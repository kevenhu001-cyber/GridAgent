import type { PiCredentialStatus, PiModelRecord, PiProvider } from "../../../host/desktop-bridge";
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
