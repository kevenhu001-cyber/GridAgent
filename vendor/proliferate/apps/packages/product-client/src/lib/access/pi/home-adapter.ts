import type { ModelSelectorProps, ModelSelectorSelection } from "#product/lib/domain/chat/models/model-selector-types";
import type { HomeModelGate } from "#product/lib/domain/home/home-model-gate";
import type { HomeLaunchTarget } from "#product/lib/domain/home/home-next-launch";

/** Existing Home gate contract; never report an external harness install. */
export function resolvePiHomeGate(mode:"legacy"|"native"|"checking"|"unavailable",props:ModelSelectorProps,
  selection:ModelSelectorSelection|null,target:HomeLaunchTarget|null,hasSession:boolean):{
    modelGate:HomeModelGate;targetDisabledReason:string|null;canLaunchTarget:boolean
} {
  const reason=mode!=="native"?"Native Pi runtime is unavailable or starting."
    : target?.kind!=="local" || !target.existingWorkspaceId ? "Choose an existing local workspace for Pi."
    : hasSession ? "Close the current Pi session before starting another." : null;
  const selected=!!selection && props.groups.some(group=>group.models.some(model=>model.kind===selection.kind && model.modelId===selection.modelId && !model.isUnsupported));
  const modelGate:HomeModelGate=props.isLoading ? {kind:"blocked",reason:"querying"}
    : props.availability==="unavailable" ? {kind:"blocked",reason:"transport_error"}
    : selected ? {kind:"launchable"} : {kind:"selection_required"};
  return {modelGate,targetDisabledReason:reason,canLaunchTarget:reason===null};
}
