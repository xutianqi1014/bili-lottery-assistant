import type { ActivityPreview, Discovery, Problem } from "../../shared/api";
import { escapeHtml } from "../../shared/formatters";
import type { RenderedWorkspacePage, WorkspaceSnapshot } from "./view-types";

function stateLabel(state: string): string {
  return { liked: "已点赞/已处理", unliked: "未点赞/待处理", unknown: "未知/人工复核" }[state] ?? state;
}

function renderAutomaticPlanStatus(
  discovery: Discovery,
  candidateCount: number,
  hasPlan: boolean,
): string {
  const state = String(discovery.stats.automaticPlanState ?? "");
  if (state === "failed") {
    const code = String(discovery.stats.automaticPlanErrorCode ?? "AUTOMATIC_PLAN_FAILED");
    return `<p class="error">自动生成执行计划失败：${escapeHtml(code)}。未执行任何动态。</p>`;
  }
  if (state === "skipped_no_candidates" || (discovery.state === "preview_ready" && candidateCount === 0)) {
    return `<p class="status-line">只读发现已完成；没有待处理动态，本轮不生成执行计划。</p>`;
  }
  if (hasPlan || state === "created") {
    return `<p class="status-line">只读发现已完成，执行计划已自动生成；请在“执行与结果”页审查计划后再确认。</p>`;
  }
  if (discovery.state === "preview_ready" && candidateCount > 0) {
    return `<p class="status-line">只读发现已完成，正在自动生成执行计划……</p>`;
  }
  if (discovery.state === "running") {
    return `<p class="status-line">发现完成后，如有待处理动态将自动生成执行计划。</p>`;
  }
  return "";
}

function renderProblems(problems: Problem[]): string {
  if (problems.length === 0) return `<p class="problem-empty">本轮暂未记录问题网址。</p>`;
  const rows = problems.map((problem) => `<div class="problem-row"><a href="${escapeHtml(problem.problemUrl)}" target="_blank" rel="noreferrer">${escapeHtml(problem.problemUrl)}</a><span>${escapeHtml(problem.problemCode)} · ${escapeHtml(problem.safeDetail)}</span></div>`).join("");
  return `<div class="problem-box"><div class="problem-heading"><div><span class="kicker">PROBLEM URLS</span><strong>问题网址（本轮不点赞）</strong></div><span class="state state-unknown">${problems.length}</span></div>${rows}</div>`;
}

function renderActivityRow(row: ActivityPreview): string {
  const sourceNames = row.origins.map((origin) => `${origin.family} · ${origin.sourcePosition}`).join("；");
  const expectedFlow = row.origins.some((origin) => origin.family === "normal") ? "非官方" : "官方";
  return `<tr><td><a href="${escapeHtml(row.url)}" target="_blank" rel="noreferrer">${escapeHtml(row.title || row.dynamicId)}</a><small>${escapeHtml(row.dynamicId)}</small></td><td>${escapeHtml(sourceNames || "未知来源")}</td><td><span class="state state-liked">${expectedFlow}</span></td><td>未检查</td><td>执行时读取页面分类、参与状态、点赞状态和评论要求</td></tr>`;
}

function renderDiscoverySnapshot(snapshot: WorkspaceSnapshot, discovery: Discovery): string {
  const activityRows = discovery.activities ?? [];
  const readlists = discovery.selectedReadlists.map((item) => `<span class="chip">${escapeHtml(String(item.title ?? ""))} · ${escapeHtml(String(item.url ?? ""))}</span>`).join("");
  const rows = discovery.selections.map((row) => `<tr><td>${escapeHtml(row.family)}</td><td>${row.rank}</td><td>${row.position}</td><td><a href="${escapeHtml(row.url)}" target="_blank" rel="noreferrer">${escapeHtml(row.title || row.articleId)}</a></td><td><span class="state state-${row.likeState}">${stateLabel(row.likeState)}</span></td><td>${escapeHtml(row.reason)}</td><td>${escapeHtml(row.parseStatus || "未解析")}</td></tr>`).join("");
  const activities = activityRows.map((row) => renderActivityRow(row)).join("");
  return `<section class="panel discovery-snapshot">
    <div class="panel-heading"><div><span class="kicker">DISCOVERY SNAPSHOT #${discovery.id}</span><h2>不可变发现预览</h2><p class="section-description">状态：${escapeHtml(discovery.state)}</p></div><button class="secondary" data-refresh>刷新</button></div>
    <div class="metric-grid discovery-metrics"><div><span>已检查专栏</span><strong>${discovery.stats.selectedArticles ?? 0}</strong><small>selectedArticles</small></div><div><span>未知标记</span><strong>${discovery.stats.unknownMarkers ?? 0}</strong><small>unknownMarkers</small></div><div><span>动态去重后</span><strong>${discovery.stats.activityRefsUnique ?? 0}</strong><small>activityRefsUnique</small></div><div><span>自动计划</span><strong class="metric-text">${escapeHtml(String(discovery.stats.automaticPlanState ?? "—"))}</strong><small>automaticPlanState</small></div></div>
    <div class="readlists">${readlists || `<span class="chip">等待文集</span>`}</div>
    ${renderAutomaticPlanStatus(discovery, activityRows.length, Boolean(snapshot.plan))}
    ${discovery.errorDetail ? `<p class="error">${escapeHtml(discovery.errorDetail)}</p>` : ""}
    <div class="section-divider"><div><span class="kicker">SOURCE ARTICLE DECISIONS</span><h3>来源专栏判定</h3></div><div class="table-wrap"><table><thead><tr><th>类别</th><th>最新排名</th><th>原序号</th><th>来源专栏</th><th>点赞判定</th><th>决策</th><th>解析</th></tr></thead><tbody>${rows || `<tr><td colspan="7">尚未得到来源专栏。</td></tr>`}</tbody></table></div></div>
    <div class="section-divider"><div class="subheading"><div><span class="kicker">ACTIVITY QUEUE · CANDIDATES</span><h3>动态候选与全局去重</h3></div><span class="state state-liked">候选由发现响应提供</span></div><p class="status-line">共 ${activityRows.length} 条唯一动态；重复动态只保留一个活动记录，但保留全部来源关系。候选页面不打开动态，页面分类、参与状态和要求在正式执行当前条目时读取。</p><div class="table-wrap"><table><thead><tr><th>动态</th><th>来源</th><th>计划流程</th><th>页面状态</th><th>执行时读取</th></tr></thead><tbody>${activities || `<tr><td colspan="5">没有待处理动态，或来源专栏仍需人工复核。</td></tr>`}</tbody></table></div></div>
    ${renderProblems(snapshot.problems)}
  </section>`;
}

function renderSourceProfile(snapshot: WorkspaceSnapshot): string {
  const profile = snapshot.profile;
  return `<section class="panel source-panel"><div class="panel-heading"><div><span class="kicker">SOURCE PROFILE</span><h2>当前来源</h2></div><p class="status-badge" data-status>${escapeHtml(snapshot.statusMessage ?? (snapshot.discovery ? `发现状态：${snapshot.discovery.state}` : "尚未执行发现。"))}</p></div><div class="actions source-actions"><button class="secondary" data-login ${profile ? "" : "disabled"}>打开登录页</button><button data-discover ${profile ? "" : "disabled"}>开始只读发现</button></div>${profile ? `<dl class="source-meta"><div><dt>UP / MID</dt><dd>${escapeHtml(profile.mid)}</dd></div><div><dt>适配器</dt><dd>${escapeHtml(profile.adapterKey)}</dd></div><div><dt>来源主页</dt><dd><a href="${escapeHtml(profile.uploadUrl)}" target="_blank" rel="noreferrer">打开 B 站主页</a></dd></div><div><dt>每类最新</dt><dd>${profile.latestPerFamily} 篇</dd></div></dl>` : `<p class="empty-copy">没有启用的来源配置。</p>`}</section>`;
}

export function renderDiscoveryPage(snapshot: WorkspaceSnapshot): RenderedWorkspacePage {
  return {
    eyebrow: "WORKSPACE / DISCOVERY",
    title: "来源发现",
    subtitle: "读取配置 UP 的最新图文与专栏，筛出两个来源家族并完成全局去重。",
    content: `${renderSourceProfile(snapshot)}${snapshot.discovery ? renderDiscoverySnapshot(snapshot, snapshot.discovery) : `<section class="panel empty-state"><span class="kicker">DISCOVERY SNAPSHOT</span><h2>尚未执行只读发现</h2><p>确认登录状态后点击“开始只读发现”。发现阶段不会打开候选动态。</p></section>`}`,
  };
}

