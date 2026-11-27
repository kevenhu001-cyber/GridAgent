import type { PiCredentialStatus, PiModelRecord, PiProvider, PiModelSelection } from "../../../host/desktop-bridge";
import type { ModelSelectorGroup, ModelSelectorProps, ModelSelectorSelection } from "../../domain/chat/models/model-selector-types";

const labels: Record<PiProvider, string> = {openai: "OpenAI", anthropic: "Anthropic", google: "Google"};

/** Existing picker data contract. Credential presence is not provider validation. */
export function buildPiModelSelector(input: {
  models: readonly PiModelRecord[];
  credentials: readonly PiCredentialStatus[];
  selection: ModelSelectorSelection | null;
  onSelect: ModelSelectorProps["onSelect"];
}): ModelSelectorProps {
  const configured = new Set(input.credentials.filter(c=>c.configured).map(c=>c.provider));
  const groups: ModelSelectorGroup[] = [];
  for (const kind of Object.keys(labels) as PiProvider[]) {
    const models = input.models.filter(m=>m.provider===kind).map(m=>({
      kind, modelId:m.id, displayName:m.name, actionKind:"select" as const,
      isSelected: input.selection?.kind===kind && input.selection.modelId===m.id,
      isUnsupported: !configured.has(kind),
    }));
    if (models.length) groups.push({kind, providerDisplayName:labels[kind], models});
  }
  const selected = groups.flatMap(g=>g.models).find(m=>m.isSelected);
  return {
    connectionState:"healthy", currentModel:selected ? {kind:selected.kind,displayName:selected.displayName,pendingState:null} : null,
    groups, hasAgents:true, isLoading:false, availability:groups.length?"ready":"observed_empty",
    onSelect: selection => {
      const model=groups.flatMap(g=>g.models).find(m=>m.kind===selection.kind && m.modelId===selection.modelId);
      if (model && !model.isUnsupported) input.onSelect(selection);
    },
  };
}

// Reuse the existing persisted map. The reserved Pi slot is deliberately
// separate from legacy harness preferences and never becomes an Agent kind.
export const PI_MODEL_PREFERENCE_KEY = "gridagent.pi.model";
export function readPiModelPreference(defaults: Record<string,string>): PiModelSelection | null {
  const raw = defaults[PI_MODEL_PREFERENCE_KEY];
  if (typeof raw !== "string") return null;
  const delimiter = raw.indexOf(":");
  const provider = raw.slice(0, delimiter);
  const modelId = raw.slice(delimiter + 1);
  if (delimiter < 1 || !Object.hasOwn(labels, provider) || !modelId || modelId.length > 512 || modelId.trim() !== modelId || /[\x00-\x1f\x7f]/.test(modelId)) return null;
  return {provider: provider as PiProvider, modelId};
}

export function updatePiModelPreference(defaults: Record<string,string>, selection: ModelSelectorSelection): Record<string,string> {
  if (!Object.hasOwn(labels,selection.kind) || !selection.modelId || selection.modelId.length>512 || selection.modelId.trim()!==selection.modelId || /[\x00-\x1f\x7f]/.test(selection.modelId)) throw new Error("Invalid native Pi model selection");
  return {...defaults,[PI_MODEL_PREFERENCE_KEY]:selection.kind+":"+selection.modelId};
}

export function resolvePiModelPreference(defaults: Record<string,string>, models: readonly PiModelRecord[], credentials: readonly PiCredentialStatus[]): ModelSelectorSelection | null {
  const selected = readPiModelPreference(defaults);
  if (!selected || !models.some(m=>m.provider===selected.provider && m.id===selected.modelId)
    || !credentials.some(c=>c.provider===selected.provider && c.configured)) return null;
  return {kind:selected.provider,modelId:selected.modelId};
}
