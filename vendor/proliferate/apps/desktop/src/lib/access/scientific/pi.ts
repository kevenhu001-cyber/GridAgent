import { invoke } from "@tauri-apps/api/core";
import type { DesktopPiBridge, PiEvent } from "@proliferate/product-client/host/desktop-bridge";

/** Debug bridge only; the native host selects the executable and workspace. */
export const embeddedPi: DesktopPiBridge = {
  credentials: {
    list: () => invoke("pi_list_credentials"),
    save: (provider, value) => invoke("pi_save_credential", { provider, value }),
    remove: provider => invoke("pi_delete_credential", { provider }),
  },
  listModels: () => invoke("pi_list_models"),
  history: {
    list: workspacePath => invoke("pi_list_history", { workspacePath }),
    dismiss: sessionId => invoke("pi_dismiss_history", { sessionId }),
  },
  mode: () => invoke<boolean>("pi_mode"),
  matchesWorkspace: path => invoke<boolean>("pi_matches_workspace", { path }),
  open: (workspacePath, selection) => invoke<string>("pi_open", { workspacePath, selection: selection ?? null }),
  resume: (workspacePath, sessionId, revision) => invoke("pi_resume", { workspacePath, sessionId, revision }),
  prompt: (sessionId, text) => invoke<string>("pi_prompt", { sessionId, text }),
  abort: (sessionId, id) => invoke<void>("pi_abort", { sessionId, id }),
  poll: sessionId => invoke<PiEvent[]>("pi_poll", { sessionId }),
  close: sessionId => invoke<void>("pi_close", { sessionId }),
};
