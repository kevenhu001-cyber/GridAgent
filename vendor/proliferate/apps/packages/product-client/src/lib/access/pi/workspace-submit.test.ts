import { afterEach, expect, it, vi } from "vitest";
import type { Workspace } from "@anyharness/sdk";
import type { DesktopPiBridge, PiEvent } from "../../../host/desktop-bridge";
import { submitPiWorkspacePrompt } from "./workspace-submit";
import { closePiProductSession, ownsPiSession } from "./product-session";
import { getSessionRecord, removeSessionRecord } from "#product/stores/sessions/session-records";
import { useSessionIntentStore } from "#product/stores/sessions/session-intent-store";

const id="c".repeat(32);
const workspace:Workspace={
  id:"workspace",kind:"worktree",repoRootId:"repo",path:"/project",surface:"standard",
  originalBranch:"main",currentBranch:"main",availability:"available",lifecycleState:"active",
  createdAt:"2026-11-28T00:00:00Z",updatedAt:"2026-11-28T00:00:00Z",
};
function fixture() {
  const events:PiEvent[]=[{kind:"ready",version:1}];
  const bridge:DesktopPiBridge={
    mode:vi.fn(async()=>true), matchesWorkspace:vi.fn(async()=>true),
    open:vi.fn(async()=>id), prompt:vi.fn(async()=>"d".repeat(32)),
    abort:vi.fn(async()=>{}), poll:vi.fn(async()=>events.splice(0)),close:vi.fn(async()=>{}),
  };
  const input={bridge,workspace,selection:{kind:"openai",modelId:"model"},activeSessionId:null,
    text:"calculate",blocks:[{type:"text" as const,text:"calculate"}],attachmentSnapshots:[],promptId:"prompt",isCurrent:()=>true};
  const deps={activate:vi.fn(),enqueue:vi.fn(async(sessionId:string,promptId:string)=>{
    useSessionIntentStore.getState().enqueuePrompt({clientPromptId:promptId,clientSessionId:sessionId,
      materializedSessionId:sessionId,workspaceId:workspace.id,text:input.text,blocks:input.blocks});
  })};
  return {input,deps,bridge};
}
afterEach(async()=>{
  useSessionIntentStore.getState().clear();
  if(ownsPiSession(id)) await closePiProductSession(id);
  removeSessionRecord(id);
});
it("opens the native worker, enqueues in the original outbox and activates the existing tab",async()=>{
  const {input,deps,bridge}=fixture();
  expect(await submitPiWorkspacePrompt(input,deps)).toBe(id);
  expect(bridge.open).toHaveBeenCalledWith("/project",{provider:"openai",modelId:"model"});
  expect(bridge.prompt).not.toHaveBeenCalled();
  expect(deps.activate).toHaveBeenCalledWith(id);
  expect(useSessionIntentStore.getState().entriesById.prompt).toMatchObject({clientSessionId:id,deliveryState:"waiting_for_session"});
  await expect(closePiProductSession(id)).rejects.toThrow("pending prompt");
});
it("refuses a mismatched workspace without opening the worker",async()=>{
  const {input,deps,bridge}=fixture();
  vi.mocked(bridge.matchesWorkspace).mockResolvedValue(false);
  await expect(submitPiWorkspacePrompt(input,deps)).rejects.toThrow("not authorized");
  expect(bridge.open).not.toHaveBeenCalled();
  expect(deps.enqueue).not.toHaveBeenCalled();
});
it("discards an empty worker if the user switches workspace during startup",async()=>{
  const {input,deps,bridge}=fixture();let current=true;
  vi.mocked(bridge.open).mockImplementation(async()=>{current=false;return id;});
  await expect(submitPiWorkspacePrompt({...input,isCurrent:()=>current},deps)).rejects.toThrow("changed");
  expect(bridge.close).toHaveBeenCalledWith(id);
  expect(deps.enqueue).not.toHaveBeenCalled();
  expect(deps.activate).not.toHaveBeenCalled();
  expect(getSessionRecord(id)).toBeNull();
});
it("does not mistake a post-enqueue exception for an unsent prompt",async()=>{
  const {input,deps,bridge}=fixture();
  const enqueue=deps.enqueue;
  const outcome=await submitPiWorkspacePrompt(input,{...deps,enqueue:async(sessionId,promptId)=>{
    await enqueue(sessionId,promptId);throw new Error("after store write");
  }});
  expect(outcome).toBe(id);
  expect(bridge.close).not.toHaveBeenCalled();
  expect(useSessionIntentStore.getState().entriesById.prompt).toBeDefined();
});
