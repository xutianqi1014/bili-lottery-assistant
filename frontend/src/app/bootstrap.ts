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
    connectEvents((name, data) => {
      if (
        name === "discovery.ready"
        || name === "discovery.failed"
        || name === "discovery.plan_skipped"
        || name === "discovery.plan_failed"
      ) {
        const id = (data as { discoveryId?: number }).discoveryId;
        if (id) void view.refresh(id);
      }
      if (name.startsWith("run.")) {
        const id = (data as { runId?: number }).runId;
        if (id) void view.refreshPlan(id);
      }
    });
  } catch (error) {
    root.innerHTML = `<section class="panel error-panel"><h1>无法连接本机服务</h1><p>${String(error)}</p><p>请先运行 <code>python -m backend.launcher</code>。</p></section>`;
  }
}
