import { useState, useEffect, useRef, useCallback } from "react";
import { useSWRConfig } from "swr";
import type { AgentEvent } from "@/types";

const API_BASE = import.meta.env.VITE_API_URL ?? "";

export function useAgentEvents(runId: string | undefined) {
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [done, setDone] = useState(false);
  const esRef = useRef<EventSource | null>(null);
  const { mutate } = useSWRConfig();
  // Keep mutate in a ref so the SSE closures always use the latest reference
  const mutateRef = useRef(mutate);
  mutateRef.current = mutate;

  const revalidate = useCallback(() => {
    void mutateRef.current(
      (key) =>
        typeof key === "string" &&
        (key.startsWith("/experiments") ||
          key.startsWith("/domains") ||
          key.startsWith("/knowledge") ||
          key.startsWith("/agent")),
      undefined,
      { revalidate: true },
    );
  }, []);

  useEffect(() => {
    if (!runId) return;

    setEvents([]);
    setDone(false);

    const es = new EventSource(`${API_BASE}/agent/runs/${runId}/events`);
    esRef.current = es;

    const handleEvent = (e: MessageEvent) => {
      try {
        const parsed = JSON.parse(e.data) as AgentEvent;
        setEvents((prev) => [...prev, parsed]);
      } catch {
        // Ignore malformed events
      }
    };

    const handleToolResult = (e: MessageEvent) => {
      handleEvent(e);
      revalidate();
    };

    es.addEventListener("tool_call", handleEvent);
    es.addEventListener("tool_result", handleToolResult);
    es.addEventListener("text", handleEvent);
    es.addEventListener("error", handleEvent);
    es.addEventListener("result", handleEvent);
    es.addEventListener("done", () => {
      setDone(true);
      revalidate();
      es.close();
    });
    es.onerror = () => {
      setDone(true);
      es.close();
    };

    return () => es.close();
  }, [runId, revalidate]);

  return { events, done };
}
