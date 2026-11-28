import { describe, expect, it, vi } from "vitest";
import type { DesktopPiBridge, PiEvent } from "../../../host/desktop-bridge";
import { PiSessionController } from "./session-controller";

function fixture() {
  let events: PiEvent[] = [{kind: "ready", version: 1}];
  const bridge: DesktopPiBridge = {
    mode: vi.fn(async () => true),
    matchesWorkspace: vi.fn(async () => true),
    open: vi.fn(async () => "session-1"),
    prompt: vi.fn(async () => "request-1"),
    abort: vi.fn(async () => {}),
    poll: vi.fn(async () => {const batch = events; events = []; return batch;}),
    close: vi.fn(async () => {}),
  };
  return {bridge, controller: new PiSessionController(bridge),
    push: (...batch: PiEvent[]) => {events.push(...batch);}};
}

describe("native Pi session controller", () => {
  it("retains identity, text and tool events and waits for settlement", async () => {
    const {bridge, controller, push} = fixture();
    const received: PiEvent[] = [];
    controller.subscribe((_state, events) => received.push(...events));
    await controller.open("/project");
    expect(controller.getSnapshot().status).toBe("ready");
    await controller.prompt("simulate");
    expect(bridge.prompt).toHaveBeenCalledWith("session-1", "simulate");
    push({kind: "text", id: "request-1", delta: "result"},
      {kind: "tool_started", id: "request-1", tool_id: "tool-1", name: "read"},
      {kind: "finished", id: "request-1"});
    await controller.poll();
    expect(controller.getSnapshot().status).toBe("running");
    await expect(controller.prompt("second")).rejects.toThrow();
    await controller.cancel();
    expect(bridge.abort).toHaveBeenCalledWith("session-1", "request-1");
    expect(controller.getSnapshot().status).toBe("cancelling");
    push({kind: "settled", id: "request-1"});
    await controller.poll();
    expect(controller.getSnapshot().status).toBe("ready");
    expect(received.map(e => e.kind)).toEqual(["ready", "text", "tool_started", "finished", "settled"]);
    await controller.close();
    expect(bridge.close).toHaveBeenCalledWith("session-1");
  });

  it("never automatically replays a failed submission", async () => {
    const {bridge, controller} = fixture();
    await controller.open("/project");
    vi.mocked(bridge.prompt).mockRejectedValueOnce(new Error("transport failure"));
    await expect(controller.prompt("simulate")).rejects.toThrow("not confirmed");
    expect(controller.getSnapshot().status).toBe("failed");
    await expect(controller.prompt("simulate")).rejects.toThrow();
    expect(bridge.prompt).toHaveBeenCalledTimes(1);
  });

  it("rejects cross-request events and preserves the failure", async () => {
    const {bridge, controller, push} = fixture();
    await controller.open("/project");
    await controller.prompt("simulate");
    push({kind: "text", id: "wrong", delta: "wrong"});
    await expect(controller.poll()).rejects.toThrow();
    expect(controller.getSnapshot().status).toBe("failed");
    expect(controller.getSnapshot().requestId).toBe("request-1");
    // The host decides whether an interrupted worker remains active.
    await controller.close();
    expect(bridge.close).toHaveBeenCalledWith("session-1");
  });

  it("does not label provider failure as a successful turn", async () => {
    const {controller, push} = fixture();
    await controller.open("/project");
    await controller.prompt("simulate");
    push({kind: "error", id: "request-1", code: "provider_error"},
      {kind: "settled", id: "request-1"});
    await controller.poll();
    expect(controller.getSnapshot().status).toBe("failed");
    expect(controller.getSnapshot().requestId).toBeNull();
  });
});
