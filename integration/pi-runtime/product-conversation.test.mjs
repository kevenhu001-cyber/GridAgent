import test from "node:test";
import assert from "node:assert/strict";
import { applyPiEvent, settlePiTurn } from "../../vendor/proliferate/apps/packages/product-client/src/lib/access/pi/conversation-events.ts";

const start = () => ({id: 1, prompt: "study", segments: [], status: "running"});
test("public transcript keeps text and tool ordering and independent tool status", () => {
  const events = [
    {kind:"text", id:"turn", delta:"Preparing "},
    {kind:"text", id:"turn", delta:"study"},
    {kind:"tool_started", id:"turn", tool_id:"call", name:"read"},
    {kind:"tool_finished", id:"turn", tool_id:"call", name:"read", error:true},
    {kind:"text", id:"turn", delta:"Retry with corrected input"},
  ];
  const turn = events.reduce(applyPiEvent, start());
  assert.deepEqual(turn.segments, [
    {kind:"text",text:"Preparing study"},
    {kind:"tool",id:"call",name:"read",status:"error"},
    {kind:"text",text:"Retry with corrected input"}
  ]);
  assert.equal(settlePiTurn(turn,"complete").segments[1].status,"error");
});

test("settlement does not represent an unfinished scientific operation as successful", () => {
  const turn = applyPiEvent(start(), {kind:"tool_started",id:"turn",tool_id:"job",name:"execute_python"});
  assert.equal(settlePiTurn(turn,"cancel_requested").segments[0].status,"interrupted");
  assert.equal(settlePiTurn(turn,"failed").status,"failed");
});
