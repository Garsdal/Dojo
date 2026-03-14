import { useState } from "react";
import { Wrench, Copy, Check, ChevronDown, ChevronUp, Terminal, FileText, Globe, Database } from "lucide-react";
import SyntaxHighlighter from "react-syntax-highlighter";
import { atomOneLight } from "react-syntax-highlighter/dist/cjs/styles/hljs";
import type { ContentType, ToolCategory } from "@/lib/parse-event";

interface EventToolCallProps {
  toolName: string;
  content: Extract<ContentType, { kind: "code" | "json" | "structured" }>;
  timestamp?: string;
}

// --- Structured rendering ---

const CATEGORY_CONFIG: Record<
  ToolCategory,
  {
    dotBg: string;
    dotBorder: string;
    iconColor: string;
    badgeBg: string;
    badgeText: string;
    label: string;
    Icon: React.ElementType;
  }
> = {
  exec: {
    dotBg: "bg-muted-teal/20",
    dotBorder: "border-muted-teal/50",
    iconColor: "text-muted-teal",
    badgeBg: "bg-muted-teal/15",
    badgeText: "text-muted-teal",
    label: "EXEC",
    Icon: Terminal,
  },
  file: {
    dotBg: "bg-soft-fawn/20",
    dotBorder: "border-soft-fawn/60",
    iconColor: "text-grey",
    badgeBg: "bg-soft-fawn/20",
    badgeText: "text-blackberry",
    label: "FILE",
    Icon: FileText,
  },
  web: {
    dotBg: "bg-blackberry/10",
    dotBorder: "border-blackberry/30",
    iconColor: "text-blackberry",
    badgeBg: "bg-blackberry/10",
    badgeText: "text-blackberry",
    label: "WEB",
    Icon: Globe,
  },
  data: {
    dotBg: "bg-wheat/40",
    dotBorder: "border-soft-fawn/50",
    iconColor: "text-blackberry",
    badgeBg: "bg-wheat/30",
    badgeText: "text-blackberry",
    label: "DATA",
    Icon: Database,
  },
  tool: {
    dotBg: "bg-blackberry/10",
    dotBorder: "border-blackberry/30",
    iconColor: "text-blackberry",
    badgeBg: "bg-blackberry/15",
    badgeText: "text-blackberry",
    label: "TOOL",
    Icon: Wrench,
  },
};

function displayName(toolName: string): string {
  return toolName.replace(/^mcp__[^_]+__/, "");
}

interface StructuredToolCallProps {
  toolName: string;
  content: Extract<ContentType, { kind: "structured" }>;
  timestamp?: string;
}

function StructuredToolCall({ toolName, content, timestamp }: StructuredToolCallProps) {
  const [copied, setCopied] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  const cfg = CATEGORY_CONFIG[content.category];
  const name = displayName(toolName);
  const isLong = content.primary?.isCode && (content.primary.value.split("\n").length > 12);

  const handleCopy = () => {
    if (content.primary) {
      navigator.clipboard.writeText(content.primary.value);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <div className="flex gap-3 animate-slide-in">
      <div className="flex flex-col items-center pt-0.5">
        <div className={`h-5 w-5 rounded-full ${cfg.dotBg} border-2 ${cfg.dotBorder} flex items-center justify-center shrink-0`}>
          <cfg.Icon className={`h-2.5 w-2.5 ${cfg.iconColor}`} />
        </div>
        <div className="w-px flex-1 bg-soft-fawn/30 mt-1" />
      </div>

      <div className="flex-1 pb-4 min-w-0">
        {/* Header */}
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <span className={`text-xs font-semibold ${cfg.badgeBg} ${cfg.badgeText} rounded-sm px-2 py-0.5 flex items-center gap-1`}>
              <cfg.Icon className="h-2.5 w-2.5" />
              {cfg.label}
            </span>
            <code className="text-sm font-mono font-semibold text-blackberry">{name}</code>
          </div>
          {timestamp && (
            <span className="text-xs text-grey">{new Date(timestamp).toLocaleTimeString()}</span>
          )}
        </div>

        {/* Label (description, file path, context, etc.) */}
        {content.label && (
          <p className="text-xs text-grey mb-2 font-mono truncate" title={content.label}>
            {content.label}
          </p>
        )}

        {/* Primary content */}
        {content.primary && (
          content.primary.isCode ? (
            <div className="rounded-md overflow-hidden border border-soft-fawn/20 mb-2">
              <div className="flex items-center justify-between bg-blackberry/5 px-3 py-1 border-b border-soft-fawn/20">
                <span className="text-xs text-grey font-mono">{content.primary.language ?? "text"}</span>
                <div className="flex items-center gap-2">
                  {isLong && (
                    <button
                      onClick={() => setCollapsed(!collapsed)}
                      className="text-xs text-grey hover:text-blackberry flex items-center gap-0.5 transition-colors"
                    >
                      {collapsed ? <ChevronDown className="h-3 w-3" /> : <ChevronUp className="h-3 w-3" />}
                      {collapsed ? "Expand" : "Collapse"}
                    </button>
                  )}
                  <button
                    onClick={handleCopy}
                    className="text-xs text-grey hover:text-blackberry flex items-center gap-0.5 transition-colors"
                  >
                    {copied ? <Check className="h-3 w-3 text-muted-teal" /> : <Copy className="h-3 w-3" />}
                    {copied ? "Copied!" : "Copy"}
                  </button>
                </div>
              </div>
              {!collapsed && (
                <SyntaxHighlighter
                  language={content.primary.language ?? "text"}
                  style={atomOneLight}
                  customStyle={{ margin: 0, background: "transparent", fontSize: "0.75rem", padding: "0.75rem" }}
                >
                  {content.primary.value}
                </SyntaxHighlighter>
              )}
            </div>
          ) : (
            <p className="text-sm text-blackberry font-mono bg-blackberry/5 rounded-sm px-2 py-1 mb-2 break-all">
              {content.primary.value}
            </p>
          )
        )}

        {/* Meta key: value chips */}
        {content.meta.length > 0 && (
          <div className="flex flex-wrap gap-x-4 gap-y-0.5 mt-1">
            {content.meta.map(({ key, value }) => (
              <span key={key} className="text-xs text-grey">
                <span className="text-blackberry/50 font-medium">{key}:</span>{" "}
                <span className="font-mono">{value}</span>
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// --- Generic (fallback) rendering ---

export function EventToolCall({ toolName, content, timestamp }: EventToolCallProps) {
  const [copied, setCopied] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  if (content.kind === "structured") {
    return <StructuredToolCall toolName={toolName} content={content} timestamp={timestamp} />;
  }

  const codeString =
    content.kind === "code"
      ? content.code
      : JSON.stringify(content.json, null, 2);
  const language = content.kind === "code" ? content.language : "json";
  const lines = codeString.split("\n");
  const isLong = lines.length > 12;

  const handleCopy = () => {
    navigator.clipboard.writeText(codeString);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="flex gap-3 animate-slide-in">
      <div className="flex flex-col items-center pt-0.5">
        <div className="h-5 w-5 rounded-full bg-blackberry/10 border-2 border-blackberry/30 flex items-center justify-center shrink-0">
          <Wrench className="h-2.5 w-2.5 text-blackberry" />
        </div>
        <div className="w-px flex-1 bg-soft-fawn/30 mt-1" />
      </div>

      <div className="flex-1 pb-4 min-w-0">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold bg-blackberry/15 text-blackberry rounded-sm px-2.5 py-0.5 flex items-center gap-1">
              <Wrench className="h-2.5 w-2.5" />
              TOOL
            </span>
            <code className="text-sm font-mono font-semibold text-blackberry">{displayName(toolName)}</code>
          </div>
          {timestamp && (
            <span className="text-xs text-grey">{new Date(timestamp).toLocaleTimeString()}</span>
          )}
        </div>

        <div className="rounded-md overflow-hidden border border-soft-fawn/20">
          <div className="flex items-center justify-between bg-blackberry/5 px-3 py-1.5 border-b border-soft-fawn/20">
            <span className="text-xs text-grey font-mono">{language}</span>
            <div className="flex items-center gap-2">
              {isLong && (
                <button
                  onClick={() => setCollapsed(!collapsed)}
                  className="text-xs text-grey hover:text-blackberry flex items-center gap-0.5 transition-colors"
                >
                  {collapsed ? <ChevronDown className="h-3 w-3" /> : <ChevronUp className="h-3 w-3" />}
                  {collapsed ? "Expand" : "Collapse"}
                </button>
              )}
              <button
                onClick={handleCopy}
                className="text-xs text-grey hover:text-blackberry flex items-center gap-0.5 transition-colors"
              >
                {copied ? <Check className="h-3 w-3 text-muted-teal" /> : <Copy className="h-3 w-3" />}
                {copied ? "Copied!" : "Copy"}
              </button>
            </div>
          </div>
          {!collapsed && (
            <div className="text-xs">
              <SyntaxHighlighter
                language={language}
                style={atomOneLight}
                customStyle={{ margin: 0, background: "transparent", fontSize: "0.75rem", padding: "0.75rem" }}
              >
                {codeString}
              </SyntaxHighlighter>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
