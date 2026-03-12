import { useState } from "react";
import { CheckCircle, ChevronDown, ChevronUp } from "lucide-react";
import SyntaxHighlighter from "react-syntax-highlighter";
import { atomOneLight } from "react-syntax-highlighter/dist/cjs/styles/hljs";

interface EventToolResultProps {
  content: { kind: "text"; text: string } | { kind: "code"; code: string; language: string } | { kind: "json"; json: unknown };
  timestamp?: string;
}

export function EventToolResult({ content, timestamp }: EventToolResultProps) {
  const [collapsed, setCollapsed] = useState(false);

  const textContent =
    content.kind === "text"
      ? content.text
      : content.kind === "code"
        ? content.code
        : JSON.stringify(content.json, null, 2);

  const isCode = content.kind === "code" || content.kind === "json";
  const language = content.kind === "code" ? content.language : content.kind === "json" ? "json" : "text";
  const lines = textContent.split("\n");
  const isLong = lines.length > 10;

  return (
    <div className="flex gap-3 animate-slide-in">
      <div className="flex flex-col items-center pt-0.5">
        <div className="h-5 w-5 rounded-full bg-muted-teal/20 border-2 border-muted-teal/50 flex items-center justify-center shrink-0">
          <CheckCircle className="h-2.5 w-2.5 text-muted-teal" />
        </div>
        <div className="w-px flex-1 bg-soft-fawn/30 mt-1" />
      </div>

      <div className="flex-1 pb-4 min-w-0">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-semibold bg-muted-teal/20 text-muted-teal rounded-full px-2.5 py-0.5 flex items-center gap-1">
            <CheckCircle className="h-2.5 w-2.5" />
            RESULT
          </span>
          <div className="flex items-center gap-2">
            {isLong && (
              <button
                onClick={() => setCollapsed(!collapsed)}
                className="text-xs text-grey hover:text-blackberry flex items-center gap-0.5 transition-colors"
              >
                {collapsed ? <ChevronDown className="h-3 w-3" /> : <ChevronUp className="h-3 w-3" />}
                {collapsed ? "Show" : "Collapse"}
              </button>
            )}
            {timestamp && <span className="text-xs text-grey">{new Date(timestamp).toLocaleTimeString()}</span>}
          </div>
        </div>

        {!collapsed && (
          <div className="bg-muted-teal/5 border border-muted-teal/15 rounded-lg p-3 overflow-hidden">
            {isCode ? (
              <SyntaxHighlighter
                language={language}
                style={atomOneLight}
                customStyle={{ margin: 0, background: "transparent", fontSize: "0.75rem", padding: 0 }}
              >
                {textContent}
              </SyntaxHighlighter>
            ) : (
              <pre className="text-xs text-blackberry whitespace-pre-wrap break-words font-mono">{textContent}</pre>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
