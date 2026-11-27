import test from "node:test";
import assert from "node:assert/strict";
import { PiSessionController } from "../../vendor/proliferate/apps/packages/product-client/src/lib/access/pi/session-controller.ts";

function fixture() {
  const events = [{kind: "ready", version: 1}];
  const calls = [];
  const bridge = {
    open: async () => "session",
    prompt: async (session, text) => { calls.push(["prompt", session, text]); return "turn"; },
    abort: async (session, turn) => { calls.push(["abort", session, turn]); },
    poll: async () => events.splice(0),
    close: async session => { calls.push(["close", session]); },
  };
  return {bridge, calls, events, controller: new PiSessionController(bridge)};
}

test("shared product session drives a native turn and settles after cancellation", async () => {
  const {controller, events, calls} = fixture();
  await controller.open("/project");
  await controller.prompt("study");
  const received = [];
  controller.subscribe((_snapshot, batch) => received.push(...batch));
  events.push({kind: "tool_started", id: "turn", tool_id: "tool", name: "read"},
    {kind: "text", id: "turn", delta: "answer"}, {kind: "finished", id: "turn"});
  await controller.poll();
  assert.equal(controller.getSnapshot().status, "running");
  await assert.rejects(() => controller.prompt("another"));
  await controller.cancel();
  events.push({kind: "settled", id: "turn"});
  assert.equal((await controller.drainTurn()).status, "ready");
  assert.equal(received[0].tool_id, "tool");
  await controller.close();
  assert.deepEqual(calls, [["prompt","session","study"],["abort","session","turn"],["close","session"]]);
});

test("failed submission is not retried", async () => {
  const {controller, bridge} = fixture();
  let count = 0;
  bridge.prompt = async () => { count++; throw new Error("failed"); };
  await controller.open("/project");
  await assert.rejects(() => controller.prompt("study"));
  await assert.rejects(() => controller.prompt("study"));
  assert.equal(count, 1);
  assert.equal(controller.getSnapshot().status, "failed");
});

test("failed turn settles without success or an automatic replay", async () => {
  const {controller, events} = fixture();
  await controller.open("/project");
  await controller.prompt("study");
  events.push({kind: "error", id: "turn", code: "provider_error"}, {kind: "settled", id: "turn"});
  assert.equal((await controller.drainTurn()).status, "failed");
  assert.equal(controller.getSnapshot().requestId, null);
});

test("foreign event fails closed", async () => {
  const {controller, events} = fixture();
  await controller.open("/project");
  await controller.prompt("study");
  events.push({kind: "text", id: "foreign", delta: "bad"});
  await assert.rejects(() => controller.drainTurn());
  assert.equal(controller.getSnapshot().status, "failed");
});
