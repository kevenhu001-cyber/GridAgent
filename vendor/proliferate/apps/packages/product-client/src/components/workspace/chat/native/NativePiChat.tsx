import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import type { DesktopPiBridge } from "@proliferate/product-client/host/desktop-bridge";
import { PiConversation, type PiConversationSnapshot } from "#product/lib/access/pi/conversation";
import { ChatComposerDock } from "../input/ChatComposerDock";
import { ChatComposerSurface } from "../composer/ChatComposerSurface";
import { ChatComposerControlRowFrame } from "../composer/ChatComposerControlRowFrame";
import { ComposerTextareaFrame } from "#product/primitives/patterns/composer/ComposerTextareaFrame";
import { ComposerRichTextEditor } from "../input/ComposerRichTextEditor";
import { ChatComposerActions } from "../input/ChatComposerActions";
import { UserMessage } from "../transcript/UserMessage";
import { AssistantMessage } from "../transcript/AssistantMessage";
import { CHAT_COLUMN_CLASSNAME, CHAT_SURFACE_GUTTER_CLASSNAME } from "#product/config/chat-layout";

// The debug host permits one worker. Preserve its controller across chat pane
// unmounts so navigation cannot orphan an in-flight turn or create a new one.
const conversations = new WeakMap<DesktopPiBridge, PiConversation>();
function conversationFor(bridge: DesktopPiBridge, path: string) {
  const existing = conversations.get(bridge);
  if (existing) return existing.workspacePath === path ? existing : null;
  const conversation = new PiConversation(bridge, path);
  conversations.set(bridge, conversation);
  return conversation;
}

export function NativePiChat({bridge, workspacePath}: {
  bridge: DesktopPiBridge; workspacePath: string;
}) {
  const conversation = conversationFor(bridge, workspacePath);
  if (!conversation) return <div role="status" className="p-6 text-chat text-muted-foreground">Return to the original Pi workspace before continuing.</div>;
  return <ConversationView conversation={conversation} />;
}

function ConversationView({conversation}: {conversation: PiConversation}) {
  const state: PiConversationSnapshot = useSyncExternalStore(conversation.subscribe, conversation.getSnapshot);
  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  const status = state.session.status;
  const running = status === "running" || status === "cancelling";
  const blocked = !["closed", "ready"].includes(status);
  const canSubmit = !blocked && Boolean(draft.trim());
  useEffect(() => {
    const element = scrollRef.current;
    if (element && stick.current) element.scrollTop = element.scrollHeight;
  }, [state]);
  const submit = () => {
    if (!canSubmit) return;
    const text = draft;
    setDraft("");
    void conversation.send(text).catch(() => {
      // The controller owns uncertain submission state; do not retry.
    });
  };
  return <div className="chat-selection-root flex h-full min-h-0 flex-1 flex-col overflow-hidden" data-focus-zone="chat">
    <div ref={scrollRef} onScroll={event => {
      const el = event.currentTarget;
      stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    }} className="min-h-0 flex-1 overflow-y-auto pt-6">
      <div className={CHAT_SURFACE_GUTTER_CLASSNAME}>
        <div className={CHAT_COLUMN_CLASSNAME + " flex flex-col gap-6 pb-6"} data-telemetry-mask>
          {state.turns.length === 0 && <div className="py-16 text-center">
            <h2 className="text-title font-semibold">What would you like to model?</h2>
            <p className="mt-3 text-chat text-muted-foreground">Describe an engineering problem, simulation, or optimization task.</p>
          </div>}
          {state.turns.map(turn => <section key={turn.id} className="flex min-w-0 flex-col gap-4">
            <UserMessage sessionId={null} content={turn.prompt} />
            {turn.segments.map((segment, index) => segment.kind === "text"
              ? <AssistantMessage key={index} content={segment.text} isStreaming={turn.status === "running" && index === turn.segments.length - 1} />
              : <div key={segment.id} className="flex items-center gap-2 text-chat text-muted-foreground" role="status">
                  <span>{segment.name}</span>
                  <span>{segment.status === "running" ? "Running…" : segment.status === "error" ? "Failed" : segment.status === "interrupted" ? "Interrupted" : "Finished"}</span>
                </div>)}
            {turn.status === "failed" && <p role="alert" className="text-chat text-muted-foreground">Turn not confirmed. Check the workspace before retrying.</p>}
            {turn.status === "cancelled" && <p className="text-chat text-muted-foreground">Generation stopped. Scientific jobs may still require inspection.</p>}
          </section>)}
        </div>
      </div>
    </div>
    <ChatComposerDock backdrop={false}>
      <ChatComposerSurface className="border border-border bg-card">
        <ComposerTextareaFrame topInset="standard">
          <ComposerRichTextEditor value={draft} onChange={value => setDraft(value)}
            canSubmit={canSubmit} onSubmit={submit} disabled={blocked}
            placeholder={state.turns.length ? "Ask a follow-up" : "Describe a scientific task"} />
        </ComposerTextareaFrame>
        <ChatComposerControlRowFrame leading={<span className="px-2 text-chat text-muted-foreground">GridAgent · Pi preview</span>}
          action={<ChatComposerActions isRunning={status === "running"} isEmpty={!draft.trim()}
            isDisabled={blocked || running} onSubmit={submit}
            onCancel={() => {void conversation.cancel().catch(() => {});}} />} />
      </ChatComposerSurface>
      <div className="mt-2 truncate text-center text-chat text-muted-foreground" title={conversation.workspacePath} data-telemetry-mask>
        {conversation.workspacePath} · {status}
      </div>
      {state.session.failure && <p role="alert" className="mt-2 text-center text-chat text-muted-foreground">{state.session.failure}</p>}
      {status === "ready" && <button type="button" className="mt-2 text-chat text-muted-foreground hover:text-foreground"
        onClick={() => {void conversation.newChat().catch(() => {});}}>New chat</button>}
    </ChatComposerDock>
  </div>;
}
