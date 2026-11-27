// @vitest-environment jsdom
import { cleanup, renderHook, act, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { usePiModelSelector } from "./use-pi-model-selector";
import { useUserPreferencesStore } from "#product/stores/preferences/user-preferences-store";
import { PI_MODEL_PREFERENCE_KEY } from "#product/lib/access/pi/model-selector";

const host = vi.hoisted(()=>({desktop:{pi:{
  mode:vi.fn(async()=>true),
  listModels:vi.fn(async()=>[{provider:"openai",id:"model-a",name:"Model A"}]),
  credentials:{list:vi.fn(async()=>[{provider:"openai",configured:true}])},
}}}));
vi.mock("@proliferate/product-client/host/ProductHostProvider",()=>({useProductHost:()=>host}));

afterEach(()=>{cleanup();vi.clearAllMocks();useUserPreferencesStore.setState({_hydrated:false,defaultChatModelIdByAgentKind:{}});});

it("feeds the original picker props and persists a native choice without replacing legacy defaults",async()=>{
  useUserPreferencesStore.setState({_hydrated:true,defaultChatAgentKind:"claude",defaultChatModelIdByAgentKind:{claude:"legacy"}});
  const client=new QueryClient({defaultOptions:{queries:{retry:false}}});
  const wrapper=({children}:{children:ReactNode})=><QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const {result}=renderHook(()=>usePiModelSelector(),{wrapper});
  await waitFor(()=>expect(result.current.props.groups[0]?.models[0]?.modelId).toBe("model-a"));
  act(()=>result.current.props.onSelect({kind:"openai",modelId:"model-a"}));
  expect(useUserPreferencesStore.getState().defaultChatAgentKind).toBe("claude");
  expect(useUserPreferencesStore.getState().defaultChatModelIdByAgentKind).toEqual({claude:"legacy",[PI_MODEL_PREFERENCE_KEY]:"openai:model-a"});
  expect(result.current.props.currentModel?.displayName).toBe("Model A");
});
