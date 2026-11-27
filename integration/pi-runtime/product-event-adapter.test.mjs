import test from "node:test";
import assert from "node:assert/strict";
import { PiEventAdapter } from "../../vendor/proliferate/apps/packages/product-client/src/lib/access/pi/event-adapter.ts";
const id = "a".repeat(32);

test("projects into the existing session envelope format with contiguous cursors and outbox prompt ID", () => {
  const a = new PiEventAdapter("product-session", 12);
  const events = [...a.begin(id, "outbox-id", "study"),
    ...a.accept({kind:"text",id,delta:"Preparing"}),
    ...a.accept({kind:"tool_started",id,tool_id:"tool",name:"read"}),
    ...a.accept({kind:"tool_finished",id,tool_id:"tool",name:"read",error:true}),
    ...a.accept({kind:"text",id,delta:"Retry"}),
    ...a.accept({kind:"finished",id}),
    ...a.accept({kind:"settled",id})];
  assert.deepEqual(events.map(e=>e.seq), events.map((_,i)=>13+i));
  assert.ok(events.every(e=>e.sessionId==="product-session" && e.turnId===id));
  assert.equal(events[1].event.item.promptId,"outbox-id");
  assert.equal(events.find(e=>e.event.item?.kind==="tool_invocation" && e.event.type==="item_completed").event.item.status,"failed");
  assert.equal(events.at(-1).event.type,"turn_ended");
  assert.equal(events.filter(e=>e.event.type==="item_delta").length,2);
});

test("foreign events and mismatched tool completions are rejected", () => {
  const a = new PiEventAdapter("s");
  a.begin(id,"p","study");
  assert.throws(()=>a.accept({kind:"text",id:"b".repeat(32),delta:"wrong"}));
  assert.throws(()=>a.accept({kind:"tool_finished",id,tool_id:"missing",name:"read",error:false}));
  a.accept({kind:"tool_started",id,tool_id:"x",name:"read"});
  assert.throws(()=>a.accept({kind:"tool_finished",id,tool_id:"x",name:"write",error:false}));
});

test("cancellation and disconnection never invent a successful outcome", () => {
  const a = new PiEventAdapter("s");
  a.begin(id,"p","study");
  a.accept({kind:"tool_started",id,tool_id:"job",name:"execute"});
  a.noteCancellation(id);
  const events = a.accept({kind:"settled",id});
  assert.equal(events[0].event.item.status,"failed");
  assert.equal(events.at(-1).event.code,"PI_OUTCOME_UNCONFIRMED");
  assert.ok(!events.some(e=>e.event.type==="turn_ended"));
  a.begin("b".repeat(32),"p2","next");
  assert.equal(a.disconnect().at(-1).event.code,"PI_DISCONNECTED");
});
