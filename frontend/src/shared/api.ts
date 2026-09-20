export type SourceProfile = {
  id: number;
  sourceKey: string;
  displayName: string;
  platform: string;
  mid: string;
  uploadUrl: string;
  adapterKey: string;
  enabled: boolean;
  latestPerFamily: number;
  sourcePages?: Array<{ mid: string; uploadUrl: string }>;
  activityTypes?: string[];
  lastDiscoveryAt: string | null;
};

export type DiscoverySelection = {
  sourceArticleId: number;
  articleId: string;
  title: string;
  url: string;
  readlistTitle: string;
  family: string;
  rank: number;
  position: number;
  likeState: "liked" | "unliked" | "unknown";
  decision: "skip_processed" | "process" | "manual_review";
  reason: string;
  parseStatus: string;
  parseStats: Record<string, unknown>;
};

export type ActivityPreview = {
  id: number;
  dynamicId: string;
  url: string;
  title: string;
  bodyExcerpt: string;
  mode: string;
  unofficialType: string;
  platformStatus: string;
  classification: {
    confidence?: string;
    evidenceCodes?: string[];
    requiredTopics?: string[];
    requiredMentionCount?: number;
    commentInstruction?: string;
  };
  origins: Array<{
    sourceArticleId: number;
    sourceArticleTitle: string;
    family: string;
    sourcePosition: number;
    sourceSection?: string | null;
  }>;
  runtimeInspectedAt: string | null;
};

export type RunItem = {
  activityId: number;
  sequence: number;
  dynamicId: string;
  url: string;
  title: string;
  family: string;
  sourceSection: string | null;
  mode: string;
  unofficialType: string;
  platformStatus: string;
  sourceArticleIds: number[];
  actionPlan: string[];
  state: string;
  blockReason: string | null;
  runtimeInspectedAt: string | null;
  runtimeSelectorVersion: string | null;
  runtimeInspection: Record<string, unknown>;
  resultCode: string | null;
  resultMessage: string | null;
};

export type RunPlan = {
  id: number;
  discoveryRunId: number;
  state: string;
  executionPolicy: string;
  familyOrder: string[];
  stats: Record<string, unknown>;
  directWriteEnabled: boolean;
  /** True when confirmed-run official automation is enabled. */
  officialAutomationEnabled?: boolean;
  officialAutomationDelayMinSec?: number;
  officialAutomationDelayMaxSec?: number;
  sourceLikeAutomationEnabled?: boolean;
  sourceLikeAutomationMaxItemsPerRun?: number;
  sourceLikeAutomationDelayMinSec?: number;
  sourceLikeAutomationDelayMaxSec?: number;
  unofficialAutomationEnabled?: boolean;
  unofficialAutomationDelayMinSec?: number;
  unofficialAutomationDelayMaxSec?: number;
  deepseekConfigured?: boolean;
  confirmationNote: string | null;
  statusDetail: string | null;
  createdAt: string;
  startedAt: string | null;
  confirmedAt: string | null;
  finishedAt: string | null;
  items: RunItem[];
};

export type RuntimeSettings = {
  deepseekConfigured: boolean;
  deepseekApiUrl: string;
  deepseekModel: string;
  mentionNames: string[];
  unofficialAutomationEnabled: boolean;
  unofficialAutomationDelayMinSec: number;
  unofficialAutomationDelayMaxSec: number;
};

export type SourceClosureItem = {
  sourceArticleId: number;
  title: string;
  url: string;
  status: "ready_to_mark" | "already_liked" | "blocked_not_marked" | string;
  readyToMark: boolean;
  activityCount: number;
  terminalActivityCount: number;
  pendingActivityCount: number;
  openProblemCount: number;
  problemCodes: string[];
  reasonCodes: string[];
};

export type SourceClosureSummary = {
  runId: number;
  readyToMarkCount: number;
  alreadyLikedCount: number;
  blockedCount: number;
  items: SourceClosureItem[];
};

export type Discovery = {
  id: number;
  profileId: number;
  state: string;
  runPlanId: number | null;
  selectedReadlists: Array<Record<string, unknown>>;
  stats: Record<string, number | string | boolean>;
  errorCode: string | null;
  errorDetail: string | null;
  selections: DiscoverySelection[];
  activities: ActivityPreview[];
};

export type Problem = {
  id: number;
  sourceArticleId: number | null;
  problemUrl: string;
  pageType: string;
  stage: string;
  problemCode: string;
  safeDetail: string;
  occurrenceCount: number;
  status: string;
};

let csrfToken = "";

export async function initializeSession(): Promise<string> {
  const response = await fetch("/api/session");
  if (!response.ok) throw new Error("无法建立本机会话");
  csrfToken = (await response.json()).csrfToken;
  return csrfToken;
}

async function request<T>(url: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body) headers.set("Content-Type", "application/json");
  if (init.method && init.method !== "GET") headers.set("X-CSRF-Token", csrfToken);
  const response = await fetch(url, { ...init, headers });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${response.status}: ${detail}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  getSettings: () => request<RuntimeSettings>("/api/settings"),
  updateSettings: (payload: {
    deepseekApiKey?: string;
    clearDeepseekApiKey?: boolean;
    deepseekApiUrl?: string;
    deepseekModel?: string;
    mentionNames?: string[];
  }) => request<RuntimeSettings>("/api/settings", {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  listSources: () => request<SourceProfile[]>("/api/source-profiles"),
  openLogin: () => request<{ ok: boolean }>("/api/account/open-login", { method: "POST" }),
  startDiscovery: (profileId: number) =>
    request<{ discoveryId: number }>(`/api/source-profiles/${profileId}/discoveries`, { method: "POST" }),
  confirmRunPlan: (runId: number, note = "用户已确认计划") =>
    request<RunPlan>(`/api/runs/${runId}/confirm`, {
      method: "POST",
      body: JSON.stringify({ note }),
    }),
  startRun: (runId: number) =>
    request<RunPlan>(`/api/runs/${runId}/start`, {
      method: "POST",
      body: "{}",
    }),
  resumeRun: (runId: number) =>
    request<RunPlan>(`/api/runs/${runId}/resume`, {
      method: "POST",
      body: "{}",
    }),
  restartRun: (runId: number) =>
    request<RunPlan>(`/api/runs/${runId}/restart`, {
      method: "POST",
      body: "{}",
    }),
  getRunPlan: (runId: number) => request<RunPlan>(`/api/runs/${runId}`),
  getDiscovery: (id: number) => request<Discovery>(`/api/discoveries/${id}`),
  getProblems: (id: number) => request<Problem[]>(`/api/discoveries/${id}/problems`),
  health: () => request<{ ok: boolean; browserReady: boolean }>("/api/health")
};
