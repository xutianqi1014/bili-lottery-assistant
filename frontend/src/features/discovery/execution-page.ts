import type { RunItem, RunPlan } from "../../shared/api";
import { escapeHtml } from "../../shared/formatters";
import type { RenderedWorkspacePage, WorkspaceSnapshot } from "./view-types";

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function numberValue(record: Record<string, unknown>, key: string): number {
  const value = record[key];
  return typeof value === "number" ? value : 0;
}

function renderSourceClosure(stats: Record<string, unknown>): string {
  const raw = asRecord(stats.sourceClosure);
  if (!raw) return "";
  const items = Array.isArray(raw.items)
    ? raw.items.map((value) => asRecord(value)).filter((value): value is Record<string, unknown> => value !== null)
    : [];
  if (items.length === 0) return "";
  const statusLabel: Record<string, string> = {
    ready_to_mark: "可自动收尾（等待运行结束）",
    already_liked: "已点赞（无需处理）",
    blocked_not_marked: "阻塞（本轮不点赞）",
  };
  const rows = items.map((item) => {
    const id = typeof item.sourceArticleId === "number" ? String(item.sourceArticleId) : "";
    const title = typeof item.title === "string" ? item.title : id;
    const url = typeof item.url === "string" ? item.url : "";
    const status = typeof item.status === "string" ? item.status : "unknown";
    const reasons = Array.isArray(item.reasonCodes) ? item.reasonCodes.filter((value): value is string => typeof value === "string").join(", ") : "";
    const activityCount = typeof item.activityCount === "number" ? item.activityCount : 0;
    const terminalCount = typeof item.terminalActivityCount === "number" ? item.terminalActivityCount : 0;
    const openProblems = typeof item.openProblemCount === "number" ? item.openProblemCount : 0;
    const source = url ? `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${escapeHtml(title)}</a>` : escapeHtml(title);
    return `<tr><td>${source}<small>${escapeHtml(id)}</small></td><td>${escapeHtml(statusLabel[status] ?? status)}</td><td>${terminalCount}/${activityCount}</td><td>${openProblems}</td><td>${escapeHtml(reasons || "—")}</td></tr>`;
  }).join("");
  return `<section class="panel source-closure"><div class="subheading"><div><span class="kicker">SOURCE ARTICLE CLOSURE</span><h3>来源专栏收尾判定</h3></div><div class="closure-counts"><span class="state state-liked">可收尾 ${numberValue(raw, "readyToMarkCount")}</span><span class="state">已点赞 ${numberValue(raw, "alreadyLikedCount")}</span><span class="state state-${numberValue(raw, "blockedCount") > 0 ? "unknown" : "liked"}">阻塞 ${numberValue(raw, "blockedCount")}</span></div></div><p class="status-line">运行结束时只自动点赞零问题且全部相关动态已终态的来源；有问题的来源保持未点赞。</p><div class="table-wrap"><table><thead><tr><th>来源专栏</th><th>判定</th><th>终态活动</th><th>未解决问题</th><th>原因码</th></tr></thead><tbody>${rows}</tbody></table></div></section>`;
}

function renderPlanItem(item: RunItem): string {
  return `<tr><td>${item.sequence}</td><td><a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">${escapeHtml(item.title || item.dynamicId)}</a><small>${escapeHtml(item.dynamicId)}</small></td><td><span class="family-label">${escapeHtml(item.family === "official" ? "官方" : "非官方")}</span></td><td>${escapeHtml(item.platformStatus === "unchecked" ? "未检查" : item.platformStatus)}</td><td><span class="state state-${["completed", "skipped"].includes(item.state) ? "liked" : item.state === "planned" ? "unliked" : "unknown"}">${escapeHtml(item.state)}</span></td></tr>`;
}

function renderAction(plan: RunPlan): string {
  const blocked = Number(plan.stats.blockedActivities ?? 0);
  if (plan.state === "awaiting_confirmation" && blocked === 0) {
    return `<button data-confirm-start-run>确认并开始执行</button>`;
  }
  const hasOfficial = plan.items.some((item) => item.family === "official");
  const hasUnofficial = plan.items.some((item) => item.family !== "official");
  if (plan.state === "confirmed_waiting_user") {
    const label = plan.officialAutomationEnabled && hasOfficial && !hasUnofficial ? "开始官方自动执行" : "开始执行计划";
    return `<button data-start-run>${label}</button>`;
  }
  // A blocked/interrupted item may have been completed manually in Bilibili.
  // The explicit restart resets only that current item and re-inspects it;
  // terminal items remain untouched.  This action is available for both
  // official and non-official automation runs.
  if ((plan.state === "waiting_user" || plan.state === "interrupted") && (blocked > 0 || plan.state === "interrupted")) {
    return `<button data-restart-run title="请先在 B 站完成当前错误动态；重新开始只重新检查当前动态">重新开始</button>`;
  }
  if (plan.state === "waiting_user" && !plan.officialAutomationEnabled) {
    return `<button data-resume-run>继续下一条／重新检查当前条目</button>`;
  }
  return `<span class="state state-${["completed"].includes(plan.state) ? "liked" : "unknown"}">${escapeHtml(plan.state)}</span>`;
}

function executionPolicy(plan: RunPlan): string {
  const hasOfficial = plan.items.some((item) => item.family === "official");
  const hasUnofficial = plan.items.some((item) => item.family !== "official");
  const deepseekPolicy = plan.deepseekConfigured ? "DeepSeek 已配置" : "DeepSeek 未配置（非官方条目会在写入前安全阻塞）";
  if (plan.unofficialAutomationEnabled && hasUnofficial) {
    const min = plan.unofficialAutomationDelayMinSec ?? 1;
    const max = plan.unofficialAutomationDelayMaxSec ?? 2;
    return `非官方动态将自动执行评论、勾选“同时转发到我的动态”、转发、点赞和关注；先检查动态点赞，已点赞直接跳过；评论由 DeepSeek 生成并补全要求的话题及固定 @好友（${deepseekPolicy}）。每步等待 ${min}–${max} 秒；评论发布点击返回 COMMENT_SUBMIT_ACCEPTED，不复检评论列表，转发、点赞和关注继续确认终态，未知结果停止且不自动重试。`;
  }
  if (plan.officialAutomationEnabled && hasOfficial) return "官方条目会按计划顺序自动处理；每条得到明确终态后才进入下一条。";
  return "非官方自动化未启用；每次只打开当前一条，生成动作策略后暂停且不写入。";
}

function renderPlan(plan: RunPlan): string {
  const stats = plan.stats;
  const blocked = Number(stats.blockedActivities ?? 0);
  const items = plan.items.map((item) => renderPlanItem(item)).join("");
  const planSection = `<section class="panel run-plan"><div class="plan-top"><div><span class="kicker">RUN PLAN #${plan.id}</span><h2>本次运行计划</h2><p class="section-description">${escapeHtml(plan.statusDetail ?? "等待读取计划状态。")}</p></div><div class="current-action"><span>当前唯一操作</span>${renderAction(plan)}</div></div>
    <div class="metric-grid plan-metrics"><div><span>全部动态</span><strong>${stats.totalActivities ?? 0}</strong></div><div><span>计划处理</span><strong>${stats.plannedActivities ?? 0}</strong></div><div><span>跳过</span><strong>${stats.skippedActivities ?? 0}</strong></div><div><span>阻塞</span><strong>${blocked}</strong></div></div>
    <p class="status-line">${executionPolicy(plan)}</p>
    <div class="table-wrap"><table class="run-plan-table"><colgroup><col class="run-plan-col-sequence"><col class="run-plan-col-dynamic"><col class="run-plan-col-family"><col class="run-plan-col-page-state"><col class="run-plan-col-run-state"></colgroup><thead><tr><th>序号</th><th>动态</th><th>流程</th><th>页面状态</th><th>运行状态</th></tr></thead><tbody>${items || `<tr><td colspan="5">计划为空。</td></tr>`}</tbody></table></div>
  </section>`;
  return `${planSection}${renderSourceClosure(stats)}`;
}

export function renderExecutionPage(snapshot: WorkspaceSnapshot): RenderedWorkspacePage {
  return {
    eyebrow: "WORKSPACE / EXECUTION",
    title: "执行与结果",
    subtitle: "审查不可变计划，按条件显示唯一操作，并追踪每个动作的明确终态。",
    content: snapshot.plan ? renderPlan(snapshot.plan) : `<section class="panel empty-state"><span class="kicker">RUN PLAN</span><h2>尚未生成执行计划</h2><p>请先在“来源发现”页执行只读发现；只有存在待处理动态时才会自动生成计划。</p></section>`,
  };
}
