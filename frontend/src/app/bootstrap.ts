import { initializeSession } from "../shared/api";
import { connectDesktopLifecycle } from "../shared/desktop-lifecycle";
import { connectEvents } from "../shared/events";
import { DiscoveryView } from "../features/discovery/view";

export async function bootstrap(root: HTMLElement): Promise<void> {
  root.innerHTML = `<div class="loading">正在连接本机服务…</div>`;
  try {
    const csrfToken = await initializeSession();
    connectDesktopLifecycle(csrfToken);
    const view = new DiscoveryView(root);
    await view.load();
    const events = connectEvents((name, data) => view.handleEvent(name, data));
    events.addEventListener("open", () => void view.reconnect().catch(() => undefined));
    window.addEventListener("pagehide", () => {
      view.dispose();
      events.close();
    });
    window.addEventListener("pageshow", (event) => {
      if (event.persisted) window.location.reload();
    });
  } catch (error) {
    root.innerHTML = `<section class="panel error-panel"><h1>无法连接本机服务</h1><p>${String(error)}</p><p>请先运行 <code>python -m backend.launcher</code>。</p></section>`;
  }
}
