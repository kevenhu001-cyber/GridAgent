import { afterEach, describe, expect, it, vi } from "vitest";
import type { DesktopPiBridge, PiEvent } from "../../../host/desktop-bridge";
import { openPiProductSession, dispatchPiPromptIntent, cancelPiProductSession,
  closePiProductSession, hasPiSessionCapacity, ownsPiSession, canSendPiSession,
  getPiSessionSelection, PI_MAX_LIVE_SESSIONS } from "./product-session";
import { getSessionRecord, removeSessionRecord } from "#product/stores/sessions/session-records";
import { useSessionIntentStore } from "#product/stores/sessions/session-intent-store";
import { useSessionIngestStore } from "#product/stores/sessions/session-ingest-store";

const opened:string[]=[];
// Unique host ids across the whole file so a leaked binding from a failed
// test can never masquerade as an identity collision in a later one.
let sessionSeq=0;
let turnSeq=0;
let cleanup:{queues:Map<string,PiEvent[]>;turns:Map<string,string>}|null=null;

// Each host session gets its own event queue and turn ids, mirroring the
// per-process workers the Tauri host now admits independently.
function fixture() {
  const queues=new Map<string,PiEvent[]>();
  const turns=new Map<string,string>();
  const bridge:DesktopPiBridge={
    mode:vi.fn(async()=>true), matchesWorkspace:vi.fn(async()=>true),
    open:vi.fn(async()=>{
      const id=(++sessionSeq).toString(16).padStart(32,"0");
      queues.set(id,[{kind:"ready",version:1}]);return id;
    }),
    prompt:vi.fn(async(sessionId:string)=>{
      const id=(++turnSeq).toString(16).padStart(32,"0");
      turns.set(sessionId,id);
      queues.get(sessionId)!.push({kind:"started",id});
      return id;
    }),
    abort:vi.fn(async()=>{}),
    poll:vi.fn(async(sessionId:string)=>queues.get(sessionId)?.splice(0)??[]),
    close:vi.fn(async(sessionId:string)=>{queues.delete(sessionId);turns.delete(sessionId);}),
  };
  cleanup={queues,turns};
  return {bridge,queues,turns};
}
async function open(bridge:DesktopPiBridge,index:number,modelId=`model-${index}`) {
  const id=await openPiProductSession({bridge,workspaceId:"workspace",workspacePath:"/project",
    selection:{provider:"openai",modelId}});
  opened.push(id);
  return id;
}
function enqueue(sessionId:string,promptId:string,text=`calculate ${promptId}`) {
  return useSessionIntentStore.getState().enqueuePrompt({clientPromptId:promptId,clientSessionId:sessionId,
    materializedSessionId:sessionId,workspaceId:"workspace",text,blocks:[{type:"text",text}]});
}
function settle(queues:Map<string,PiEvent[]>,sessionId:string,turnId:string,delta="done") {
  queues.get(sessionId)!.push({kind:"text",id:turnId,delta},{kind:"settled",id:turnId});
}
afterEach(async()=>{
  // Unblock any turn a failed assertion left draining so bindings release.
  for(const id of opened) {
    const turn=cleanup?.turns.get(id);
    if(turn&&cleanup?.queues.has(id)) settle(cleanup.queues,id,turn);
  }
  for(const id of opened.splice(0)){
    try{await closePiProductSession(id);}catch{/* already closed or busy */}
    removeSessionRecord(id);
  }
  cleanup=null;
  useSessionIntentStore.getState().clear();
  useSessionIngestStore.getState().clear();
});

describe("multiple live native Pi sessions",()=>{
  it("admits independent sessions with isolated prompts and transcripts",async()=>{
    const {bridge,queues,turns}=fixture();
    const first=await open(bridge,0),second=await open(bridge,1);
    expect(first).not.toBe(second);
    expect(ownsPiSession(first)).toBe(true);
    expect(ownsPiSession(second)).toBe(true);
    expect(canSendPiSession(first,"workspace")).toBe(true);
    expect(canSendPiSession(second,"workspace")).toBe(true);
    expect(getPiSessionSelection(first)?.modelId).toBe("model-0");
    expect(getPiSessionSelection(second)?.modelId).toBe("model-1");

    const entryA=enqueue(first,"prompt-a"),entryB=enqueue(second,"prompt-b");
    const runningA=dispatchPiPromptIntent(entryA);
    const runningB=dispatchPiPromptIntent(entryB);
    await vi.waitFor(()=>expect(getSessionRecord(first)?.status).toBe("running"));
    await vi.waitFor(()=>expect(getSessionRecord(second)?.status).toBe("running"));
    // Only session A settles; B keeps its own live turn untouched.
    settle(queues,first,turns.get(first)!);
    await runningA;
    expect(getSessionRecord(first)?.transcript.turnOrder).toEqual([turns.get(first)]);
    expect(getSessionRecord(second)?.transcript.turnOrder ?? []).not.toContain(turns.get(first)!);
    expect(getSessionRecord(second)?.status).toBe("running");
    settle(queues,second,turns.get(second)!,"beta");
    await runningB;
    expect(getSessionRecord(second)?.status).toBe("idle");
    expect(getSessionRecord(second)?.transcript.turnOrder).toEqual([turns.get(second)]);
    expect(bridge.prompt).toHaveBeenCalledTimes(2);
    expect(bridge.prompt).toHaveBeenCalledWith(first,"calculate prompt-a");
    expect(bridge.prompt).toHaveBeenCalledWith(second,"calculate prompt-b");
  });

  it("keeps the surviving session usable after closing another",async()=>{
    const {bridge,queues,turns}=fixture();
    const first=await open(bridge,0),second=await open(bridge,1);
    await closePiProductSession(first);
    expect(ownsPiSession(first)).toBe(false);
    expect(ownsPiSession(second)).toBe(true);
    expect(canSendPiSession(second,"workspace")).toBe(true);
    const entry=enqueue(second,"after-close");
    const running=dispatchPiPromptIntent(entry);
    await vi.waitFor(()=>expect(getSessionRecord(second)?.status).toBe("running"));
    settle(queues,second,turns.get(second)!);
    await running;
    expect(getSessionRecord(second)?.status).toBe("idle");
    // A closed session id can no longer dispatch.
    const stale=enqueue(first,"stale");
    await dispatchPiPromptIntent(stale);
    expect(useSessionIntentStore.getState().entriesById[stale.intentId])
      .toMatchObject({deliveryState:"failed_before_dispatch"});
  });

  it("enforces the live-session bound including in-flight opens",async()=>{
    const {bridge}=fixture();
    for(let i=0;i<PI_MAX_LIVE_SESSIONS;i++) await open(bridge,i);
    expect(hasPiSessionCapacity()).toBe(false);
    await expect(openPiProductSession({bridge,workspaceId:"workspace",workspacePath:"/project",
      selection:{provider:"openai",modelId:"overflow"}})).rejects.toThrow("session limit");
    expect(bridge.open).toHaveBeenCalledTimes(PI_MAX_LIVE_SESSIONS);
    await closePiProductSession(opened[0]!);
    expect(hasPiSessionCapacity()).toBe(true);
  });

  it("isolates cancellation to the addressed session",async()=>{
    const {bridge,queues,turns}=fixture();
    const first=await open(bridge,0),second=await open(bridge,1);
    const entryA=enqueue(first,"cancel-a"),entryB=enqueue(second,"send-b");
    const runningA=dispatchPiPromptIntent(entryA);
    const runningB=dispatchPiPromptIntent(entryB);
    await vi.waitFor(()=>expect(getSessionRecord(first)?.status).toBe("running"));
    await vi.waitFor(()=>expect(getSessionRecord(second)?.status).toBe("running"));
    await cancelPiProductSession(first);
    expect(bridge.abort).toHaveBeenCalledTimes(1);
    expect(bridge.abort).toHaveBeenCalledWith(first,turns.get(first));
    // Session B's turn is unaffected by A's cancellation.
    expect(getSessionRecord(second)?.status).toBe("running");
    settle(queues,first,turns.get(first)!);
    await runningA;
    settle(queues,second,turns.get(second)!);
    await runningB;
    expect(getSessionRecord(first)?.status).toBe("errored");
    expect(getSessionRecord(second)?.status).toBe("idle");
  });
});
