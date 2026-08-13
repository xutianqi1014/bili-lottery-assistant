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
  activePage: "overview" | "discovery" | "execution",
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
