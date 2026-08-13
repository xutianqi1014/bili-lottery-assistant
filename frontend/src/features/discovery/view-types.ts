import type {
  Discovery,
  Problem,
  RunPlan,
  RuntimeSettings,
  SourceProfile,
} from "../../shared/api";

export type WorkspacePage = "overview" | "discovery" | "execution";

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
};

export type RenderedWorkspacePage = {
  eyebrow: string;
  title: string;
  subtitle: string;
  content: string;
};

export const WORKSPACE_PAGES: WorkspacePage[] = ["overview", "discovery", "execution"];

