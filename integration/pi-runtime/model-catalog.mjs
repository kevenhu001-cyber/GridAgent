import { createModels } from "@earendil-works/pi-ai";
import { openaiProvider } from "@earendil-works/pi-ai/providers/openai";
import { anthropicProvider } from "@earendil-works/pi-ai/providers/anthropic";
import { googleProvider } from "@earendil-works/pi-ai/providers/google";

const factories = {openai: openaiProvider, anthropic: anthropicProvider, google: googleProvider};
export const providerIds = Object.freeze(Object.keys(factories));

export function modelRegistry(provider) {
  if (provider !== undefined && !Object.hasOwn(factories, provider)) throw new Error("Unsupported model provider");
  const models = createModels();
  for (const id of provider === undefined ? providerIds : [provider]) models.setProvider(factories[id]());
  return models;
}

/** Public metadata only. Static SDK catalog, not a claim of account entitlement. */
export function listPiModels() {
  const models = modelRegistry();
  return providerIds.flatMap(provider => models.getModels(provider).map(model => ({
    provider, id: model.id, name: model.name,
  })));
}
