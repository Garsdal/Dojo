import { useState } from "react";
import ReactMarkdown from "react-markdown";

interface EventTextProps {
  text: string;
  timestamp?: string;
}

export function EventText({ text, timestamp }: EventTextProps) {
  const [expanded, setExpanded] = useState(false);
  const lines = text.split("\n");
  const isLong = lines.length > 6;
  const displayText = isLong && !expanded ? lines.slice(0, 6).join("\n") + "…" : text;

  return (
    <div className="flex gap-3 animate-slide-in">
      {/* Timeline dot */}
      <div className="flex flex-col items-center pt-0.5">
        <div className="h-5 w-5 rounded-full bg-wheat/30 border-2 border-wheat flex items-center justify-center shrink-0">
          <span className="text-[8px] font-bold text-blackberry">T</span>
        </div>
        <div className="w-px flex-1 bg-soft-fawn/30 mt-1" />
      </div>

      <div className="flex-1 pb-4 min-w-0">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-semibold bg-wheat/20 text-blackberry rounded-full px-2.5 py-0.5">
            TEXT
          </span>
          {timestamp && (
            <span className="text-xs text-grey">{new Date(timestamp).toLocaleTimeString()}</span>
          )}
        </div>
        <div className="border-l-2 border-wheat pl-3">
          <div className="text-sm text-blackberry prose prose-sm max-w-none [&>p]:my-1 [&>ul]:my-1 [&>ol]:my-1">
            <ReactMarkdown>{displayText}</ReactMarkdown>
          </div>
          {isLong && (
            <button
              onClick={() => setExpanded(!expanded)}
              className="mt-1 text-xs text-grey hover:text-blackberry transition-colors"
            >
              {expanded ? "Show less" : "Show more"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
