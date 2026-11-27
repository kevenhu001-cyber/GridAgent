import test from "node:test";
import assert from "node:assert/strict";
import { buildPiModelSelector } from "../../vendor/proliferate/apps/packages/product-client/src/lib/access/pi/model-selector.ts";

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
