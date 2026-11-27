import test from "node:test";
import assert from "node:assert/strict";
import { listPiModels, modelRegistry, providerIds } from "./model-catalog.mjs";

test("real pinned SDK catalog supplies selectable chat models without credentials", () => {
  const rows = listPiModels();
  for (const provider of providerIds) {
    const group = rows.filter(row => row.provider === provider);
    assert.ok(group.length > 0, provider);
    assert.equal(new Set(group.map(row => row.id)).size, group.length);
    const registry = modelRegistry(provider);
    for (const row of group) {
      assert.ok(row.id && row.name);
      assert.deepEqual(Object.keys(row).sort(), ["id", "name", "provider"]);
      assert.ok(registry.getModel(provider, row.id));
    }
  }
  assert.throws(() => modelRegistry("external-agent"));
});
