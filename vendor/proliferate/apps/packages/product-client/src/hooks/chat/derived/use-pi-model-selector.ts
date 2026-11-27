import { useQuery } from "@tanstack/react-query";
import { useProductHost } from "@proliferate/product-client/host/ProductHostProvider";
import { useUserPreferencesStore } from "#product/stores/preferences/user-preferences-store";
import type { ModelSelectorSelection, ModelSelectorProps } from "#product/lib/domain/chat/models/model-selector-types";
import { buildPiModelSelector, resolvePiModelPreference, updatePiModelPreference } from "#product/lib/access/pi/model-selector";

export const PI_CREDENTIAL_STATUS_QUERY_KEY = ["gridagent","pi","credential-status"] as const;

export function usePiMode() {
  const pi = useProductHost().desktop?.pi;
  const query = useQuery({
    queryKey: ["gridagent","pi","mode"],
    enabled: !!pi,
    queryFn: () => pi!.mode(),
    staleTime: Infinity,
    retry: false,
  });
  // Fail closed while native capability discovery is uncertain.
  const mode = !pi ? "legacy" : query.isError ? "unavailable"
    : query.data === true ? "native" : query.data === false ? "legacy" : "checking";
  return {pi,mode} as const;
}

/** Pure data adapter for the existing selector. No new view or preference store. */
export function usePiModelSelector(): {mode: ReturnType<typeof usePiMode>["mode"]; props: ModelSelectorProps; selection: ModelSelectorSelection | null} {
  const {pi,mode} = usePiMode();
  const defaults = useUserPreferencesStore(state=>state.defaultChatModelIdByAgentKind);
  const hydrated = useUserPreferencesStore(state=>state._hydrated);
  const models = useQuery({
    queryKey:["gridagent","pi","models"],
    enabled:mode==="native" && !!pi?.listModels,
    queryFn:()=>pi!.listModels!(),
    staleTime:Infinity, retry:false,
  });
  const credentials = useQuery({
    queryKey:PI_CREDENTIAL_STATUS_QUERY_KEY,
    enabled:mode==="native" && !!pi?.credentials,
    queryFn:()=>pi!.credentials!.list(),
    retry:false,
  });
  const unavailable = mode==="unavailable" || (mode==="native" &&
    (!pi?.listModels || !pi.credentials || models.isError || credentials.isError));
  if (mode !== "native" || unavailable || !hydrated || !models.data || !credentials.data) return {
    mode, selection:null,
    props:{nativePi:true,connectionState:unavailable?"disconnected":"connecting",currentModel:null,
      groups:[],hasAgents:false,isLoading:!unavailable,availability:unavailable?"unavailable":"observation_pending",
      onSelect:()=>{}},
  };
  const selection=resolvePiModelPreference(defaults,models.data,credentials.data);
  return {mode,selection,props:{
    ...buildPiModelSelector({models:models.data,credentials:credentials.data,selection,
      onSelect: selected=>{
        const store=useUserPreferencesStore.getState();
        if (store._hydrated) store.set("defaultChatModelIdByAgentKind",updatePiModelPreference(store.defaultChatModelIdByAgentKind,selected));
      }}),nativePi:true,
  }};
}
