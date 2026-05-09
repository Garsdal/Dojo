// --- Domain ---

export type DomainStatus =
  | "draft"
  | "active"
  | "paused"
  | "completed"
  | "archived";

export type WorkspaceSource = "local" | "git" | "empty";

export interface Workspace {
  path: string;
  source: WorkspaceSource;
  ready: boolean;
  python_path: string | null;
  git_url: string | null;
}

export interface DomainTool {
  id: string;
  name: string;
  description: string;
  type: string;
  example_usage: string;
  code: string;
  module_filename: string;
  entrypoint: string;
  created_by: string;
  created_at: string;
  return_description?: string;
}

export interface Domain {
  id: string;
  name: string;
  description: string;
  prompt: string;
  status: DomainStatus;
  config: Record<string, unknown>;
  metadata: Record<string, unknown>;
  experiment_ids: string[];
  tools: DomainTool[];
  workspace: Workspace | null;
  created_at: string;
  updated_at: string;
}

// --- Experiments ---

export interface Experiment {
  id: string;
  domain_id: string;
  hypothesis: string | null;
  state: "pending" | "running" | "completed" | "failed" | "archived";
  config: Record<string, unknown>;
  metrics: Record<string, number> | null;
  error: string | null;
}

export interface CodeRun {
  run_number: number;
  code_path: string;
  description: string;
  exit_code: number;
  duration_ms: number;
  timestamp: string;
}

export interface CodeRunDetail extends CodeRun {
  code: string;
}

// --- Knowledge ---

export interface KnowledgeAtom {
  id: string;
  domain_id: string;
  source_experiment_id: string;
  context: string;
  claim: string;
  action: string;
  confidence: number;
  evidence_ids: string[];
}

export interface KnowledgeLink {
  id: string;
  atom_id: string;
  experiment_id: string;
  domain_id: string;
  link_type: string;
  related_atom_id: string | null;
  created_at: string;
}

export interface KnowledgeDetail {
  atom: KnowledgeAtom;
  links: KnowledgeLink[];
}

export interface LinkingResult {
  atom_id: string;
  action: "created";
  confidence: number;
  related_to: string[] | null;
}

// --- Metrics ---

export interface MetricPoint {
  experiment_id: string;
  timestamp: string;
  metrics: Record<string, number>;
}

// --- Agent ---

export interface AgentRun {
  id: string;
  domain_id: string;
  prompt: string;
  status: "pending" | "running" | "completed" | "failed" | "stopped";
  events: AgentEvent[];
  started_at: string | null;
  completed_at: string | null;
  total_cost_usd: number | null;
  num_turns: number;
  error: string | null;
}

export interface AgentEvent {
  id: string;
  timestamp: string;
  event_type: string;
  data: Record<string, unknown>;
}

export interface ToolHint {
  name: string;
  description: string;
  source: string;
  code_template?: string;
}

// --- Health / Config ---

export interface HealthStatus {
  status: "ok" | "error";
}

export interface AppConfig {
  api: { host: string; port: number };
  storage: { base_dir: string };
  llm: { provider: string; model: string };
  tracking: { enabled: boolean };
}
