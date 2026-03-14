import useSWR from "swr";
import { apiFetch } from "@/lib/api";
import type { AgentRun, ToolHint } from "@/types";

// List all runs
export function useAgentRuns() {
  return useSWR<AgentRun[]>("/agent/runs", (url: string) =>
    apiFetch<AgentRun[]>(url),
  );
}

// Get single run (poll while running for status updates)
export function useAgentRun(id: string | undefined) {
  return useSWR<AgentRun>(
    id ? `/agent/runs/${id}` : null,
    (url: string) => apiFetch<AgentRun>(url),
    {
      refreshInterval: (data: AgentRun | undefined) =>
        data?.status === "running" ? 1000 : 0,
    },
  );
}

// Start a domain-scoped run
export async function startAgentRun(
  prompt: string,
  domainId?: string,
  toolHints?: ToolHint[],
): Promise<AgentRun> {
  return apiFetch<AgentRun>("/agent/run", {
    method: "POST",
    body: JSON.stringify({
      prompt,
      domain_id: domainId ?? null,
      tool_hints: toolHints ?? [],
    }),
  });
}

// Stop a run
export async function stopAgentRun(runId: string): Promise<void> {
  await apiFetch(`/agent/runs/${runId}/stop`, { method: "POST" });
}
