// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, type Discovery, type RunPlan, type RuntimeSettings, type SourceProfile } from "../../shared/api";
import { DiscoveryView } from "./view";

const profiles: SourceProfile[] = [1, 2].map(id => ({
  id, sourceKey: String(id), displayName: "source" + id, platform: "bilibili",
  mid: String(id), uploadUrl: "https://space.bilibili.com/" + id,
  adapterKey: "test", enabled: true, latestPerFamily: 5, lastDiscoveryAt: null,
}));
const settings: RuntimeSettings = {
  deepseekConfigured: false, deepseekApiUrl: "https://api.deepseek.com/chat/completions",
  deepseekModel: "test", mentionNames: ["one"], unofficialAutomationEnabled: true,
  unofficialAutomationDelayMinSec: 1, unofficialAutomationDelayMaxSec: 2,
};
const discovery: Discovery = {
  id: 7, profileId: 1, state: "preview_ready", runPlanId: null,
  selectedReadlists: [], stats: {}, errorCode: null, errorDetail: null, selections: [], activities: [],
};
const plan: RunPlan = {
  id: 9, discoveryRunId: 7, state: "running", executionPolicy: "confirm_each",
  familyOrder: [], stats: {}, directWriteEnabled: false, confirmationNote: null,
  statusDetail: null, createdAt: "", startedAt: null, confirmedAt: null, finishedAt: null, items: [],
};
const views: DiscoveryView[] = [];
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}
async function setup() {
  const root = document.createElement("div");
  document.body.append(root);
  const view = new DiscoveryView(root);
  views.push(view);
  await view.load();
  return { root, view };
}
beforeEach(() => {
  sessionStorage.clear();
  location.hash = "#overview";
  vi.spyOn(api, "listSources").mockResolvedValue(profiles);
  vi.spyOn(api, "getSettings").mockResolvedValue(settings);
  vi.spyOn(api, "health").mockResolvedValue({ ok: true, browserReady: false });
  vi.spyOn(api, "getDiscovery").mockResolvedValue(discovery);
  vi.spyOn(api, "getProblems").mockResolvedValue([]);
  vi.spyOn(api, "getRunPlan").mockResolvedValue(plan);
});
afterEach(() => {
  views.splice(0).forEach(view => view.dispose());
  vi.useRealTimers();
  vi.restoreAllMocks();
  document.body.innerHTML = "";
});

describe("stage 1-3 workspace regressions", () => {
  it("discards a discovery response after switching sources", async () => {
    const { root, view } = await setup();
    const pending = deferred<Discovery>();
    vi.mocked(api.getDiscovery).mockReturnValueOnce(pending.promise);
    const refresh = view.refresh(7);
    view.selectProfile(2);
    pending.resolve(discovery);
    await refresh;
    expect(root.querySelector<HTMLSelectElement>("[data-source-profile]")?.value).toBe("2");
    expect(api.getProblems).not.toHaveBeenCalled();
    expect(sessionStorage.getItem("bili-lottery-assistant.current-discovery-id")).toBeNull();
  });

  it("uses one poll timer and stops polling after a terminal response", async () => {
    vi.useFakeTimers();
    const { view } = await setup();
    vi.mocked(api.getDiscovery).mockResolvedValue({ ...discovery, state: "running" });
    await Promise.all([view.refresh(7), view.refresh(7), view.refresh(7)]);
    await vi.advanceTimersByTimeAsync(0); // Drain jsdom's zero-delay document events.
    expect(vi.getTimerCount()).toBe(1);
    vi.mocked(api.getDiscovery).mockResolvedValue(discovery);
    await vi.advanceTimersByTimeAsync(1200);
    expect(vi.getTimerCount()).toBe(0);
    const calls = vi.mocked(api.getDiscovery).mock.calls.length;
    await vi.advanceTimersByTimeAsync(6000);
    expect(api.getDiscovery).toHaveBeenCalledTimes(calls);
  });

  it("discards pending plan responses after a workspace switch", async () => {
    const { root, view } = await setup();
    await view.refresh(7);
    const pending = deferred<RunPlan>();
    vi.mocked(api.getRunPlan).mockReturnValueOnce(pending.promise);
    const refresh = view.refreshPlan(9);
    view.selectProfile(2);
    pending.resolve(plan);
    await refresh;
    root.querySelector<HTMLButtonElement>('[data-view="execution"]')!.click();
    expect(root.textContent).toContain("尚未生成执行计划");
  });

  it("coalesces plan events and fetches once more for an event received in flight", async () => {
    const { view } = await setup();
    const pending = deferred<RunPlan>();
    vi.mocked(api.getRunPlan).mockReturnValueOnce(pending.promise)
      .mockResolvedValue({ ...plan, state: "completed" });
    const first = view.refreshPlan(9);
    const second = view.refreshPlan(9);
    const third = view.refreshPlan(9);
    expect(api.getRunPlan).toHaveBeenCalledTimes(1);
    pending.resolve(plan);
    await Promise.all([first, second, third]);
    expect(api.getRunPlan).toHaveBeenCalledTimes(2);
  });

  it("ignores events for a different discovery or run", async () => {
    const { view } = await setup();
    await view.refresh(7);
    vi.mocked(api.getDiscovery).mockClear();
    vi.mocked(api.getRunPlan).mockClear();
    view.handleEvent("discovery.ready", { discoveryId: 99 });
    view.handleEvent("run.finished", { runId: 99 });
    expect(api.getDiscovery).not.toHaveBeenCalled();
    expect(api.getRunPlan).not.toHaveBeenCalled();
  });

  it("preserves the live draft, checkbox, focus and selection during background renders", async () => {
    const { root, view } = await setup();
    const input = root.querySelector<HTMLInputElement>('[name="deepseekApiKey"]')!;
    const checkbox = root.querySelector<HTMLInputElement>('[name="clearDeepseekApiKey"]')!;
    input.value = "unsaved-test-key";
    checkbox.checked = true;
    input.focus();
    input.setSelectionRange(2, 5);
    await view.refreshPlan(9);
    expect(root.querySelector('[name="deepseekApiKey"]')).toBe(input);
    expect(input.value).toBe("unsaved-test-key");
    expect(checkbox.checked).toBe(true);
    expect(document.activeElement).toBe(input);
    expect([input.selectionStart, input.selectionEnd]).toEqual([2, 5]);
    expect(sessionStorage.getItem("unsaved-test-key")).toBeNull();
  });

  it("does not multiply submit listeners when a form is reused", async () => {
    const { root, view } = await setup();
    const update = vi.spyOn(api, "updateSettings").mockResolvedValue(settings);
    view.render();
    view.render();
    const form = root.querySelector<HTMLFormElement>("[data-settings-form]")!;
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await Promise.resolve();
    expect(update).toHaveBeenCalledTimes(1);
  });

  it("does not reopen the old workspace when discovery creation finishes late", async () => {
    const { root, view } = await setup();
    const pending = deferred<{ discoveryId: number }>();
    vi.spyOn(api, "startDiscovery").mockReturnValueOnce(pending.promise);
    const started = view.start();
    view.selectProfile(2);
    pending.resolve({ discoveryId: 7 });
    await started;
    expect(root.querySelector<HTMLSelectElement>("[data-source-profile]")?.value).toBe("2");
    expect(api.getDiscovery).not.toHaveBeenCalled();
  });
  it("does not auto-start or restore a run if its confirmation finishes after switching", async () => {
    const { root, view } = await setup();
    await view.refresh(7);
    await view.refreshPlan(9);
    const pending = deferred<RunPlan>();
    vi.spyOn(api, "confirmRunPlan").mockReturnValueOnce(pending.promise);
    const start = vi.spyOn(api, "startRun").mockResolvedValue(plan);
    const action = view.confirmAndStartRun();
    view.selectProfile(2);
    pending.resolve({ ...plan, state: "confirmed_waiting_user" });
    await action;
    expect(start).not.toHaveBeenCalled();
    root.querySelector<HTMLButtonElement>('[data-view="execution"]')!.click();
    expect(root.textContent).toContain("尚未生成执行计划");
  });

  it("shows the source count and configured limit before execution", async () => {
    const { root, view } = await setup();
    vi.mocked(api.getRunPlan).mockResolvedValue({
      ...plan, state: "awaiting_confirmation", sourceLikeAutomationMaxItemsPerRun: 10,
      stats: { sourceClosure: { items: Array.from({ length: 15 }, (_, i) => ({
        sourceArticleId: i + 1, status: "blocked_not_marked",
      })) } },
    });
    await view.refreshPlan(9);
    root.querySelector<HTMLButtonElement>('[data-view="execution"]')!.click();
    expect(root.textContent).toContain("本计划包含 15 篇来源，单轮自动收尾上限 10 篇");
    expect(root.textContent).toContain("将停止收尾且不点击");
  });

  it("coalesces log bursts and a plan response without replacing navigation or existing rows", async () => {
    vi.useFakeTimers();
    location.hash = "#logs";
    const { root, view } = await setup();
    const nav = root.querySelector('[data-view="overview"]');
    const first = root.querySelector("[data-log-id]");
    const copy = root.querySelector("[data-copy-logs]");
    const render = vi.spyOn(view, "render");
    for (let i = 0; i < 20; i++) view.ingestEvent("run.item_updated", { sequence: i });
    await view.refreshPlan(9);
    await vi.advanceTimersByTimeAsync(32);
    expect(render).toHaveBeenCalledTimes(1);
    expect(root.querySelectorAll("[data-log-id]")).toHaveLength(21);
    expect(root.querySelector('[data-view="overview"]')).toBe(nav);
    expect(root.querySelector("[data-log-id]")).toBe(first);
    expect(root.querySelector("[data-copy-logs]")).toBe(copy);
    expect(root.querySelector(".workflow-rail")?.textContent).toContain("running");
  });

  it("bounds incremental logs, redacts details and clears them with the original button", async () => {
    vi.useFakeTimers();
    location.hash = "#logs";
    const { root, view } = await setup();
    const clear = root.querySelector<HTMLButtonElement>("[data-clear-logs]")!;
    for (let i = 0; i < 600; i++) view.ingestEvent("run.item_updated", { sequence: i });
    view.ingestEvent("run.waiting_user", { secret: "secret-value", reason: "<script>bad</script>" });
    await vi.advanceTimersByTimeAsync(32);
    expect(root.querySelectorAll("[data-log-id]")).toHaveLength(500);
    expect(root.textContent).toContain("[REDACTED]");
    expect(root.textContent).not.toContain("secret-value");
    expect(root.querySelector("script")).toBeNull();
    expect(root.querySelector("[data-log-description]")?.textContent).toContain("500 条记录");
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    clear.click();
    expect(confirm).toHaveBeenCalledTimes(1);
    expect(root.querySelectorAll("[data-log-id]")).toHaveLength(0);
    expect(clear.disabled).toBe(true);
    expect(root.querySelector(".runtime-log-empty")).not.toBeNull();
  });

  it("cancels scheduled log updates on dispose", async () => {
    vi.useFakeTimers();
    location.hash = "#logs";
    const { view } = await setup();
    const render = vi.spyOn(view, "render");
    view.ingestEvent("run.item_updated", {});
    view.dispose();
    await vi.advanceTimersByTimeAsync(32);
    expect(render).not.toHaveBeenCalled();
  });
});
