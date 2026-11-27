import { describe,expect,it } from "vitest";
import { resolvePiHomeGate } from "./home-adapter";
import type { ModelSelectorProps } from "#product/lib/domain/chat/models/model-selector-types";
const selection={kind:"openai",modelId:"m"};
const props:ModelSelectorProps={connectionState:"healthy",currentModel:null,hasAgents:true,isLoading:false,
  groups:[{kind:"openai",providerDisplayName:"OpenAI",models:[{...selection,displayName:"M",isUnsupported:false,isSelected:true,actionKind:"select"}]}],onSelect:()=>{}};
const target={kind:"local" as const,sourceRoot:"/project",existingWorkspaceId:"workspace"};
describe("retained Home native model gate",()=>{
  it("allows only a selected available native model and existing local target",()=>{
    expect(resolvePiHomeGate("native",props,selection,target,false)).toEqual({modelGate:{kind:"launchable"},targetDisabledReason:null,canLaunchTarget:true});
    expect(resolvePiHomeGate("native",props,null,target,false).modelGate.kind).toBe("selection_required");
    expect(resolvePiHomeGate("native",props,selection,{kind:"cowork"},false).canLaunchTarget).toBe(false);
    expect(resolvePiHomeGate("native",props,selection,{...target,existingWorkspaceId:null},false).canLaunchTarget).toBe(false);
    expect(resolvePiHomeGate("native",props,selection,target,true).canLaunchTarget).toBe(false);
    expect(resolvePiHomeGate("checking",props,selection,target,false).canLaunchTarget).toBe(false);
  });
});
