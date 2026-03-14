import type { AgentEvent } from "@/types";

export type ToolCategory = "exec" | "file" | "web" | "data" | "tool";

export type ContentType =
  | { kind: "text"; text: string }
  | { kind: "code"; code: string; language: string }
  | { kind: "json"; json: unknown }
  | {
      kind: "structured";
      category: ToolCategory;
      label?: string;
      primary?: { value: string; isCode: boolean; language?: string };
      meta: Array<{ key: string; value: string }>;
    }
  | { kind: "error"; message: string; trace?: string };

interface ToolTemplate {
  /** Field whose value is shown as a context label above the primary content */
  labelField?: string;
  /** Field whose value is the main content (code block or prominent text) */
  primaryField: string | null;
  /** Whether primary should be syntax-highlighted */
  isCode: boolean;
  /** Explicit language; if unset and isCode, inferred from labelField (file path) */
  language?: string;
  /** Additional fields shown as key: value chips */
  metaFields: string[];
  category: ToolCategory;
}

const TOOL_TEMPLATES: Record<string, ToolTemplate> = {
  // Claude built-in tools
  Bash: {
    labelField: "description",
    primaryField: "command",
    isCode: true,
    language: "bash",
    metaFields: [],
    category: "exec",
  },
  Read: {
    primaryField: "file_path",
    isCode: false,
    metaFields: ["offset", "limit"],
    category: "file",
  },
  Write: {
    labelField: "file_path",
    primaryField: "content",
    isCode: true,
    metaFields: [],
    category: "file",
  },
  Edit: {
    labelField: "file_path",
    primaryField: "new_string",
    isCode: true,
    metaFields: ["old_string"],
    category: "file",
  },
  WebFetch: {
    primaryField: "url",
    isCode: false,
    metaFields: ["prompt"],
    category: "web",
  },
  // AgentML tools (matched after stripping mcp__<server>__ prefix)
  create_experiment: {
    primaryField: "hypothesis",
    isCode: false,
    metaFields: ["domain_id", "variables"],
    category: "data",
  },
  complete_experiment: {
    primaryField: "metrics",
    isCode: false,
    metaFields: ["experiment_id"],
    category: "data",
  },
  fail_experiment: {
    primaryField: "error",
    isCode: false,
    metaFields: ["experiment_id"],
    category: "data",
  },
  get_experiment: {
    primaryField: "experiment_id",
    isCode: false,
    metaFields: [],
    category: "data",
  },
  list_experiments: {
    primaryField: null,
    isCode: false,
    metaFields: ["domain_id"],
    category: "data",
  },
  compare_experiments: {
    primaryField: "experiment_ids",
    isCode: false,
    metaFields: [],
    category: "data",
  },
  write_knowledge: {
    labelField: "context",
    primaryField: "claim",
    isCode: false,
    metaFields: ["action", "confidence", "domain_id", "experiment_id"],
    category: "data",
  },
  search_knowledge: {
    primaryField: "query",
    isCode: false,
    metaFields: ["limit", "domain_id"],
    category: "data",
  },
  list_knowledge: {
    primaryField: null,
    isCode: false,
    metaFields: ["domain_id"],
    category: "data",
  },
};

function stripMcpPrefix(toolName: string): string {
  const match = toolName.match(/^mcp__[^_]+__(.+)$/);
  return match ? match[1] : toolName;
}

function languageFromPath(filePath: string): string {
  if (filePath.endsWith(".py")) return "python";
  if (filePath.endsWith(".ts") || filePath.endsWith(".tsx")) return "typescript";
  if (filePath.endsWith(".js") || filePath.endsWith(".jsx")) return "javascript";
  if (filePath.endsWith(".json")) return "json";
  if (filePath.endsWith(".sh")) return "bash";
  if (filePath.endsWith(".sql")) return "sql";
  if (filePath.endsWith(".md")) return "markdown";
  if (filePath.endsWith(".css")) return "css";
  if (filePath.endsWith(".html") || filePath.endsWith(".htm")) return "html";
  return "text";
}

function formatMetaValue(value: unknown, truncate = 80): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") {
    return value.length > truncate ? value.slice(0, truncate) + "…" : value;
  }
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  const json = JSON.stringify(value);
  return json.length > truncate ? json.slice(0, truncate) + "…" : json;
}

function detectLanguage(toolName: string): string {
  const n = toolName.toLowerCase();
  if (n.includes("python") || n.includes("execute_code")) return "python";
  if (n.includes("sql")) return "sql";
  if (n.includes("bash") || n.includes("shell")) return "bash";
  if (n.includes("js") || n.includes("javascript")) return "javascript";
  return "python";
}

export function parseEventContent(event: AgentEvent): ContentType {
  const d = event.data;

  switch (event.event_type) {
    case "text": {
      return { kind: "text", text: String(d.text ?? "") };
    }

    case "tool_call": {
      const rawName = String(d.tool ?? "unknown");
      const toolName = stripMcpPrefix(rawName);
      const input = d.input as Record<string, unknown> | undefined;
      const template = TOOL_TEMPLATES[toolName];

      if (template && input) {
        const labelVal = template.labelField ? input[template.labelField] : undefined;
        const label = labelVal != null ? formatMetaValue(labelVal, 200) : undefined;

        let primary: { value: string; isCode: boolean; language?: string } | undefined;
        if (template.primaryField) {
          const rawVal = input[template.primaryField];
          if (rawVal != null) {
            const value =
              typeof rawVal === "string" ? rawVal : JSON.stringify(rawVal, null, 2);
            let language = template.language;
            if (template.isCode && !language && template.labelField) {
              const fp = input[template.labelField];
              if (typeof fp === "string") language = languageFromPath(fp);
            }
            primary = { value, isCode: template.isCode, language };
          }
        }

        const meta: Array<{ key: string; value: string }> = [];
        for (const field of template.metaFields) {
          const val = input[field];
          if (val != null && val !== "") {
            const formatted = formatMetaValue(val);
            if (formatted) meta.push({ key: field, value: formatted });
          }
        }

        return { kind: "structured", category: template.category, label, primary, meta };
      }

      // Fallback for unknown tools
      if (input && typeof input === "object" && "code" in input) {
        return {
          kind: "code",
          code: String((input as Record<string, unknown>).code ?? ""),
          language: detectLanguage(toolName),
        };
      }
      return { kind: "json", json: input ?? d };
    }

    case "tool_result": {
      const content = String(d.content ?? "");
      const looksLikeCode = /^(import |def |class |SELECT |CREATE |#!|from )/.test(
        content.trimStart(),
      );
      if (looksLikeCode) {
        return { kind: "code", code: content, language: "python" };
      }
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
