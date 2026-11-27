import { describe, expect, it } from "vitest";
import { createTranscriptState, reduceEventBatch } from "@anyharness/sdk";
import { PiEventAdapter } from "./event-adapter";

describe("Pi uses the existing SDK transcript reducer", () => {
  it("renders the original user/assistant/tool item model and preserves a failed tool", () => {
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
    expect(items.map(item=>item.kind)).toEqual(["user_message","assistant_prose","tool_call"]);
    expect(items[1]).toMatchObject({text:"prepare study",isStreaming:false});
    expect(items[2]).toMatchObject({status:"failed",toolCallId:"tool"});
    expect(state.isStreaming).toBe(false);
  });
});
