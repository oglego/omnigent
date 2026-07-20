// Reactive access to the "show thinking" preference (see
// thinkingVisibilityPreferences.ts). Backed by a module-level store rather
// than a plain `useState(() => read...())` in each consumer: the toggle
// control (AgentInfo panel) and the render gate (BlockRenderer) are separate
// components that both need to observe the same value and update in lockstep
// the instant the user flips the switch, without a page reload. Mirrors the
// module-level-store + `useSyncExternalStore` shape used by
// useResizableSidebar for the same reason.

import { useCallback, useSyncExternalStore } from "react";
import { readShowThinking, writeShowThinking } from "@/lib/thinkingVisibilityPreferences";

let value = readShowThinking();
const listeners = new Set<() => void>();

function setValue(next: boolean) {
  if (next === value) return;
  value = next;
  writeShowThinking(next);
  for (const l of listeners) l();
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

function getSnapshot(): boolean {
  return value;
}

function getServerSnapshot(): boolean {
  return false;
}

/** Reset module-level state. Only for use in tests. */
export function resetShowThinkingStoreForTesting(): void {
  value = readShowThinking();
  for (const l of listeners) l();
}

/**
 * Whether reasoning blocks should render in the chat stream, plus a setter.
 * Defaults to off; persisted per-device via localStorage.
 */
export function useShowThinking(): [boolean, (next: boolean) => void] {
  const current = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  const set = useCallback((next: boolean) => setValue(next), []);
  return [current, set];
}
