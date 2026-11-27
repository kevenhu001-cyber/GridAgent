import type { PromptInputBlock, Workspace } from "@anyharness/sdk";
import type { DesktopPiBridge, PiProvider } from "../../../host/desktop-bridge";
import type { PromptAttachmentSnapshot } from "#product/domain/chats/composer/prompt-attachment-snapshot";
import type { ModelSelectorSelection } from "#product/lib/domain/chat/models/model-selector-types";
import { isWorkspaceDirectoryMissing } from "#product/lib/domain/workspaces/availability";
import { canSendPiSession, openPiProductSession, closePiProductSession } from "./product-session";

/** Existing composer launch seam. The caller owns its draft, selection guard,
 * and outbox. Admission never sends a prompt directly or falls back to an agent.
 */
export async function submitPiWorkspacePrompt(input:{
  bridge:DesktopPiBridge; workspace:Workspace; selection:ModelSelectorSelection|null;
  activeSessionId:string|null; text:string; blocks:PromptInputBlock[];
  attachmentSnapshots:PromptAttachmentSnapshot[]; promptId:string; isCurrent:()=>boolean;
},deps:{activate:(id:string)=>void; enqueue:(id:string,promptId:string)=>Promise<void>}):Promise<string> {
  if (!input.isCurrent() || input.workspace.lifecycleState!=="active" || isWorkspaceDirectoryMissing(input.workspace)) throw new Error("Select an available local workspace.");
  if (input.attachmentSnapshots.length || input.blocks.length!==1 || input.blocks[0].type!=="text" ||
    !input.blocks[0].text.trim() || new TextEncoder().encode(input.blocks[0].text).length>8192)
    throw new Error("Native Pi currently supports a single text block of up to 8192 UTF-8 bytes. Your draft is preserved.");
  if (!await input.bridge.mode() || !await input.bridge.matchesWorkspace(input.workspace.path) || !input.isCurrent())
    throw new Error("Selected workspace is not authorized for native Pi.");
  let id=input.activeSessionId;
  let created=false;
  if (id) {
    if (!canSendPiSession(id,input.workspace.id)) throw new Error("This session cannot send native Pi prompts.");
  } else {
    const choice=input.selection;
    if (!choice || !["openai","anthropic","google"].includes(choice.kind)) throw new Error("Choose a configured Pi model.");
    id=await openPiProductSession({bridge:input.bridge,workspaceId:input.workspace.id,workspacePath:input.workspace.path,
      selection:{provider:choice.kind as PiProvider,modelId:choice.modelId}});
    created=true;
  }
  if (!input.isCurrent()) {
    if(created) await closePiProductSession(id);
    throw new Error("Workspace or session changed before sending. Your draft is preserved.");
  }
  // Queue before activation; no prompt transport calls from the composer.
  try {await deps.enqueue(id,input.promptId);}
  catch {if(created) await closePiProductSession(id); throw new Error("Could not enqueue the native prompt. Your draft is preserved.");}
  // An accepted outbox entry must not be replayed even if tab activation fails.
  if(created && input.isCurrent()) {
    try {deps.activate(id);} catch { /* session already exists in directory */ }
  }
  return id;
}
