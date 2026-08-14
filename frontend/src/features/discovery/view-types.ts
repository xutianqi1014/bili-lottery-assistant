import type {
  Discovery,
  Problem,
  RunPlan,
  RuntimeSettings,
  SourceProfile,
} from "../../shared/api";

export type WorkspacePage = "overview" | "discovery" | "execution" | "logs";

export type RuntimeLogEntry = {
  id: number;
  at: string;
  level: "info" | "warn" | "error";
  summary: string;
  detail?: string;
  event?: string;
};

export type HealthStatus = {
  ok: boolean;
  browserReady: boolean;
};

export type WorkspaceSnapshot = {
  profile: SourceProfile | null;
  discovery: Discovery | null;
  problems: Problem[];
  plan: RunPlan | null;
  settings: RuntimeSettings | null;
  health: HealthStatus | null;
  statusMessage: string | null;
  logs: RuntimeLogEntry[];
};

export type RenderedWorkspacePage = {
  eyebrow: string;
  title: string;
  subtitle: string;
  content: string;
};

export const WORKSPACE_PAGES: WorkspacePage[] = ["overview", "discovery", "execution", "logs"];
