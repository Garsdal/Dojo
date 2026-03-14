import { useRef, useEffect, useState } from "react";
import { ChevronDown } from "lucide-react";
import { EventText } from "./event-text";
import { EventToolCall } from "./event-tool-call";
import { EventToolResult } from "./event-tool-result";
import { EventError } from "./event-error";
import { EventDone } from "./event-done";
import { parseEventContent } from "@/lib/parse-event";
import type { AgentEvent } from "@/types";

interface EventTimelineProps {
  events: AgentEvent[];
}

export function EventTimeline({ events }: EventTimelineProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [showScrollBtn, setShowScrollBtn] = useState(false);

  const scrollToBottom = () => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [events.length]);

  const handleScroll = () => {
    if (!containerRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = containerRef.current;
    setShowScrollBtn(scrollHeight - scrollTop - clientHeight > 100);
  };

  if (events.length === 0) {
    return (
      <div className="py-12 text-center text-sm text-grey">
        Waiting for agent events…
      </div>
    );
  }

  return (
    <div className="relative">
      <div
        ref={containerRef}
        className="overflow-y-auto pr-2"
        style={{ maxHeight: "calc(100vh - 400px)", minHeight: "300px" }}
        onScroll={handleScroll}
      >
        <div className="space-y-0">
          {events.map((event) => {
            const parsed = parseEventContent(event);

            switch (event.event_type) {
              case "text":
                if (parsed.kind === "text") {
                  return (
                    <EventText
                      key={event.id}
                      text={parsed.text}
                      timestamp={event.timestamp}
                    />
                  );
                }
                return null;

              case "tool_call":
                if (parsed.kind === "code" || parsed.kind === "json" || parsed.kind === "structured") {
                  return (
                    <EventToolCall
                      key={event.id}
                      toolName={String(event.data.tool ?? "unknown")}
                      content={parsed}
                      timestamp={event.timestamp}
                    />
                  );
                }
                return null;

              case "tool_result":
                if (parsed.kind === "text" || parsed.kind === "code" || parsed.kind === "json") {
                  return (
                    <EventToolResult
                      key={event.id}
                      content={parsed}
                      timestamp={event.timestamp}
                    />
                  );
                }
                return null;

              case "error":
                if (parsed.kind === "error") {
                  return (
                    <EventError
                      key={event.id}
                      message={parsed.message}
                      trace={parsed.trace}
                      timestamp={event.timestamp}
                    />
                  );
                }
                return null;

              case "result":
                return (
                  <EventDone
                    key={event.id}
                    turns={Number(event.data.turns ?? 0)}
                    costUsd={event.data.cost_usd != null ? Number(event.data.cost_usd) : null}
                    summary={event.data.summary ? String(event.data.summary) : undefined}
                    timestamp={event.timestamp}
                  />
                );

              default:
                // Unknown event types - show as text
                return (
                  <EventText
                    key={event.id}
                    text={`[${event.event_type}] ${JSON.stringify(event.data)}`}
                    timestamp={event.timestamp}
                  />
                );
            }
          })}
        </div>
        <div ref={bottomRef} />
      </div>

      {/* Scroll to bottom button */}
      {showScrollBtn && (
        <button
          onClick={scrollToBottom}
          className="absolute bottom-2 right-2 bg-white border border-soft-fawn/30 rounded-full p-1.5 shadow-sm text-grey hover:text-blackberry transition-colors"
        >
          <ChevronDown className="h-4 w-4" />
        </button>
      )}
    </div>
  );
}
