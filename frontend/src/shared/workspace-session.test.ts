import { afterEach, describe, expect, it, vi } from "vitest";

import { forgetDiscoveryId, recallDiscoveryId, rememberDiscoveryId } from "./workspace-session";

afterEach(() => {
  vi.unstubAllGlobals();
});

function installStorage(): Map<string, string> {
  const values = new Map<string, string>();
  vi.stubGlobal("window", {
    sessionStorage: {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
    },
  });
  return values;
}

describe("workspace session", () => {
  it("restores the current discovery after a same-tab refresh", () => {
    installStorage();
    rememberDiscoveryId(27);
    expect(recallDiscoveryId()).toBe(27);
  });

  it("forgets an old workspace pointer", () => {
    installStorage();
    rememberDiscoveryId(27);
    forgetDiscoveryId();
    expect(recallDiscoveryId()).toBeNull();
  });
});
