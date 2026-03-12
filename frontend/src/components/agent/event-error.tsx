import { useState } from "react";
import { AlertTriangle, ChevronDown, ChevronUp } from "lucide-react";

interface EventErrorProps {
  message: string;
  trace?: string;
  timestamp?: string;
}

export function EventError({ message, trace, timestamp }: EventErrorProps) {
  const [showTrace, setShowTrace] = useState(false);

  return (
    <div className="flex gap-3 animate-slide-in">
      <div className="flex flex-col items-center pt-0.5">
        <div className="h-5 w-5 rounded-full bg-danger/15 border-2 border-danger/40 flex items-center justify-center shrink-0">
          <AlertTriangle className="h-2.5 w-2.5 text-danger" />
        </div>
        <div className="w-px flex-1 bg-soft-fawn/30 mt-1" />
      </div>

      <div className="flex-1 pb-4 min-w-0">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-semibold bg-danger/15 text-danger rounded-full px-2.5 py-0.5 flex items-center gap-1">
            <AlertTriangle className="h-2.5 w-2.5" />
            ERROR
          </span>
          {timestamp && (
            <span className="text-xs text-grey">{new Date(timestamp).toLocaleTimeString()}</span>
          )}
        </div>

        <div className="bg-danger/5 border border-danger/20 rounded-lg p-3">
          <pre className="text-xs text-danger whitespace-pre-wrap break-words font-mono">{message}</pre>
          {trace && (
            <>
              <button
                onClick={() => setShowTrace(!showTrace)}
                className="mt-2 text-xs text-danger/70 hover:text-danger flex items-center gap-0.5 transition-colors"
              >
                {showTrace ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                {showTrace ? "Hide" : "Show"} stack trace
              </button>
              {showTrace && (
                <pre className="mt-2 text-xs text-danger/70 whitespace-pre-wrap break-words font-mono border-t border-danger/20 pt-2">
                  {trace}
                </pre>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
