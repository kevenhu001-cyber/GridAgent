import test from "node:test";
import assert from "node:assert/strict";
import { PiEventAdapter } from "../../vendor/proliferate/apps/packages/product-client/src/lib/access/pi/event-adapter.ts";
import { createTranscriptState, reduceEventBatch } from "../../vendor/proliferate/anyharness/sdk/dist/reducer/transcript.js";

test("original reducer renders native Pi text, user prompt and failed tool", () => {
  const id = "a".repeat(32);
  const adapter = new PiEventAdapter("session");
  const events = [...adapter.begin(id, "prompt", "study"),
    ...adapter.accept({kind:"text",id,delta:"prepare "}),
    ...adapter.accept({kind:"text",id,delta:"study"}),
    ...adapter.accept({kind:"tool_started",id,tool_id:"tool",name:"read"}),
    ...adapter.accept({kind:"tool_finished",id,tool_id:"tool",name:"read",error:true}),
    ...adapter.accept({kind:"settled",id})];
  const state = reduceEventBatch(createTranscriptState("session"), events);
  const items = state.turnsById[id].itemOrder.map(key => state.itemsById[key]);
  assert.deepEqual(items.map(item=>item.kind), ["user_message","assistant_prose","tool_call"]);
  assert.equal(items[0].promptId,"prompt");
  assert.equal(items[1].text,"prepare study");
  assert.equal(items[1].isStreaming,false);
  assert.equal(items[2].status,"failed");
  assert.equal(items[2].toolCallId,"tool");
  assert.equal(state.isStreaming,false);
  assert.equal(state.lastSeq,events.at(-1).seq);
  assert.equal(state.unknownEvents.length,0);
});

test("interrupted computation is not shown as a successful tool or turn", () => {
  const id = "b".repeat(32);
  const adapter = new PiEventAdapter("session");
  const events = [...adapter.begin(id,"p","study"),
    ...adapter.accept({kind:"tool_started",id,tool_id:"job",name:"execute"}),
    ...adapter.disconnect()];
  const state = reduceEventBatch(createTranscriptState("session"),events);
  const items = state.turnsById[id].itemOrder.map(key=>state.itemsById[key]);
  assert.equal(items[1].status,"failed");
  assert.equal(items[2].kind,"error");
  assert.equal(state.isStreaming,false);
  assert.equal(state.turnsById[id].stopReason,null);
});
