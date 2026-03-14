import { StateBadge } from "@/components/state-badge";
import { Button } from "@/components/ui/button";
import { EventTimeline } from "@/components/agent/event-timeline";
import { useAgentRun } from "@/hooks/use-agent";
import { useAgentEvents } from "@/hooks/use-agent-events";
import { stopAgentRun } from "@/hooks/use-agent";
import { Square } from "lucide-react";

interface AgentRunViewProps {
  runId: string;
}

export function AgentRunView({ runId }: AgentRunViewProps) {
  const { data: run, mutate } = useAgentRun(runId);
  const { events } = useAgentEvents(runId);

  if (!run) {
    return (
      <div className="py-8 text-center text-sm text-grey">Loading run…</div>
    );
  }

  const isRunning = run.status === "running";
  const displayEvents = events.length > 0 ? events : run.events;

  const handleStop = async () => {
    await stopAgentRun(runId);
    void mutate();
  };

  return (
    <div className="flex flex-col gap-3">
      {/* Status bar */}
      <div className="flex items-center justify-between px-1">
        <div className="flex items-center gap-2">
          <StateBadge state={run.status} />
          {run.num_turns > 0 && (
            <span className="text-xs text-grey">
              {run.num_turns} turn{run.num_turns !== 1 ? "s" : ""}
              {run.total_cost_usd != null &&
                ` · $${run.total_cost_usd.toFixed(4)}`}
            </span>
          )}
        </div>
        {isRunning && (
          <Button variant="destructive" size="sm" onClick={handleStop}>
            <Square className="h-3 w-3" />
            Stop
          </Button>
        )}
      </div>

      {/* Prompt display */}
      <div className="bg-wheat/10 rounded-xl border border-soft-fawn/20 px-4 py-3">
        <div className="text-xs text-grey mb-1">Prompt</div>
        <p className="text-sm text-blackberry">{run.prompt}</p>
      </div>

      {/* Event timeline */}
      <EventTimeline events={displayEvents} />

      {/* Error display */}
      {run.error && (
        <div className="bg-danger/5 border border-danger/20 rounded-xl px-4 py-3">
          <div className="text-xs text-danger font-semibold mb-1">
            Run Error
          </div>
          <pre className="text-xs text-danger font-mono whitespace-pre-wrap">
            {run.error}
          </pre>
        </div>
      )}
    </div>
  );
}
