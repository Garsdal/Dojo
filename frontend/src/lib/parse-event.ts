import type { AgentEvent } from "@/types";

export type ContentType =
  | { kind: "text"; text: string }
  | { kind: "code"; code: string; language: string }
  | { kind: "json"; json: unknown }
  | { kind: "error"; message: string; trace?: string };

function detectLanguage(toolName: string): string {
  const lowerName = toolName.toLowerCase();
  if (lowerName.includes("python") || lowerName.includes("execute_code")) return "python";
  if (lowerName.includes("sql")) return "sql";
  if (lowerName.includes("bash") || lowerName.includes("shell")) return "bash";
  if (lowerName.includes("js") || lowerName.includes("javascript")) return "javascript";
  return "python"; // default for ML tools
}

export function parseEventContent(event: AgentEvent): ContentType {
  const d = event.data;

  switch (event.event_type) {
    case "text": {
      return { kind: "text", text: String(d.text ?? "") };
    }
    case "tool_call": {
      const input = d.input;
      const toolName = String(d.tool ?? "unknown");
      // Check if input has a "code" field
      if (input && typeof input === "object" && "code" in input) {
        return {
          kind: "code",
          code: String((input as Record<string, unknown>).code ?? ""),
          language: detectLanguage(toolName),
        };
      }
      // Otherwise it's JSON
      return { kind: "json", json: input ?? d };
    }
    case "tool_result": {
      const content = String(d.content ?? "");
      // If content looks like code or data (has newlines and code-like patterns)
      const looksLikeCode = /^(import |def |class |SELECT |CREATE |#!|from )/.test(content.trimStart());
      if (looksLikeCode) {
        return { kind: "code", code: content, language: "python" };
      }
      // Check if parseable JSON
      try {
        const parsed = JSON.parse(content);
        return { kind: "json", json: parsed };
      } catch {
        return { kind: "text", text: content };
      }
    }
    case "error": {
      return {
        kind: "error",
        message: String(d.error ?? "Unknown error"),
        trace: d.traceback ? String(d.traceback) : undefined,
      };
    }
    default:
      return { kind: "text", text: JSON.stringify(d, null, 2) };
  }
}
