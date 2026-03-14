// --- Domain ---

export type DomainStatus =
  | "draft"
  | "active"
  | "paused"
  | "completed"
  | "archived";

export interface DomainTool {
  id: string;
  name: string;
  description: string;
  type: string;
  example_usage: string;
  parameters: Record<string, unknown>;
  created_by: string;
  created_at: string;
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
  created_at: string;
  updated_at: string;
}

// --- Experiments ---

export interface Experiment {
  id: string;
  domain_id: string;
  state: "pending" | "running" | "completed" | "failed" | "archived";
  config: Record<string, unknown>;
  metrics: Record<string, number> | null;
  error: string | null;
}

// --- Knowledge ---

export interface KnowledgeAtom {
  id: string;
  context: string;
  claim: string;
  action: string;
  confidence: number;
  evidence_ids: string[];
  version: number;
  supersedes: string | null;
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
  version: number;
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
