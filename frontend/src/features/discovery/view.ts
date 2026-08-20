import {
  api,
  type Discovery,
  type Problem,
  type RunPlan,
  type RuntimeSettings,
  type SourceProfile,
} from "../../shared/api";
import { renderDiscoveryPage } from "./discovery-page";
import { renderExecutionPage } from "./execution-page";
import { renderOverviewPage } from "./overview-page";
import { formatRuntimeLogs, renderLogsPage } from "./runtime-logs";
import type { HealthStatus, RuntimeLogEntry, WorkspacePage, WorkspaceSnapshot } from "./view-types";
import { WORKSPACE_PAGES } from "./view-types";
import { renderWorkspaceShell } from "./workspace-shell";
import {
  forgetDiscoveryId,
  recallDiscoveryId,
  rememberDiscoveryId,
} from "../../shared/workspace-session";

export class DiscoveryView {
  private root: HTMLElement;
  private profiles: SourceProfile[] = [];
  private profile: SourceProfile | null = null;
  private discovery: Discovery | null = null;
  private problems: Problem[] = [];
  private plan: RunPlan | null = null;
  private settings: RuntimeSettings | null = null;
  private health: HealthStatus | null = null;
  private activePage: WorkspacePage;
  private statusMessage: string | null = null;
  private logs: RuntimeLogEntry[] = [];
  private nextLogId = 1;
  private runActionInFlight = false;

  constructor(root: HTMLElement) {
    this.root = root;
    this.activePage = this.pageFromHash();
  }

  async load(): Promise<void> {
    const [sources, settings, health] = await Promise.all([
      api.listSources(),
      api.getSettings(),
      api.health().catch(() => ({ ok: false, browserReady: false })),
    ]);
    this.profiles = sources.filter((item) => item.enabled);
    this.profile = this.profiles[0] ?? null;
    this.settings = settings;
    this.health = health;
    this.appendLog("info", "本地控制台已连接");
    const rememberedDiscoveryId = recallDiscoveryId();
    if (rememberedDiscoveryId !== null) {
      try {
        await this.refresh(rememberedDiscoveryId);
        return;
      } catch {
        forgetDiscoveryId();
        this.discovery = null;
        this.problems = [];
        this.plan = null;
      }
    }
    this.render();
  }

  async saveSettings(form: HTMLFormElement): Promise<void> {
    const formData = new FormData(form);
    const mentionNames = [1, 2, 3]
      .map((index) => String(formData.get(`mentionName${index}`) ?? "").trim())
      .filter(Boolean);
    const apiKey = String(formData.get("deepseekApiKey") ?? "").trim();
    const clearKey = formData.get("clearDeepseekApiKey") === "on";
    this.setMessage("正在保存运行设置…");
    this.appendLog("info", "正在保存运行设置");
    this.settings = await api.updateSettings({
      deepseekApiKey: apiKey || undefined,
      clearDeepseekApiKey: clearKey,
      deepseekApiUrl: String(formData.get("deepseekApiUrl") ?? "").trim() || undefined,
      deepseekModel: String(formData.get("deepseekModel") ?? "").trim() || undefined,
      mentionNames,
    });
    this.render();
    this.setMessage("运行设置已保存；DeepSeek Key 仅保存在当前本地服务进程内。");
    this.appendLog("info", "运行设置已保存");
  }

  async start(): Promise<void> {
    if (!this.profile) return;
    this.plan = null;
    this.setMessage("正在创建只读发现任务；发现候选后将自动生成执行计划……");
    this.appendLog("info", "开始只读发现");
    let result: { discoveryId: number };
    try {
      result = await api.startDiscovery(this.profile.id);
    } catch (error) {
      this.appendLog("error", "只读发现启动失败", { error: String(error) }, "discovery.start_failed");
      throw error;
    }
    rememberDiscoveryId(result.discoveryId);
    await this.refresh(result.discoveryId);
  }

  selectProfile(profileId: number): void {
    const selected = this.profiles.find((item) => item.id === profileId && item.enabled);
    if (!selected || selected.id === this.profile?.id) return;
    this.profile = selected;
    this.discovery = null;
    this.problems = [];
    this.plan = null;
    forgetDiscoveryId();
    this.setMessage(`已切换来源：${selected.displayName}；请重新开始只读发现。`);
    this.appendLog("info", `切换来源：${selected.displayName}`);
    this.render();
  }

  async refresh(id?: number): Promise<void> {
    const target = id ?? this.discovery?.id;
    if (!target) return;
    try {
      this.discovery = await api.getDiscovery(target);
    } catch (error) {
      this.appendLog("error", "读取发现状态失败", { discoveryId: target, error: String(error) }, "discovery.refresh_failed");
      throw error;
    }
    const discoveredProfile = this.profiles.find(
      (item) => item.id === this.discovery?.profileId,
    );
    if (discoveredProfile) this.profile = discoveredProfile;
    rememberDiscoveryId(target);
    const previousProblemIds = new Set(this.problems.map((problem) => problem.id));
    this.problems = await api.getProblems(target);
    for (const problem of this.problems) {
      if (!previousProblemIds.has(problem.id)) {
        this.appendLog("error", `问题中断：${problem.problemCode}`, {
          problemUrl: problem.problemUrl,
          pageType: problem.pageType,
          stage: problem.stage,
          problemCode: problem.problemCode,
          safeDetail: problem.safeDetail,
          occurrenceCount: problem.occurrenceCount,
        }, "problem.recorded");
      }
    }
    if (this.discovery.runPlanId && this.plan?.id !== this.discovery.runPlanId) {
      this.plan = await api.getRunPlan(this.discovery.runPlanId);
    }
    this.render();
    if (this.discovery.state === "running") {
      window.setTimeout(() => void this.refresh(target), 1200);
    }
  }

  async confirmAndStartRun(): Promise<void> {
    if (!this.plan || this.runActionInFlight) return;
    this.runActionInFlight = true;
    const trigger = this.root.querySelector<HTMLButtonElement>("[data-confirm-start-run]");
    if (trigger) trigger.disabled = true;
    const planId = this.plan.id;
    this.setMessage("正在确认计划并开始执行……");
    this.appendLog("info", `确认运行计划 #${planId} 并开始执行`);
    try {
      this.plan = await api.confirmRunPlan(planId);
      this.plan = await api.startRun(planId);
      this.render();
    } catch (error) {
      this.appendLog("error", "确认并启动运行失败", { planId, error: String(error) }, "run.start_failed");
      this.render();
      throw error;
    } finally {
      this.runActionInFlight = false;
    }
  }

  async startRun(): Promise<void> {
    if (!this.plan || this.runActionInFlight) return;
    this.runActionInFlight = true;
    const trigger = this.root.querySelector<HTMLButtonElement>("[data-start-run]");
    if (trigger) trigger.disabled = true;
    this.setMessage(this.plan.officialAutomationEnabled
      ? "正在排队；将按确认计划自动处理官方动态……"
      : "正在排队；只会逐条打开当前动态并读取页面状态……");
    this.appendLog("info", `开始执行运行计划 #${this.plan.id}`);
    try {
      this.plan = await api.startRun(this.plan.id);
      this.render();
    } catch (error) {
      this.appendLog("error", "开始执行失败", { error: String(error) }, "run.start_failed");
      this.render();
      throw error;
    } finally {
      this.runActionInFlight = false;
    }
  }

  async resumeRun(): Promise<void> {
    if (!this.plan) return;
    this.setMessage("正在继续当前只读条目……");
    this.appendLog("info", `继续运行计划 #${this.plan.id}`);
    this.plan = await api.resumeRun(this.plan.id);
    this.render();
  }

  async restartRun(): Promise<void> {
    if (!this.plan || this.runActionInFlight) return;
    this.runActionInFlight = true;
    const trigger = this.root.querySelector<HTMLButtonElement>("[data-restart-run]");
    if (trigger) trigger.disabled = true;
    this.setMessage("正在重新开始：将重新检查当前问题动态，已完成动态不会重复执行……");
    this.appendLog("info", `重新开始运行计划 #${this.plan.id}`);
    try {
      this.plan = await api.restartRun(this.plan.id);
      this.render();
    } catch (error) {
      this.appendLog("error", "重新开始运行失败", { error: String(error) }, "run.restart_failed");
      this.render();
      throw error;
    } finally {
      this.runActionInFlight = false;
    }
  }

  private jumpToCurrentDynamic(): void {
    const trigger = this.root.querySelector<HTMLButtonElement>("[data-jump-current-dynamic]");
    const targetId = trigger?.dataset.targetItem;
    if (!targetId) {
      this.setMessage("当前没有正在处理的动态");
      return;
    }
    const target = this.root.querySelector<HTMLElement>(`[data-run-item="${targetId}"]`);
    if (!target) {
      this.setMessage("当前动态尚未刷新到执行计划，请稍后重试");
      return;
    }
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    target.focus({ preventScroll: true });
    this.setMessage("已定位到当前处理动态");
  }

  async refreshPlan(id = this.plan?.id): Promise<void> {
    if (!id) return;
    try {
      this.plan = await api.getRunPlan(id);
    } catch (error) {
      this.appendLog("error", "读取运行计划失败", { runId: id, error: String(error) }, "run.refresh_failed");
      throw error;
    }
    this.render();
  }

  render(): void {
    const snapshot = this.snapshot();
    const page = this.activePage === "overview"
      ? renderOverviewPage(snapshot)
      : this.activePage === "discovery"
        ? renderDiscoveryPage(snapshot)
        : this.activePage === "execution"
          ? renderExecutionPage(snapshot)
          : renderLogsPage(snapshot);
    this.root.innerHTML = renderWorkspaceShell(this.activePage, snapshot, page);
    this.bindEvents();
  }

  private bindEvents(): void {
    this.root.querySelectorAll<HTMLButtonElement>("[data-view]").forEach((button) => {
      button.addEventListener("click", () => {
        const pageName = button.dataset.view;
        if (pageName && WORKSPACE_PAGES.includes(pageName as WorkspacePage)) {
          this.navigate(pageName as WorkspacePage);
        }
      });
    });
    this.root.querySelector<HTMLButtonElement>("[data-discover]")?.addEventListener(
      "click",
      () => void this.start(),
    );
    this.root.querySelector<HTMLSelectElement>("[data-source-profile]")?.addEventListener(
      "change",
      (event) => {
        const select = event.currentTarget;
        if (select instanceof HTMLSelectElement) {
          this.selectProfile(Number(select.value));
        }
      },
    );
    this.root.querySelector<HTMLFormElement>("[data-settings-form]")?.addEventListener(
      "submit",
      (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        if (form instanceof HTMLFormElement) {
          void this.saveSettings(form).catch((error) => {
          this.setMessage(`保存运行设置失败：${String(error)}`);
          this.appendLog("error", "保存运行设置失败", { error: String(error) }, "settings.save_failed");
          });
        }
      },
    );
    this.root.querySelector<HTMLButtonElement>("[data-refresh]")?.addEventListener(
      "click",
      () => void this.refresh(),
    );
    this.root.querySelector<HTMLButtonElement>("[data-confirm-start-run]")?.addEventListener(
      "click",
      () => void this.confirmAndStartRun().catch((error) => {
        this.setMessage(`确认并开始执行失败：${String(error)}`);
      }),
    );
    this.root.querySelector<HTMLButtonElement>("[data-start-run]")?.addEventListener(
      "click",
      () => void this.startRun().catch((error) => {
        this.setMessage(`开始执行失败：${String(error)}`);
      }),
    );
    this.root.querySelector<HTMLButtonElement>("[data-resume-run]")?.addEventListener(
      "click",
      () => void this.resumeRun().catch((error) => {
        this.setMessage(`继续执行失败：${String(error)}`);
        this.appendLog("error", "继续执行失败", { error: String(error) }, "run.resume_failed");
      }),
    );
    this.root.querySelector<HTMLButtonElement>("[data-restart-run]")?.addEventListener(
      "click",
      () => void this.restartRun().catch((error) => {
        this.setMessage(`重新开始失败：${String(error)}`);
      }),
    );
    this.root.querySelector<HTMLButtonElement>("[data-jump-current-dynamic]")?.addEventListener(
      "click",
      () => this.jumpToCurrentDynamic(),
    );
    this.root.querySelector<HTMLButtonElement>("[data-copy-logs]")?.addEventListener("click", () => void this.copyLogs());
    this.root.querySelector<HTMLButtonElement>("[data-clear-logs]")?.addEventListener("click", () => this.clearLogs());
    this.root.querySelector<HTMLButtonElement>("[data-login]")?.addEventListener(
      "click",
      (event) => {
        const button = event.currentTarget;
        if (!(button instanceof HTMLButtonElement) || button.disabled) return;
        button.disabled = true;
        this.setMessage("正在打开登录页；已有页面时将直接切换到该页面……");
        void api.openLogin()
          .then(async () => {
            this.health = await api.health().catch(() => this.health);
            this.render();
            this.setMessage("登录页已打开或已切换至前台；完成登录后再开始只读发现。");
          })
          .catch((error) => {
            this.setMessage(`打开登录页失败：${String(error)}`);
            this.appendLog("error", "打开登录页失败", { error: String(error) }, "login.open_failed");
          })
          .finally(() => {
            if (button.isConnected) button.disabled = false;
          });
      },
    );
  }

  private setMessage(message: string): void {
    this.statusMessage = message;
    const status = this.root.querySelector<HTMLElement>("[data-status]");
    if (status) status.textContent = message;
  }

  ingestEvent(name: string, data: unknown): void {
    const record = data && typeof data === "object" ? data as Record<string, unknown> : {};
    const state = String(record.state ?? "");
    const critical = /(?:failed|interrupted|waiting_user|blocked|problem|cancelled)/i.test(name)
      || ["failed", "interrupted", "waiting_user", "blocked_failed", "blocked_unknown"].includes(state);
    const detail = critical ? this.sanitizeLogValue(data) : undefined;
    const paused = /(?:waiting_user|blocked|cancelled)/i.test(name) || ["waiting_user", "blocked_failed", "blocked_unknown"].includes(state);
    this.appendLog(critical ? (paused ? "warn" : "error") : "info", this.eventSummary(name, data), detail, name);
  }

  private eventSummary(name: string, data: unknown): string {
    const record = data && typeof data === "object" ? data as Record<string, unknown> : {};
    const sequence = typeof record.sequence === "number" ? `第 ${record.sequence} 条` : "当前条目";
    const labels: Record<string, string> = {
      "job.started": "后台任务已开始",
      "job.finished": "后台任务已完成",
      "job.cancelled": "后台任务已取消",
      "discovery.progress": "只读发现进行中",
      "discovery.article_checked": "来源专栏已检查",
      "discovery.ready": "只读发现完成，候选已准备",
      "discovery.failed": "只读发现失败",
      "discovery.plan_skipped": "没有待处理动态，未生成执行计划",
      "discovery.plan_failed": "执行计划生成失败",
      "run.plan_created": "执行计划已生成",
      "run.confirmed": "执行计划已确认",
      "run.started": "执行计划已开始",
      "run.item_started": `${sequence}开始处理`,
      "run.item_updated": `${sequence}处理状态已更新`,
      "run.source_closure_started": "来源专栏收尾判定开始",
      "run.source_closure_updated": "来源专栏收尾判定已更新",
      "run.interrupted": "运行已中断",
      "run.waiting_user": "运行暂停，等待人工处理",
      "run.restarted": "已重新开始运行计划",
      "run.finished": "执行计划已完成",
      "run.failed": "执行计划失败",
    };
    return labels[name] ?? `${name} 已更新`;
  }

  private sanitizeLogValue(value: unknown): string {
    const redact = (current: unknown): unknown => {
      if (Array.isArray(current)) return current.map(redact);
      if (!current || typeof current !== "object") return current;
      return Object.fromEntries(Object.entries(current as Record<string, unknown>).map(([key, child]) => {
        if (/(key|token|secret|password|cookie|authorization)/i.test(key)) return [key, "[REDACTED]"];
        return [key, redact(child)];
      }));
    };
    try {
      return JSON.stringify(redact(value), null, 2).slice(0, 12000);
    } catch {
      return String(value);
    }
  }

  private appendLog(level: RuntimeLogEntry["level"], summary: string, detail?: unknown, event?: string): void {
    const entry: RuntimeLogEntry = {
      id: this.nextLogId++,
      at: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
      level,
      summary,
      detail: detail === undefined ? undefined : typeof detail === "string" ? detail : this.sanitizeLogValue(detail),
      event,
    };
    this.logs = [...this.logs, entry].slice(-500);
    if (this.activePage === "logs" && this.root.isConnected) this.render();
  }

  private async copyLogs(): Promise<void> {
    const text = formatRuntimeLogs(this.logs);
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const textarea = document.createElement("textarea");
        textarea.value = text;
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.select();
        const copied = document.execCommand("copy");
        textarea.remove();
        if (!copied) throw new Error("CLIPBOARD_UNAVAILABLE");
      }
      this.setMessage("运行日志已复制");
    } catch (error) {
      this.setMessage(`复制日志失败：${String(error)}`);
    }
  }

  private clearLogs(): void {
    if (!window.confirm("确定清空当前运行日志吗？")) return;
    this.logs = [];
    this.setMessage("运行日志已清空");
    this.render();
  }

  private snapshot(): WorkspaceSnapshot {
    return {
      profiles: this.profiles,
      profile: this.profile,
      discovery: this.discovery,
      problems: this.problems,
      plan: this.plan,
      settings: this.settings,
      health: this.health,
      statusMessage: this.statusMessage,
      logs: this.logs,
    };
  }

  private pageFromHash(): WorkspacePage {
    const hash = typeof window === "undefined" ? "" : window.location.hash.replace(/^#/, "");
    return WORKSPACE_PAGES.includes(hash as WorkspacePage)
      ? hash as WorkspacePage
      : "overview";
  }

  private navigate(page: WorkspacePage): void {
    this.activePage = page;
    if (typeof window !== "undefined" && window.location.hash !== `#${page}`) {
      window.history.replaceState(null, "", `#${page}`);
    }
    this.render();
  }
}
