const CURRENT_DISCOVERY_KEY = "bili-lottery-assistant.current-discovery-id";

/** Persist only the current numeric workspace pointer for this browser tab. */
export function rememberDiscoveryId(discoveryId: number): void {
  if (!Number.isInteger(discoveryId) || discoveryId < 1) return;
  try {
    window.sessionStorage.setItem(CURRENT_DISCOVERY_KEY, String(discoveryId));
  } catch {
    // The UI still works when storage is disabled; only F5 restoration is lost.
  }
}

export function recallDiscoveryId(): number | null {
  try {
    const value = Number(window.sessionStorage.getItem(CURRENT_DISCOVERY_KEY));
    return Number.isInteger(value) && value > 0 ? value : null;
  } catch {
    return null;
  }
}

export function forgetDiscoveryId(): void {
  try {
    window.sessionStorage.removeItem(CURRENT_DISCOVERY_KEY);
  } catch {
    // Storage may be disabled by the browser.
  }
}
