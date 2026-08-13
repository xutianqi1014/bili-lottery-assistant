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
import type { HealthStatus, WorkspacePage, WorkspaceSnapshot } from "./view-types";
import { WORKSPACE_PAGES } from "./view-types";
import { renderWorkspaceShell } from "./workspace-shell";
import {
  forgetDiscoveryId,
  recallDiscoveryId,
  rememberDiscoveryId,
} from "../../shared/workspace-session";

export class DiscoveryView {
  private root: HTMLElement;
  private profile: SourceProfile | null = null;
  private discovery: Discovery | null = null;
  private problems: Problem[] = [];
  private plan: RunPlan | null = null;
  private settings: RuntimeSettings | null = null;
  private health: HealthStatus | null = null;
  private activePage: WorkspacePage;
  private statusMessage: string | null = null;

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
    this.profile = sources.find((item) => item.enabled) ?? null;
    this.settings = settings;
    this.health = health;
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
    this.settings = await api.updateSettings({
      deepseekApiKey: apiKey || undefined,
      clearDeepseekApiKey: clearKey,
      deepseekApiUrl: String(formData.get("deepseekApiUrl") ?? "").trim() || undefined,
      deepseekModel: String(formData.get("deepseekModel") ?? "").trim() || undefined,
      mentionNames,
    });
    this.render();
    this.setMessage("运行设置已保存；DeepSeek Key 仅保存在当前本地服务进程内。");
  }

  async start(): Promise<void> {
    if (!this.profile) return;
    this.plan = null;
    this.setMessage("正在创建只读发现任务；发现候选后将自动生成执行计划……");
    const result = await api.startDiscovery(this.profile.id);
    rememberDiscoveryId(result.discoveryId);
    await this.refresh(result.discoveryId);
  }

  async refresh(id?: number): Promise<void> {
    const target = id ?? this.discovery?.id;
    if (!target) return;
    this.discovery = await api.getDiscovery(target);
    rememberDiscoveryId(target);
    this.problems = await api.getProblems(target);
    if (this.discovery.runPlanId && this.plan?.id !== this.discovery.runPlanId) {
      this.plan = await api.getRunPlan(this.discovery.runPlanId);
    }
    this.render();
    if (this.discovery.state === "running") {
      window.setTimeout(() => void this.refresh(target), 1200);
    }
  }

  async confirmPlan(): Promise<void> {
    if (!this.plan) return;
    this.setMessage("正在保存本次运行计划确认……");
    this.plan = await api.confirmRunPlan(this.plan.id);
    this.render();
  }

  async startRun(): Promise<void> {
    if (!this.plan) return;
    this.setMessage(this.plan.officialAutomationEnabled
      ? "正在排队；将按确认计划自动处理官方动态……"
      : "正在排队；只会逐条打开当前动态并读取页面状态……");
    this.plan = await api.startRun(this.plan.id);
    this.render();
  }

  async resumeRun(): Promise<void> {
    if (!this.plan) return;
    this.setMessage("正在继续当前只读条目……");
    this.plan = await api.resumeRun(this.plan.id);
    this.render();
  }

  async refreshPlan(id = this.plan?.id): Promise<void> {
    if (!id) return;
    this.plan = await api.getRunPlan(id);
    this.render();
  }

  render(): void {
    const snapshot = this.snapshot();
    const page = this.activePage === "overview"
      ? renderOverviewPage(snapshot)
      : this.activePage === "discovery"
        ? renderDiscoveryPage(snapshot)
        : renderExecutionPage(snapshot);
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
    this.root.querySelector<HTMLFormElement>("[data-settings-form]")?.addEventListener(
      "submit",
      (event) => {
        event.preventDefault();
        const form = event.currentTarget;
        if (form instanceof HTMLFormElement) {
          void this.saveSettings(form).catch((error) => {
            this.setMessage(`保存运行设置失败：${String(error)}`);
          });
        }
      },
    );
    this.root.querySelector<HTMLButtonElement>("[data-refresh]")?.addEventListener(
      "click",
      () => void this.refresh(),
    );
    this.root.querySelector<HTMLButtonElement>("[data-confirm-plan]")?.addEventListener(
      "click",
      () => void this.confirmPlan().catch((error) => {
        this.setMessage(`确认计划失败：${String(error)}`);
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
      }),
    );
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

  private snapshot(): WorkspaceSnapshot {
    return {
      profile: this.profile,
      discovery: this.discovery,
      problems: this.problems,
      plan: this.plan,
      settings: this.settings,
      health: this.health,
      statusMessage: this.statusMessage,
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
