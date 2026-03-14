import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AgentPromptForm } from "@/components/agent/agent-prompt-form";
import { AgentRunView } from "@/components/agent/agent-run-view";
import { startAgentRun } from "@/hooks/use-agent";
import { useAgentRuns } from "@/hooks/use-agent";
import { StateBadge } from "@/components/state-badge";
import { Button } from "@/components/ui/button";
import { Plus } from "lucide-react";
import type { ToolHint } from "@/types";

export default function AgentPage() {
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [isStarting, setIsStarting] = useState(false);
  const { data: runs } = useAgentRuns();

  const handleStart = async (prompt: string, toolHints: ToolHint[]) => {
    setIsStarting(true);
    try {
      const run = await startAgentRun(prompt, undefined, toolHints);
      setActiveRunId(run.id);
    } finally {
      setIsStarting(false);
    }
  };

  return (
    <div className="space-y-6 max-w-3xl mx-auto">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Agent Research</h1>
        <p className="text-muted-foreground text-sm mt-1">
          Start an AI-driven ML research session
        </p>
      </div>

      {/* Prompt form */}
      {!activeRunId && (
        <Card className="rounded-xl">
          <CardHeader>
            <CardTitle className="text-sm font-medium text-muted-foreground">
              New Research Session
            </CardTitle>
          </CardHeader>
          <CardContent>
            <AgentPromptForm onSubmit={handleStart} isLoading={isStarting} />
          </CardContent>
        </Card>
      )}

      {/* Active run view */}
      {activeRunId && (
        <>
          <div className="flex items-center justify-between px-1">
            <span className="text-xs text-muted-foreground">Current run</span>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setActiveRunId(null)}
            >
              <Plus className="h-3.5 w-3.5" />
              New Research
            </Button>
          </div>
          <AgentRunView runId={activeRunId} />
        </>
      )}

      {/* Previous runs list */}
      {runs && runs.length > 0 && (
        <div className="mt-4 pt-6 border-t border-soft-fawn/20">
          <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-3 px-1">
            Previous Runs
          </h3>
          <div className="space-y-2">
            {runs
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
                  <div className="flex items-center gap-3 text-xs text-muted-foreground">
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
