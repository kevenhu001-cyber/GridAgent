import test from "node:test";
import assert from "node:assert/strict";
import { buildPiModelSelector, readPiModelPreference, updatePiModelPreference, resolvePiModelPreference } from "../../vendor/proliferate/apps/packages/product-client/src/lib/access/pi/model-selector.ts";

test("Pi data uses original picker grouping and blocks unconfigured credentials", () => {
  const selections=[];
  const props=buildPiModelSelector({
    models:[{provider:"openai",id:"a",name:"A"},{provider:"anthropic",id:"b",name:"B"}],
    credentials:[{provider:"openai",configured:true},{provider:"anthropic",configured:false}],
    selection:{kind:"openai",modelId:"a"},onSelect:s=>selections.push(s),
  });
  assert.equal(props.currentModel.displayName,"A");
  assert.equal(props.groups[0].models[0].isUnsupported,false);
  assert.equal(props.groups[1].models[0].isUnsupported,true);
  props.onSelect({kind:"anthropic",modelId:"b"});
  props.onSelect({kind:"openai",modelId:"unknown"});
  props.onSelect({kind:"openai",modelId:"a"});
  assert.deepEqual(selections,[{kind:"openai",modelId:"a"}]);
});

test("native choice reuses persisted preference map without changing legacy launch defaults",()=>{
 const legacy={claude:"legacy-model"};
 const saved=updatePiModelPreference(legacy,{kind:"openai",modelId:"model:variant"});
 assert.equal(saved.claude,"legacy-model");
 assert.deepEqual(readPiModelPreference(saved),{provider:"openai",modelId:"model:variant"});
 const models=[{provider:"openai",id:"model:variant",name:"Model"}];
 assert.equal(resolvePiModelPreference(saved,models,[]),null);
 assert.deepEqual(resolvePiModelPreference(saved,models,[{provider:"openai",configured:true}]),{kind:"openai",modelId:"model:variant"});
 assert.equal(readPiModelPreference({"gridagent.pi.model":"claude:legacy"}),null);
 assert.throws(()=>updatePiModelPreference(legacy,{kind:"claude",modelId:"legacy"}));
});
