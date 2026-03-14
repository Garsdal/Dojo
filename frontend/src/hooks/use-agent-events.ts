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

  // Throttled revalidation: at most once every 2s, so rapid events don't spam fetches
  const lastRevalidateRef = useRef(0);
  const pendingTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const doRevalidate = useCallback(() => {
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
    lastRevalidateRef.current = Date.now();
  }, []);

  const revalidate = useCallback(
    (immediate?: boolean) => {
      if (immediate) {
        if (pendingTimerRef.current) clearTimeout(pendingTimerRef.current);
        doRevalidate();
        return;
      }
      const elapsed = Date.now() - lastRevalidateRef.current;
      if (elapsed >= 2000) {
        doRevalidate();
      } else if (!pendingTimerRef.current) {
        pendingTimerRef.current = setTimeout(() => {
          pendingTimerRef.current = null;
          doRevalidate();
        }, 2000 - elapsed);
      }
    },
    [doRevalidate],
  );

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

    // Revalidate on every tool_result (data may have changed on server)
    const handleToolResult = (e: MessageEvent) => {
      handleEvent(e);
      revalidate();
    };

    es.addEventListener("tool_call", handleEvent);
    es.addEventListener("tool_result", handleToolResult);
    es.addEventListener("text", handleEvent);
    es.addEventListener("error", handleEvent);
    es.addEventListener("result", (e: MessageEvent) => {
      handleEvent(e);
      // result event means the run finished — immediately revalidate
      revalidate(true);
    });
    es.addEventListener("done", () => {
      setDone(true);
      revalidate(true);
      es.close();
    });
    es.onerror = () => {
      setDone(true);
      es.close();
    };

    return () => {
      es.close();
      if (pendingTimerRef.current) clearTimeout(pendingTimerRef.current);
    };
  }, [runId, revalidate]);

  return { events, done };
}
