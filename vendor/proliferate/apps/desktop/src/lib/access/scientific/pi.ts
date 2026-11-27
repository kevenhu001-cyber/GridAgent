import { invoke } from "@tauri-apps/api/core";
import type { DesktopPiBridge, PiEvent } from "@proliferate/product-client/host/desktop-bridge";

/** Debug bridge only; the native host selects the executable and workspace. */
export const embeddedPi: DesktopPiBridge = {
  open: () => invoke<string>("pi_open"),
  prompt: (sessionId, text) => invoke<string>("pi_prompt", { sessionId, text }),
  abort: (sessionId, id) => invoke<void>("pi_abort", { sessionId, id }),
  poll: sessionId => invoke<PiEvent[]>("pi_poll", { sessionId }),
  close: sessionId => invoke<void>("pi_close", { sessionId }),
};
