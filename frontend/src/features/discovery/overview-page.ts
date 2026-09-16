import { escapeHtml } from "../../shared/formatters";
import type { RenderedWorkspacePage, WorkspaceSnapshot } from "./view-types";

function activityTypeLabel(profile: { activityTypes?: string[] }): string {
  const labels: Record<string, string> = {
    // Keep the internal ``official`` mode for execution, but show the
    // user-facing category as interaction.
    official: "互动",
    unofficial: "非官方",
    reservation: "预约",
  };
  return (profile.activityTypes ?? [])
    .map((value) => labels[value] ?? value)
    .join(" / ") || "按兼容规则";
}

function sourcePages(profile: { mid: string; uploadUrl: string; sourcePages?: Array<{ mid: string; uploadUrl: string }> }): Array<{ mid: string; uploadUrl: string }> {
  return profile.sourcePages?.length
    ? profile.sourcePages
    : [{ mid: profile.mid, uploadUrl: profile.uploadUrl }];
}

function renderSettings(snapshot: WorkspaceSnapshot): string {
  const settings = snapshot.settings ?? {
    deepseekConfigured: false,
    deepseekApiUrl: "https://api.deepseek.com/chat/completions",
    deepseekModel: "deepseek-v4-flash",
    mentionNames: ["你的抽奖工具人", "哔哩哔哩弹幕网", "哔哩哔哩足球赛事"],
    unofficialAutomationEnabled: true,
    unofficialAutomationDelayMinSec: 1,
    unofficialAutomationDelayMaxSec: 2,
  };
  const names = [0, 1, 2].map((index) => escapeHtml(settings.mentionNames[index] ?? ""));
  const configuredLabel = settings.deepseekConfigured ? "已配置（Key 不回显）" : "未配置";
  return `<section class="panel settings-panel">
    <div class="panel-heading"><div><span class="kicker">RUNTIME SETTINGS</span><h2>DeepSeek 与提及好友配置</h2><p class="section-description">非官方自动化的评论生成和最多 3 个固定 @账号均来自这里。</p></div><span class="state state-${settings.deepseekConfigured ? "liked" : "unknown"}">${configuredLabel}</span></div>
    <form data-settings-form>
      <div class="settings-grid">
        <label>DeepSeek API Key<input type="password" name="deepseekApiKey" autocomplete="new-password" placeholder="输入 sk-…；留空表示保持当前 Key"></label>
        <label>API 地址<input type="url" name="deepseekApiUrl" value="${escapeHtml(settings.deepseekApiUrl)}"></label>
        <label>模型<input name="deepseekModel" value="${escapeHtml(settings.deepseekModel)}"></label>
        <label>固定 @账号 1<input name="mentionName1" value="${names[0]}" placeholder="你的抽奖工具人"></label>
        <label>固定 @账号 2<input name="mentionName2" value="${names[1]}" placeholder="哔哩哔哩弹幕网"></label>
        <label>固定 @账号 3<input name="mentionName3" value="${names[2]}" placeholder="哔哩哔哩足球赛事"></label>
      </div>
      <div class="settings-footer"><div><label class="checkbox-line"><input type="checkbox" name="clearDeepseekApiKey"> 清除当前 Key</label><p class="settings-meta">动作等待：${settings.unofficialAutomationDelayMinSec}–${settings.unofficialAutomationDelayMaxSec} 秒 · 自动化状态：${settings.unofficialAutomationEnabled ? "已启用" : "已关闭"}</p></div><button type="submit">保存设置</button></div>
    </form>
  </section>`;
}

function renderSource(snapshot: WorkspaceSnapshot): string {
  const profile = snapshot.profile;
  const pages = profile ? sourcePages(profile) : [];
  const profilePicker = snapshot.profiles.length > 1
    ? `<label class="source-picker">选择来源<select data-source-profile>${snapshot.profiles.map((item) => `<option value="${item.id}"${item.id === profile?.id ? " selected" : ""}>${escapeHtml(item.displayName || item.sourceKey)} · ${item.sourcePages?.length && item.sourcePages.length > 1 ? "双来源" : escapeHtml(item.mid)}</option>`).join("")}</select></label>`
    : "";
  return `<section class="panel source-panel">
    <div class="panel-heading"><div><span class="kicker">SOURCE PROFILE</span><h2>当前来源</h2></div><div class="actions">${profilePicker}<button class="secondary" data-login ${profile ? "" : "disabled"}>打开登录页</button></div></div>
    ${profile ? `<dl class="source-meta">
      <div><dt>UP</dt><dd>${escapeHtml(profile.displayName || profile.sourceKey)}</dd></div>
      <div><dt>UP / MID</dt><dd>${escapeHtml(pages.map((page) => page.mid).join("、"))}</dd></div>
      <div><dt>适配器</dt><dd>${escapeHtml(profile.adapterKey)}</dd></div>
      <div><dt>来源主页</dt><dd>${pages.map((page, index) => `<a href="${escapeHtml(page.uploadUrl)}" target="_blank" rel="noreferrer">主页${index + 1}</a>`).join(" / ")}</dd></div>
      <div><dt>每类最新</dt><dd>${profile.latestPerFamily} 篇</dd></div>
      <div><dt>允许动态类型</dt><dd>${escapeHtml(activityTypeLabel(profile))}</dd></div>
    </dl>` : `<p class="empty-copy">没有启用的来源配置。</p>`}
  </section>`;
}

function renderReadiness(snapshot: WorkspaceSnapshot): string {
  const health = snapshot.health;
  const service = health ? (health.ok ? "正常" : "不可用") : "检查中";
  const browser = health ? (health.browserReady ? "已就绪" : "需要时启动") : "检查中";
  const tone = health?.ok ? "liked" : health ? "unknown" : "unliked";
  return `<section class="panel readiness-panel">
    <div class="panel-heading"><div><span class="kicker">READINESS</span><h2>会话准备状态</h2></div></div>
    <div class="readiness-list"><div><span>接口健康</span><strong class="state state-${tone}">${service}</strong></div><div><span>浏览器会话</span><strong class="state state-${health?.browserReady ? "liked" : "unliked"}">${browser}</strong></div></div>
    <p class="status-card" data-status>${escapeHtml(snapshot.statusMessage ?? "等待读取当前会话状态。")}</p>
  </section>`;
}

export function renderOverviewPage(snapshot: WorkspaceSnapshot): RenderedWorkspacePage {
  return {
    eyebrow: "WORKSPACE / OVERVIEW",
    title: "概览与准备",
    subtitle: "确认本地服务、B站浏览器会话与运行配置，再进入来源发现。",
    content: `<section class="notice"><strong>安全边界：</strong>未知、风控、控件不唯一或终态无法确认时，停止当前条目并记录问题网址；存在开放问题的来源合集本轮不点赞。</section>
      <div class="overview-grid">${renderSource(snapshot)}${renderReadiness(snapshot)}</div>
      ${renderSettings(snapshot)}`,
  };
}
