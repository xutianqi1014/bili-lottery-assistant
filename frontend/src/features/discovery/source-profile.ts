import { escapeHtml } from "../../shared/formatters";
import type { WorkspaceSnapshot } from "./view-types";

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

export function renderSourceProfile(snapshot: WorkspaceSnapshot, mode: "overview" | "discovery"): string {
  const profile = snapshot.profile;
  const pages = profile ? sourcePages(profile) : [];
  const profilePicker = snapshot.profiles.length > 1
    ? `<label class="source-picker">选择来源<select data-source-profile>${snapshot.profiles.map((item) => `<option value="${item.id}"${item.id === profile?.id ? " selected" : ""}>${escapeHtml(item.displayName || item.sourceKey)} · ${item.sourcePages?.length && item.sourcePages.length > 1 ? "双来源" : escapeHtml(item.mid)}</option>`).join("")}</select></label>`
    : "";
  const login = `<button class="secondary" data-login ${profile ? "" : "disabled"}>打开登录页</button>`;
  const headerActions = mode === "overview"
    ? `${profilePicker}${login}`
    : `<p class="status-badge" data-status>${escapeHtml(snapshot.statusMessage ?? (snapshot.discovery ? `发现状态：${snapshot.discovery.state}` : "尚未执行发现。"))}</p>${profilePicker}`;
  const discoveryActions = mode === "discovery"
    ? `<div class="actions source-actions">${login}<button data-discover ${profile ? "" : "disabled"}>开始只读发现</button></div>`
    : "";
  return `<section class="panel source-panel">
    <div class="panel-heading"><div><span class="kicker">SOURCE PROFILE</span><h2>当前来源</h2></div><div class="actions">${headerActions}</div></div>
    ${discoveryActions}
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
