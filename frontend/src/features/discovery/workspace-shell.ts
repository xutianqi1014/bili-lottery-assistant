import { escapeHtml } from "../../shared/formatters";
import type {
  RenderedWorkspacePage,
  WorkspacePage,
  WorkspaceSnapshot,
} from "./view-types";

const PAGE_LABELS: Record<WorkspacePage, string> = {
  overview: "概览与准备",
  discovery: "来源发现",
  execution: "执行与结果",
  logs: "运行日志",
};

const PAGE_NUMBERS: Record<WorkspacePage, string> = {
  overview: "01",
  discovery: "02",
  execution: "03",
  logs: "04",
};

function navItem(page: WorkspacePage, activePage: WorkspacePage): string {
  const active = page === activePage;
  return `<button type="button" class="workspace-nav-item${active ? " is-active" : ""}" data-view="${page}" ${active ? 'aria-current="page"' : ""}><span>${PAGE_NUMBERS[page]}</span>${PAGE_LABELS[page]}</button>`;
}

function stageTone(value: string): string {
  if (["preview_ready", "completed", "skipped", "已就绪", "已完成"].includes(value)) {
    return "is-complete";
  }
  if (["running", "awaiting_confirmation", "confirmed_waiting_user"].includes(value)) {
    return "is-current";
  }
  if (["waiting_user", "failed", "interrupted", "cancelled", "blocked_unknown", "blocked_failed"].includes(value)) {
    return "is-blocked";
  }
  return "";
}

function renderStage(
  number: string,
  title: string,
  value: string,
  code: string,
  focused: boolean,
): string {
  const tone = stageTone(value);
  return `<div class="workflow-stage ${tone}${focused ? " is-focused" : ""}"><p>${number} · ${focused ? "本页重点" : "实时状态"}</p><strong>${title}</strong><small>${escapeHtml(value)} · ${escapeHtml(code)}</small></div>`;
}

function sourceLikeState(snapshot: WorkspaceSnapshot): string {
  const raw = snapshot.plan?.stats.sourceLikeAutomation;
  if (raw && typeof raw === "object" && !Array.isArray(raw)) {
    const value = (raw as Record<string, unknown>).state;
    if (typeof value === "string" && value) return value;
  }
  const closure = snapshot.plan?.stats.sourceClosure;
  if (closure && typeof closure === "object" && !Array.isArray(closure)) return "等待自动收尾";
  return "未开始";
}

function executionState(snapshot: WorkspaceSnapshot): string {
  const state = snapshot.plan?.state;
  if (!state) return "未开始";
  if (state === "awaiting_confirmation") return "等待计划确认";
  if (state === "confirmed_waiting_user") return "等待启动";
  return state;
}

function renderWorkflowRail(snapshot: WorkspaceSnapshot, activePage: WorkspacePage): string {
  const readiness = snapshot.health?.browserReady
    ? "已就绪"
    : snapshot.health?.ok
      ? "服务正常"
      : "检查中";
  const discoveryState = snapshot.discovery?.state ?? "未开始";
  const confirmationState = snapshot.plan?.state ?? "未生成";
  const execution = executionState(snapshot);
  const closure = sourceLikeState(snapshot);
  return `<section class="workflow-rail" aria-label="运行阶段"><div class="workflow-rail-grid">
    ${renderStage("01", "准备", readiness, "api.health", activePage === "overview")}
    ${renderStage("02", "只读发现", discoveryState, "api.getDiscovery", activePage === "discovery")}
    ${renderStage("03", "确认并启动", confirmationState, "api.confirmRunPlan → api.startRun", activePage === "execution")}
    ${renderStage("04", "自动执行", execution, "api.startRun / resumeRun / restartRun", activePage === "execution")}
    ${renderStage("05", "来源收尾", closure, "sourceLikeAutomation", activePage === "execution")}
  </div></section>`;
}

function sidebarNote(page: WorkspacePage): string {
  if (page === "discovery") {
    return `<strong>READ-ONLY FIRST</strong><span>候选生成不打开动态页面；有待处理动态时才自动生成计划。</span>`;
  }
  if (page === "execution") {
    return `<strong>SERIAL &amp; TERMINAL</strong><span>逐条执行；未知终态立即停止并保留问题网址。</span>`;
  }
  if (page === "logs") {
    return `<strong>RUNTIME LOGS</strong><span>正常事件保持短摘要；中断、失败或需人工处理时展开安全详细日志。</span>`;
  }
  return `<strong>READ-ONLY FIRST</strong><span>发现阶段不打开候选动态；写操作必须经过计划确认。</span>`;
}

function healthLabel(snapshot: WorkspaceSnapshot): string {
  if (!snapshot.health) return "检查本机服务中…";
  if (!snapshot.health.ok) return "本机服务不可用";
  return snapshot.health.browserReady
    ? "服务正常 · 浏览器已就绪"
    : "服务正常 · 浏览器将在需要时启动";
}

export function updateWorkspaceStatus(root: HTMLElement, snapshot: WorkspaceSnapshot, page: WorkspacePage): void {
  const rail = root.querySelector<HTMLElement>(".workflow-rail");
  const markup = renderWorkflowRail(snapshot, page);
  if (rail && rail.outerHTML !== markup) rail.outerHTML = markup;
  const health = root.querySelector<HTMLElement>("[data-health]");
  if (health) health.textContent = healthLabel(snapshot);
}

export function renderWorkspaceShell(
  activePage: WorkspacePage,
  snapshot: WorkspaceSnapshot,
  page: RenderedWorkspacePage,
): string {
  return `<div class="workspace-shell">
    <aside class="workspace-sidebar">
      <div class="workspace-brand"><span class="workspace-brand-mark" aria-hidden="true"></span><div><strong>B站互动抽奖助手</strong><small>LOCAL CONSOLE</small></div></div>
      <nav class="workspace-nav" aria-label="主导航">
        ${navItem("overview", activePage)}
        ${navItem("discovery", activePage)}
        ${navItem("execution", activePage)}
        ${navItem("logs", activePage)}
      </nav>
      <div class="workspace-sidebar-note">${sidebarNote(activePage)}</div>
    </aside>
    <main class="workspace-main">
      <div class="workspace-content">
        <header class="page-header"><div><p class="eyebrow">${page.eyebrow}</p><h1>${page.title}</h1><p class="subtitle">${page.subtitle}</p></div><div class="health" data-health>${healthLabel(snapshot)}</div></header>
        ${renderWorkflowRail(snapshot, activePage)}
        ${page.content}
      </div>
    </main>
  </div>`;
}
