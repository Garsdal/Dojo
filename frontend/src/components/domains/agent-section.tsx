import { useState } from "react";
import { AgentPromptForm } from "@/components/agent/agent-prompt-form";
import { AgentRunView } from "@/components/agent/agent-run-view";
import { startAgentRun, useAgentRuns } from "@/hooks/use-agent";
import { StateBadge } from "@/components/state-badge";
import { Button } from "@/components/ui/button";
import { Plus } from "lucide-react";
import type { ToolHint } from "@/types";

interface AgentSectionProps {
  domainId: string;
}

export function AgentSection({ domainId }: AgentSectionProps) {
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [isStarting, setIsStarting] = useState(false);
  const { data: runs } = useAgentRuns();

  const domainRuns = runs?.filter((r) => r.domain_id === domainId) ?? [];

  const handleStart = async (prompt: string, toolHints: ToolHint[]) => {
    setIsStarting(true);
    try {
      const run = await startAgentRun(prompt, domainId, toolHints);
      setActiveRunId(run.id);
    } finally {
      setIsStarting(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Prompt form (shown when no active run) */}
      {!activeRunId && (
        <AgentPromptForm onSubmit={handleStart} isLoading={isStarting} />
      )}

      {/* New research button when viewing a run */}
      {activeRunId && (
        <div className="flex items-center justify-between">
          <span className="text-xs text-grey">Current run</span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setActiveRunId(null)}
          >
            <Plus className="h-3.5 w-3.5" />
            New Research
          </Button>
        </div>
      )}

      {/* Run view */}
      {activeRunId && <AgentRunView runId={activeRunId} />}

      {/* Previous runs */}
      {domainRuns.length > 0 && (
        <div className="mt-4 pt-6 border-t border-soft-fawn/20">
          <h3 className="text-xs font-semibold text-grey uppercase tracking-wide mb-3 px-1">
            Previous Runs
          </h3>
          <div className="space-y-2">
            {domainRuns
              .filter((r) => r.id !== activeRunId)
              .map((run) => (
                <button
                  key={run.id}
                  onClick={() => setActiveRunId(run.id)}
                  className="w-full rounded-xl border border-soft-fawn/20 bg-white px-4 py-3 text-left hover:bg-wheat/5 hover:border-soft-fawn/40 transition-all group"
                >
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span className="truncate text-sm font-medium text-blackberry group-hover:text-blackberry/80">
                      {run.prompt}
                    </span>
                    <StateBadge state={run.status} />
                  </div>
                  <div className="flex items-center gap-3 text-xs text-grey">
                    <span>
                      {run.num_turns} turn{run.num_turns !== 1 ? "s" : ""}
                    </span>
                    {run.total_cost_usd != null && (
                      <span>${run.total_cost_usd.toFixed(4)}</span>
                    )}
                    {run.completed_at && (
                      <span>
                        {new Date(run.completed_at).toLocaleDateString()}
                      </span>
                    )}
                  </div>
                </button>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}
