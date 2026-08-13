const DESKTOP_SUBPROTOCOL = "bili-lottery-desktop";
const RECONNECT_DELAY_MS = 500;

/**
 * Keep one process-lifetime socket open while this HTML page exists.
 *
 * The backend waits three seconds after the final socket disconnects before it
 * exits. That makes a refresh safe: the replacement page reconnects during the
 * grace period, while a genuinely closed tab leaves no client behind.
 */
export function connectDesktopLifecycle(csrfToken: string): void {
  let socket: WebSocket | null = null;
  let reconnectTimer: number | null = null;
  let suspended = false;

  const clearReconnect = (): void => {
    if (reconnectTimer !== null) {
      window.clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };

  const connect = (): void => {
    if (
      suspended
      || socket?.readyState === WebSocket.OPEN
      || socket?.readyState === WebSocket.CONNECTING
    ) {
      return;
    }
    clearReconnect();
    const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
    socket = new WebSocket(
      `${scheme}//${window.location.host}/api/desktop/lifecycle`,
      [DESKTOP_SUBPROTOCOL, csrfToken],
    );
    socket.addEventListener("close", () => {
      socket = null;
      if (!suspended) {
        reconnectTimer = window.setTimeout(connect, RECONNECT_DELAY_MS);
      }
    });
  };

  window.addEventListener("pagehide", () => {
    suspended = true;
    clearReconnect();
    socket?.close(1000, "page closed");
    socket = null;
  });
  window.addEventListener("pageshow", () => {
    if (!suspended) return;
    suspended = false;
    connect();
  });
  connect();
}
