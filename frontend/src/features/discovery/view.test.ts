import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "../../shared/api";
import { DiscoveryView } from "./view";

class FakeRoot {
  innerHTML = "";

  querySelector<T extends Element>(_selector: string): T | null {
    return null;
  }

  querySelectorAll<T extends Element>(_selector: string): T[] {
    return [];
  }
}

const profile = {
  id: 1,
  sourceKey: "bilibili:100680137",
  displayName: "你的抽奖工具人",
  platform: "bilibili",
  mid: "100680137",
  uploadUrl: "https://space.bilibili.com/100680137/upload/opus",
  adapterKey: "lottery_toolman_v1",
  enabled: true,
  latestPerFamily: 5,
  lastDiscoveryAt: null,
};

const discovery = {
  id: 7,
  profileId: 1,
  state: "preview_ready",
  runPlanId: null as number | null,
  selectedReadlists: [],
  stats: {
    selectedArticles: 10,
    unknownMarkers: 0,
    activityRefsUnique: 1,
    automaticPlanState: "created",
  },
  errorCode: null,
  errorDetail: null,
  selections: [],
  activities: [
    {
      id: 21,
      dynamicId: "510000001",
      url: "https://www.bilibili.com/opus/510000001",
      title: "官方活动",
      bodyExcerpt: "",
      mode: "unknown",
      unofficialType: "unknown",
      platformStatus: "unchecked",
      classification: {},
      origins: [
        {
          sourceArticleId: 31,
          sourceArticleTitle: "来源专栏",
          family: "official",
          sourcePosition: 1,
        },
      ],
      runtimeInspectedAt: null,
    },
  ],
};

const emptyPlan = {
  id: 9,
  discoveryRunId: 7,
  state: "awaiting_confirmation",
  executionPolicy: "confirm_each",
  familyOrder: ["normal", "official"],
  stats: {
    totalActivities: 1,
    plannedActivities: 1,
    blockedActivities: 0,
    skippedActivities: 0,
  },
  directWriteEnabled: false,
  confirmationNote: null,
  statusDetail: null,
  createdAt: "2026-08-08T00:00:00Z",
  startedAt: null,
  confirmedAt: null,
  finishedAt: null,
  items: [],
};

const officialWaitingPlan = {
  ...emptyPlan,
  directWriteEnabled: false,
  officialAutomationEnabled: false,
  items: [
    {
      activityId: 21,
      sequence: 1,
      dynamicId: "510000001",
      url: "https://www.bilibili.com/opus/510000001",
      title: "官方活动",
      family: "official",
      mode: "unknown",
      unofficialType: "unknown",
      platformStatus: "unchecked",
      sourceArticleIds: [31],
      actionPlan: ["open_dynamic"],
      state: "planned",
      blockReason: null,
      runtimeInspectedAt: null as string | null,
      runtimeSelectorVersion: null as string | null,
      runtimeInspection: {},
      resultCode: null as string | null,
      resultMessage: null as string | null,
    },
  ],
};

afterEach(() => {
  vi.restoreAllMocks();
});

function showPage(
  view: DiscoveryView,
  activePage: "overview" | "discovery" | "execution" | "logs",
): void {
  (view as unknown as { activePage: typeof activePage }).activePage = activePage;
}

describe("DiscoveryView no-preflight workflow", () => {
  it("shows automatic plan creation without a separate plan button", () => {
    vi.spyOn(api, "health").mockResolvedValue({ ok: true, browserReady: false });
    const root = new FakeRoot();
    const view = new DiscoveryView(root as unknown as HTMLElement);
    const internal = view as unknown as {
      profile: typeof profile;
      discovery: typeof discovery;
      problems: never[];
    };
    internal.profile = profile;
    internal.discovery = discovery;
    internal.problems = [];

    showPage(view, "discovery");
    view.render();

    expect(root.innerHTML).toContain("执行计划已自动生成");
    expect(root.innerHTML).toContain("执行时读取");
    expect(root.innerHTML).toContain("未检查");
    expect(root.innerHTML).not.toContain("生成执行计划（不打开动态）");
    expect(root.innerHTML).not.toContain("data-create-plan");
    expect(root.innerHTML).not.toContain("开始活动只读预检");
    expect(root.innerHTML).not.toContain("data-preflight");
    expect("createRunPlan" in api).toBe(false);
  });

  it("shows the built-in source picker when more than one source is enabled", () => {
    const root = new FakeRoot();
    const view = new DiscoveryView(root as unknown as HTMLElement);
    const internal = view as unknown as {
      profiles: typeof profile[];
      profile: typeof profile;
      discovery: typeof discovery | null;
      problems: never[];
    };
    internal.profiles = [
      profile,
      {
        ...profile,
        id: 2,
        sourceKey: "nuomi_backpack",
        displayName: "糯米是个背包",
        mid: "492426375",
        latestPerFamily: 3,
      },
    ];
    internal.profile = internal.profiles[1];
    internal.discovery = null;
    internal.problems = [];

    showPage(view, "overview");
    view.render();

    expect(root.innerHTML).toContain("data-source-profile");
    expect(root.innerHTML).toContain("糯米是个背包");
  });

  it("loads the automatically linked plan while refreshing discovery", async () => {
    vi.spyOn(api, "getDiscovery").mockResolvedValue({
      ...discovery,
      runPlanId: 9,
    });
    vi.spyOn(api, "getProblems").mockResolvedValue([]);
    const getRunPlan = vi.spyOn(api, "getRunPlan").mockResolvedValue(emptyPlan);
    const root = new FakeRoot();
    const view = new DiscoveryView(root as unknown as HTMLElement);
    vi.spyOn(view, "render").mockImplementation(() => undefined);

    await view.refresh(7);

    expect(getRunPlan).toHaveBeenCalledOnce();
    expect(getRunPlan).toHaveBeenCalledWith(9);
    expect((view as unknown as { plan: typeof emptyPlan }).plan).toEqual(emptyPlan);
  });

  it("does not show or create a plan when discovery has no candidates", () => {
    vi.spyOn(api, "health").mockResolvedValue({ ok: true, browserReady: false });
    const root = new FakeRoot();
    const view = new DiscoveryView(root as unknown as HTMLElement);
    const internal = view as unknown as {
      profile: typeof profile;
      discovery: typeof discovery;
      problems: never[];
    };
    internal.profile = profile;
    internal.discovery = {
      ...discovery,
      stats: {
        selectedArticles: 10,
        unknownMarkers: 0,
        activityRefsUnique: 0,
        automaticPlanState: "skipped_no_candidates",
      },
      activities: [],
    };
    internal.problems = [];

    showPage(view, "discovery");
    view.render();

    expect(root.innerHTML).toContain("没有待处理动态，本轮不生成执行计划");
    expect(root.innerHTML).not.toContain("RUN PLAN");
    expect(root.innerHTML).not.toContain("data-create-plan");
  });

  it("keeps only the run plan and source closure components on the execution page", () => {
    vi.spyOn(api, "health").mockResolvedValue({ ok: true, browserReady: false });
    const root = new FakeRoot();
    const view = new DiscoveryView(root as unknown as HTMLElement);
    const internal = view as unknown as {
      profile: typeof profile;
      discovery: typeof discovery;
      problems: never[];
      plan: typeof officialWaitingPlan;
    };
    internal.profile = profile;
    internal.discovery = discovery;
    internal.problems = [];
    internal.plan = {
      ...officialWaitingPlan,
      stats: {
        ...officialWaitingPlan.stats,
        officialParticipationWrites: {
          "21": { state: "completed", resultCode: "OFFICIAL_PARTICIPATION_CONFIRMED" },
        },
        unofficialParticipationWrites: {
          "22": { state: "completed", resultCode: "UNOFFICIAL_PARTICIPATION_CONFIRMED" },
        },
        sourceClosure: {
          runId: 9,
          readyToMarkCount: 1,
          alreadyLikedCount: 0,
          blockedCount: 0,
          items: [
            {
              sourceArticleId: 31,
              title: "来源专栏",
              url: "https://www.bilibili.com/read/cv52199999",
              status: "ready_to_mark",
              activityCount: 1,
              terminalActivityCount: 1,
              openProblemCount: 0,
              reasonCodes: [],
            },
          ],
        },
        sourceLikeAutomation: {
          state: "completed",
          resultCode: "SOURCE_LIKE_AUTOMATION_CONFIRMED",
        },
      },
    } as unknown as typeof officialWaitingPlan;

    showPage(view, "execution");
    view.render();

    expect(root.innerHTML).toContain("本次运行计划");
    expect(root.innerHTML).toContain("来源专栏收尾判定");
    expect(root.innerHTML).toContain("run-plan-col-dynamic");
    expect(root.innerHTML).not.toContain("即时结果");
    expect(root.innerHTML).toContain('<span class="family-label">官方</span>');
    expect(root.innerHTML).not.toContain("官方 / 执行时检查");
    expect(root.innerHTML).not.toContain("写操作边界");
    expect(root.innerHTML).not.toContain("官方自动执行清单");
    expect(root.innerHTML).not.toContain("官方自动执行结果");
    expect(root.innerHTML).not.toContain("非官方互动执行结果");
    expect(root.innerHTML).not.toContain("来源专栏自动收尾");
    expect(root.innerHTML).not.toContain("需要处理的问题网址");
    expect(root.innerHTML).not.toContain("SOURCE_LIKE_AUTOMATION_CONFIRMED");
  });

  it("renders a jump control and marks the currently processing dynamic", () => {
    vi.spyOn(api, "health").mockResolvedValue({ ok: true, browserReady: false });
    const root = new FakeRoot();
    const view = new DiscoveryView(root as unknown as HTMLElement);
    const internal = view as unknown as {
      profile: typeof profile;
      discovery: typeof discovery;
      problems: never[];
      plan: typeof officialWaitingPlan;
    };
    internal.profile = profile;
    internal.discovery = discovery;
    internal.problems = [];
    internal.plan = {
      ...officialWaitingPlan,
      state: "running",
      items: officialWaitingPlan.items.map((item) => ({ ...item, state: "running" })),
    };

    showPage(view, "execution");
    view.render();

    expect(root.innerHTML).toContain("正在处理第 1 条动态");
    expect(root.innerHTML).toContain("跳转到当前动态");
    expect(root.innerHTML).toContain('data-jump-current-dynamic data-target-item="21"');
    expect(root.innerHTML).toContain('data-run-item="21" class="run-plan-current-item"');
  });

  it("shows one run-level automatic start action when automation is enabled", () => {
    vi.spyOn(api, "health").mockResolvedValue({ ok: true, browserReady: false });
    const root = new FakeRoot();
    const view = new DiscoveryView(root as unknown as HTMLElement);
    const internal = view as unknown as {
      profile: typeof profile;
      discovery: typeof discovery;
      problems: never[];
      plan: typeof officialWaitingPlan;
    };
    internal.profile = profile;
    internal.discovery = discovery;
    internal.problems = [];
    internal.plan = {
      ...officialWaitingPlan,
      state: "confirmed_waiting_user",
      directWriteEnabled: false,
      officialAutomationEnabled: true,
      items: officialWaitingPlan.items.map((item) => ({
        ...item,
        state: "planned",
        platformStatus: "unchecked",
        resultCode: null,
        resultMessage: null,
      })),
    };

    showPage(view, "execution");
    view.render();

    expect(root.innerHTML).toContain("开始官方自动执行");
    expect(root.innerHTML).toContain("官方条目会按计划顺序自动处理");
    expect(root.innerHTML).not.toContain("官方自动执行清单");
    expect(root.innerHTML).not.toContain("继续下一条／重新检查当前条目");
    expect(root.innerHTML).not.toContain("data-official-authorize");
  });

  it("keeps a runtime reservation classification separate in the plan table", () => {
    vi.spyOn(api, "health").mockResolvedValue({ ok: true, browserReady: false });
    const root = new FakeRoot();
    const view = new DiscoveryView(root as unknown as HTMLElement);
    const internal = view as unknown as {
      profile: typeof profile;
      discovery: typeof discovery;
      problems: never[];
      plan: typeof officialWaitingPlan;
    };
    internal.profile = profile;
    internal.discovery = discovery;
    internal.problems = [];
    internal.plan = {
      ...officialWaitingPlan,
      items: officialWaitingPlan.items.map((item) => ({ ...item, mode: "reservation" })),
    };

    showPage(view, "execution");
    view.render();

    expect(root.innerHTML).toContain('<span class="family-label">预约</span>');
    expect(root.innerHTML).not.toContain('<span class="family-label">官方 /');
  });

  it("merges confirmation and start into one primary action", () => {
    vi.spyOn(api, "health").mockResolvedValue({ ok: true, browserReady: false });
    const root = new FakeRoot();
    const view = new DiscoveryView(root as unknown as HTMLElement);
    const internal = view as unknown as { profile: typeof profile; discovery: typeof discovery; problems: never[]; plan: typeof emptyPlan };
    internal.profile = profile;
    internal.discovery = discovery;
    internal.problems = [];
    internal.plan = emptyPlan;
    showPage(view, "execution");
    view.render();
    expect(root.innerHTML).toContain("确认并开始执行");
    expect(root.innerHTML).toContain("data-confirm-start-run");
    expect(root.innerHTML).not.toContain("data-confirm-plan");
  });

  it("renders the fourth page with concise and detailed runtime logs", () => {
    const root = new FakeRoot();
    const view = new DiscoveryView(root as unknown as HTMLElement);
    (view as unknown as { logs: unknown[] }).logs = [
      { id: 1, at: "12:00:00", level: "info", summary: "执行计划已开始", event: "run.started" },
      { id: 2, at: "12:00:02", level: "error", summary: "运行已中断", detail: '{"problemUrl":"https://example.com","apiKey":"[REDACTED]"}', event: "run.interrupted" },
    ];
    showPage(view, "logs");
    view.render();
    expect(root.innerHTML).toContain("运行日志");
    expect(root.innerHTML).toContain("复制日志");
    expect(root.innerHTML).toContain("清空");
    expect(root.innerHTML).toContain("执行计划已开始");
    expect(root.innerHTML).toContain("[REDACTED]");
  });

  it("chains confirmation and start for the merged action", async () => {
    const confirm = vi.spyOn(api, "confirmRunPlan").mockResolvedValue({ ...emptyPlan, state: "confirmed_waiting_user" });
    const start = vi.spyOn(api, "startRun").mockResolvedValue({ ...emptyPlan, state: "queued" });
    const root = new FakeRoot();
    const view = new DiscoveryView(root as unknown as HTMLElement);
    (view as unknown as { plan: typeof emptyPlan }).plan = emptyPlan;
    await view.confirmAndStartRun();
    expect(confirm).toHaveBeenCalledWith(emptyPlan.id);
    expect(start).toHaveBeenCalledWith(emptyPlan.id);
    expect(confirm.mock.invocationCallOrder[0]).toBeLessThan(start.mock.invocationCallOrder[0]);
  });

  it("keeps the recovery start action after a refreshed confirmed plan", () => {
    const root = new FakeRoot();
    const view = new DiscoveryView(root as unknown as HTMLElement);
    (view as unknown as { plan: typeof emptyPlan; profile: typeof profile; discovery: typeof discovery; problems: never[] }).plan = {
      ...emptyPlan,
      state: "confirmed_waiting_user",
    };
    (view as unknown as { profile: typeof profile }).profile = profile;
    (view as unknown as { discovery: typeof discovery }).discovery = discovery;
    (view as unknown as { problems: never[] }).problems = [];
    showPage(view, "execution");
    view.render();
    expect(root.innerHTML).toContain("开始执行计划");
    expect(root.innerHTML).not.toContain("确认并开始执行");
  });

  it("shows an explicit restart action for a blocked item", () => {
    vi.spyOn(api, "health").mockResolvedValue({ ok: true, browserReady: false });
    const root = new FakeRoot();
    const view = new DiscoveryView(root as unknown as HTMLElement);
    const internal = view as unknown as {
      profile: typeof profile;
      discovery: typeof discovery;
      problems: never[];
      plan: typeof officialWaitingPlan;
    };
    internal.profile = profile;
    internal.discovery = discovery;
    internal.problems = [];
    internal.plan = {
      ...officialWaitingPlan,
      state: "waiting_user",
      stats: { ...officialWaitingPlan.stats, blockedActivities: 1 },
      items: officialWaitingPlan.items.map((item) => ({
        ...item,
        state: "waiting_user",
        platformStatus: "manual_review",
      })),
    };

    showPage(view, "execution");
    view.render();

    expect(root.innerHTML).toContain("data-restart-run");
    expect(root.innerHTML).not.toContain("data-resume-run");
  });

  it("restarts a blocked run through the explicit restart endpoint", async () => {
    const restart = vi.spyOn(api, "restartRun").mockResolvedValue({ ...emptyPlan, state: "queued" });
    const view = new DiscoveryView(new FakeRoot() as unknown as HTMLElement);
    (view as unknown as { plan: typeof emptyPlan }).plan = {
      ...emptyPlan,
      state: "waiting_user",
      stats: { ...emptyPlan.stats, blockedActivities: 1 },
    };

    await view.restartRun();

    expect(restart).toHaveBeenCalledWith(emptyPlan.id);
    expect((view as unknown as { plan: typeof emptyPlan }).plan.state).toBe("queued");
  });

  it("keeps normal event logs short and redacts interruption details", () => {
    const view = new DiscoveryView(new FakeRoot() as unknown as HTMLElement);
    view.ingestEvent("run.started", { runId: 9, secret: "do-not-log" });
    view.ingestEvent("run.interrupted", { runId: 9, problemUrl: "https://example.com", apiKey: "do-not-log" });
    const logs = (view as unknown as { logs: Array<{ detail?: string; summary: string }> }).logs;
    expect(logs[0].summary).toContain("执行计划已开始");
    expect(logs[0].detail).toBeUndefined();
    expect(logs[1].detail).toContain("[REDACTED]");
    expect(logs[1].detail).not.toContain("do-not-log");
  });

  it("shows only the non-official family label in the run plan", () => {
    vi.spyOn(api, "health").mockResolvedValue({ ok: true, browserReady: false });
    const root = new FakeRoot();
    const view = new DiscoveryView(root as unknown as HTMLElement);
    const internal = view as unknown as {
      profile: typeof profile;
      discovery: typeof discovery;
      problems: never[];
      plan: typeof officialWaitingPlan;
    };
    internal.profile = profile;
    internal.discovery = discovery;
    internal.problems = [];
    internal.plan = {
      ...officialWaitingPlan,
      state: "confirmed_waiting_user",
      items: officialWaitingPlan.items.map((item) => ({
        ...item,
        family: "normal",
        mode: "unofficial",
        unofficialType: "boosted",
        state: "waiting_user",
        runtimeInspection: {
          unofficialActionPlan: {
            actions: ["comment", "repost", "like", "follow"],
            interactionStrategy: "comment_with_repost_checkbox",
          },
          unofficialCheckpoints: {
            status: "ready",
            nextAction: "comment",
          },
        },
      })),
    };

    showPage(view, "execution");
    view.render();

    expect(root.innerHTML).toContain("开始执行计划");
    expect(root.innerHTML).not.toContain("开始官方自动执行");
    expect(root.innerHTML).toContain('<span class="family-label">非官方</span>');
    expect(root.innerHTML).not.toContain("非官方 / 执行时检查");
    expect(root.innerHTML).not.toContain("comment→repost→like→follow");
    expect(root.innerHTML).not.toContain("下一步：comment");
  });

  it("does not expose stored unofficial result details after removing the result column", () => {
    vi.spyOn(api, "health").mockResolvedValue({ ok: true, browserReady: false });
    const root = new FakeRoot();
    const view = new DiscoveryView(root as unknown as HTMLElement);
    const internal = view as unknown as {
      profile: typeof profile;
      discovery: typeof discovery;
      problems: never[];
      plan: typeof officialWaitingPlan;
    };
    internal.profile = profile;
    internal.discovery = discovery;
    internal.problems = [];
    internal.plan = {
      ...officialWaitingPlan,
      state: "waiting_user",
      stats: {
        ...officialWaitingPlan.stats,
        unofficialParticipationWrites: {
          "21": {
            state: "blocked_failed",
            checkpoint: {
              status: "blocked_failed",
              nextAction: null,
            },
          },
        },
      },
      items: officialWaitingPlan.items.map((item) => ({
        ...item,
        family: "normal",
        mode: "unofficial",
        state: "waiting_user",
        resultCode: "FOLLOW_CONTROL_NOT_UNIQUE",
        resultMessage: "exactly one visible profile follow button is required",
        runtimeInspection: {
          unofficialActionPlan: {
            actions: ["comment", "repost", "like", "follow"],
            interactionStrategy: "comment_with_repost_checkbox",
          },
          unofficialCheckpoints: {
            status: "ready",
            nextAction: "comment",
          },
        },
      })),
    } as unknown as typeof officialWaitingPlan;

    showPage(view, "execution");
    view.render();

    expect(root.innerHTML).toContain("waiting_user");
    expect(root.innerHTML).toContain('<span class="family-label">非官方</span>');
    expect(root.innerHTML).not.toContain("即时结果");
    expect(root.innerHTML).not.toContain("FOLLOW_CONTROL_NOT_UNIQUE");
    expect(root.innerHTML).not.toContain("exactly one visible profile follow button is required");
    expect(root.innerHTML).not.toContain("检查点：blocked_failed");
    expect(root.innerHTML).not.toContain("下一步：comment");
  });

  it("shows the source closure decision without the automatic-tail detail component", () => {
    vi.spyOn(api, "health").mockResolvedValue({ ok: true, browserReady: false });
    const root = new FakeRoot();
    const view = new DiscoveryView(root as unknown as HTMLElement);
    const internal = view as unknown as {
      profile: typeof profile;
      discovery: typeof discovery;
      problems: never[];
      plan: typeof officialWaitingPlan;
    };
    internal.profile = profile;
    internal.discovery = discovery;
    internal.problems = [];
    internal.plan = {
      ...officialWaitingPlan,
      state: "completed",
      sourceLikeAutomationEnabled: true,
      sourceLikeAutomationDelayMinSec: 3,
      sourceLikeAutomationDelayMaxSec: 5,
      stats: {
        ...officialWaitingPlan.stats,
        sourceClosure: {
          runId: 9,
          readyToMarkCount: 0,
          alreadyLikedCount: 1,
          blockedCount: 0,
          items: [
            {
              sourceArticleId: 31,
              title: "来源专栏",
              url: "https://www.bilibili.com/read/cv52199999",
              status: "already_liked",
              activityCount: 1,
              terminalActivityCount: 1,
              openProblemCount: 0,
              reasonCodes: ["SOURCE_ALREADY_LIKED"],
            },
          ],
        },
        sourceLikeAutomation: {
          state: "completed",
          targetCount: 1,
          completedCount: 1,
          resultCode: "SOURCE_LIKE_AUTOMATION_CONFIRMED",
          resultMessage: "1 个来源专栏已自动点赞并确认终态",
          writes: {
            "31": {
              state: "completed",
              sourceArticleId: 31,
              title: "来源专栏",
              targetUrl: "https://www.bilibili.com/read/cv52199999",
              resultCode: "SOURCE_LIKE_CONFIRMED",
            },
          },
        },
      },
    } as unknown as typeof officialWaitingPlan;

    showPage(view, "execution");
    view.render();

    expect(root.innerHTML).toContain("来源专栏收尾判定");
    expect(root.innerHTML).toContain("已点赞（无需处理）");
    expect(root.innerHTML).toContain("SOURCE_ALREADY_LIKED");
    expect(root.innerHTML).not.toContain("来源专栏自动收尾");
    expect(root.innerHTML).not.toContain("SOURCE_LIKE_AUTOMATION_CONFIRMED");
    expect(root.innerHTML).not.toContain("确认来源收尾计划");
    expect(root.innerHTML).not.toContain("data-confirm-source-like");
    expect("confirmSourceLikePlan" in api).toBe(false);
    expect("executeSourceLike" in api).toBe(false);
  });
});
