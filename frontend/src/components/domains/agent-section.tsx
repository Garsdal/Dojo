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
    <div className="space-y-4">
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
      {activeRunId && (
        <AgentRunView runId={activeRunId} onStop={() => setActiveRunId(null)} />
      )}

      {/* Prompt form (shown when no active run OR after run completed) */}
      {!activeRunId && (
        <AgentPromptForm onSubmit={handleStart} isLoading={isStarting} />
      )}

      {/* Previous runs */}
      {domainRuns.length > 0 && (
        <div className="mt-2">
          <h3 className="text-xs font-semibold text-grey uppercase tracking-wide mb-2 px-1">
            Previous Runs
          </h3>
          <div className="space-y-1.5">
            {domainRuns
              .filter((r) => r.id !== activeRunId)
              .map((run) => (
                <button
                  key={run.id}
                  onClick={() => setActiveRunId(run.id)}
                  className="w-full flex items-center justify-between rounded-xl border border-soft-fawn/20 bg-white px-4 py-2.5 text-left text-sm hover:bg-wheat/5 hover:border-soft-fawn/40 transition-all"
                >
                  <span className="truncate max-w-[60%] text-blackberry text-sm">{run.prompt}</span>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-xs text-grey">{run.num_turns} turns</span>
                    <StateBadge state={run.status} />
                  </div>
                </button>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}
