import type { ReliabilityStore } from "./redis.js";

export type CircuitStateName = "closed" | "open" | "half_open";

export type CircuitState = {
  state: CircuitStateName;
  failureCount: number;
  openedUntil: number | null;
  lastFailureCode: string | null;
};

export type CircuitOptions = {
  failureThreshold: number;
  openMs: number;
};

const defaultState: CircuitState = {
  state: "closed",
  failureCount: 0,
  openedUntil: null,
  lastFailureCode: null,
};

export async function getCircuitState(store: ReliabilityStore, key: string): Promise<CircuitState> {
  const raw = await store.get(key);
  if (!raw) {
    return defaultState;
  }

  try {
    const parsed = JSON.parse(raw) as CircuitState;
    if (parsed.state === "open" && parsed.openedUntil !== null && parsed.openedUntil <= Date.now()) {
      return {
        ...parsed,
        state: "half_open",
      };
    }
    return {
      state: parsed.state,
      failureCount: Number(parsed.failureCount) || 0,
      openedUntil: typeof parsed.openedUntil === "number" ? parsed.openedUntil : null,
      lastFailureCode: typeof parsed.lastFailureCode === "string" ? parsed.lastFailureCode : null,
    };
  } catch {
    return defaultState;
  }
}

export async function isCircuitCallAllowed(store: ReliabilityStore, key: string): Promise<boolean> {
  const state = await getCircuitState(store, key);
  return state.state !== "open";
}

export async function recordCircuitSuccess(store: ReliabilityStore, key: string, openMs: number): Promise<CircuitState> {
  const state: CircuitState = { ...defaultState };
  await store.set(key, JSON.stringify(state), Math.max(openMs * 2, 60_000));
  return state;
}

export async function recordCircuitFailure(
  store: ReliabilityStore,
  key: string,
  options: CircuitOptions,
  failureCode = "provider_unavailable",
): Promise<CircuitState> {
  const current = await getCircuitState(store, key);
  const failureCount = current.failureCount + 1;
  const shouldOpen = failureCount >= options.failureThreshold;
  const state: CircuitState = {
    state: shouldOpen ? "open" : "closed",
    failureCount,
    openedUntil: shouldOpen ? Date.now() + options.openMs : null,
    lastFailureCode: failureCode,
  };

  await store.set(key, JSON.stringify(state), Math.max(options.openMs * 2, 60_000));
  return state;
}

export function summarizeCircuitState(state: CircuitState): CircuitStateName {
  return state.state;
}
