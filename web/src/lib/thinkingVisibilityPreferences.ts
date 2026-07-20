// Persisted, per-device preference for whether reasoning ("thinking") blocks
// render inline in the chat stream.
//
// Reasoning blocks (see ReasoningView / BlockRenderer's "reasoning" case)
// already stream to the web client and render as a collapsible section
// whenever the model emits one. That's useful for debugging an agent's
// decisions, but it's noise for everyday use, especially on narrow mobile
// viewports — see omnigent-ai/omnigent#2180. This preference lets a user opt
// in to seeing them. Off by default so casual sessions stay uncluttered.
//
// This is a device-local UI filter, not a session setting: the underlying
// reasoning data is unaffected (and still streams/persists as normal), only
// whether this browser renders it. It lives in localStorage like the other
// `*Preferences` helpers rather than round-tripping through session state.

const STORAGE_KEY = "omnigent:show-thinking";

export const DEFAULT_SHOW_THINKING = false;

/**
 * Read the persisted "show thinking" preference. Returns the default (off)
 * when nothing is stored, on a server render (no `window`), or when the
 * stored value is malformed — never throws, so a corrupt entry can't break
 * app boot.
 */
export function readShowThinking(): boolean {
  if (typeof window === "undefined") return DEFAULT_SHOW_THINKING;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw === null) return DEFAULT_SHOW_THINKING;
    return raw === "true";
  } catch {
    return DEFAULT_SHOW_THINKING;
  }
}

/**
 * Persist the "show thinking" preference. Swallows quota/access errors so a
 * failed write can't break the app.
 */
export function writeShowThinking(value: boolean): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, value ? "true" : "false");
  } catch {
    // localStorage quota or access errors shouldn't break the app.
  }
}
