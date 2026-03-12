import { CheckCircle2 } from "lucide-react";

interface EventDoneProps {
  turns: number;
  costUsd: number | null;
  summary?: string;
  timestamp?: string;
}

export function EventDone({ turns, costUsd, summary, timestamp }: EventDoneProps) {
  return (
    <div className="flex gap-3 animate-slide-in">
      <div className="flex flex-col items-center pt-0.5">
        <div className="h-5 w-5 rounded-full bg-muted-teal border-2 border-muted-teal flex items-center justify-center shrink-0">
          <CheckCircle2 className="h-3 w-3 text-white" />
        </div>
      </div>

      <div className="flex-1 pb-4 min-w-0">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-semibold bg-muted-teal/20 text-muted-teal rounded-full px-2.5 py-0.5 flex items-center gap-1">
            <CheckCircle2 className="h-2.5 w-2.5" />
            DONE
          </span>
          {timestamp && (
            <span className="text-xs text-grey">{new Date(timestamp).toLocaleTimeString()}</span>
          )}
        </div>

        <div className="bg-muted-teal/10 border border-muted-teal/20 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-3">
            <CheckCircle2 className="h-4 w-4 text-muted-teal" />
            <span className="text-sm font-semibold text-blackberry">Research Complete</span>
          </div>
          <div className="flex items-center gap-4 text-xs text-grey">
            <span>{turns} turn{turns !== 1 ? "s" : ""}</span>
            {costUsd != null && <span>${costUsd.toFixed(4)} cost</span>}
          </div>
          {summary && (
            <p className="mt-3 text-sm text-blackberry border-t border-muted-teal/20 pt-3">
              {summary}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
