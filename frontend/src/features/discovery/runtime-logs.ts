import { escapeHtml } from "../../shared/formatters";
import type { RenderedWorkspacePage, RuntimeLogEntry, WorkspaceSnapshot } from "./view-types";

const levelLabels: Record<RuntimeLogEntry["level"], string> = {
  info: "信息",
  warn: "暂停",
  error: "错误",
};

export function formatRuntimeLogs(entries: RuntimeLogEntry[]): string {
  return entries
    .map((entry) => {
      const detail = entry.detail ? `\n${entry.detail}` : "";
      return `${entry.at} [${levelLabels[entry.level]}] ${entry.summary}${detail}`;
    })
    .join("\n");
}

function renderLogEntry(entry: RuntimeLogEntry): string {
  const detail = entry.detail
    ? `<pre class="runtime-log-detail">${escapeHtml(entry.detail)}</pre>`
    : "";
  return `<li data-log-id="${entry.id}" class="runtime-log-entry runtime-log-${entry.level}">
    <div class="runtime-log-meta"><time>${escapeHtml(entry.at)}</time><span class="state state-${entry.level === "info" ? "liked" : entry.level === "warn" ? "unliked" : "unknown"}">${levelLabels[entry.level]}</span>${entry.event ? `<code>${escapeHtml(entry.event)}</code>` : ""}</div>
    <p>${escapeHtml(entry.summary)}</p>${detail}
  </li>`;
}

function logDescription(entries: RuntimeLogEntry[]): string {
  return `${entries.length} 条记录${entries.some(entry => Boolean(entry.detail)) ? " · 已包含中断详细日志" : " · 当前为简洁模式"}`;
}

const emptyLogRow = `<li class="runtime-log-empty">尚未收到运行事件。开始发现或执行计划后，日志会从实时事件流写入这里。</li>`;

export function updateLogsPage(root: HTMLElement, snapshot: WorkspaceSnapshot): boolean {
  const list = root.querySelector<HTMLOListElement>(".runtime-log-list");
  const description = root.querySelector<HTMLElement>("[data-log-description]");
  if (!list || !description) return false;
  const entries = snapshot.logs;
  const retained = new Set(entries.map(entry => String(entry.id)));
  for (const row of Array.from(list.children)) {
    if (!retained.has(row.getAttribute("data-log-id") ?? "")) row.remove();
  }
  const lastId = Number(list.lastElementChild?.getAttribute("data-log-id") ?? 0);
  const added = entries.filter(entry => entry.id > lastId);
  if (added.length) list.insertAdjacentHTML("beforeend", added.map(renderLogEntry).join(""));
  if (!entries.length) list.innerHTML = emptyLogRow;
  description.textContent = logDescription(entries);
  for (const selector of ["[data-copy-logs]", "[data-clear-logs]"]) {
    const button = root.querySelector<HTMLButtonElement>(selector);
    if (button) button.disabled = entries.length === 0;
  }
  const status = root.querySelector<HTMLElement>("[data-status]");
  if (status) status.textContent = snapshot.statusMessage ?? "实时事件流已连接";
  return true;
}

export function renderLogsPage(snapshot: WorkspaceSnapshot): RenderedWorkspacePage {
  const entries = snapshot.logs;
  const rows = entries.length === 0
    ? emptyLogRow
    : entries.map(renderLogEntry).join("");
  return {
    eyebrow: "WORKSPACE / LOGS",
    title: "运行日志",
    subtitle: "正常运行仅保留短摘要；问题中断时显示问题网址、错误码和安全详情，便于定位而不暴露敏感配置。",
    content: `<section class="panel runtime-logs-panel">
      <div class="panel-heading"><div><span class="kicker">RUNTIME LOG STREAM</span><h2>本地运行事件</h2><p class="section-description" data-log-description>${logDescription(entries)}</p><p class="status-line runtime-log-status" data-status>${escapeHtml(snapshot.statusMessage ?? "实时事件流已连接")}</p></div><div class="actions"><button type="button" class="secondary" data-copy-logs ${entries.length === 0 ? "disabled" : ""}>复制日志</button><button type="button" class="secondary" data-clear-logs ${entries.length === 0 ? "disabled" : ""}>清空</button></div></div>
      <div class="runtime-log-notice"><strong>日志策略：</strong>正常事件只记录时间、级别和一句摘要；waiting_user、failed、interrupted 或问题网址会附加完整安全上下文。</div>
      <ol class="runtime-log-list">${rows}</ol>
    </section>`,
  };
}
