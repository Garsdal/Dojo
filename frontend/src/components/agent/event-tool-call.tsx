import { useState } from "react";
import { Wrench, Copy, Check, ChevronDown, ChevronUp } from "lucide-react";
import SyntaxHighlighter from "react-syntax-highlighter";
import { atomOneLight } from "react-syntax-highlighter/dist/cjs/styles/hljs";

interface EventToolCallProps {
  toolName: string;
  content: { kind: "code"; code: string; language: string } | { kind: "json"; json: unknown };
  timestamp?: string;
}

export function EventToolCall({ toolName, content, timestamp }: EventToolCallProps) {
  const [copied, setCopied] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

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
            <span className="text-xs font-semibold bg-blackberry/15 text-blackberry rounded-full px-2.5 py-0.5 flex items-center gap-1">
              <Wrench className="h-2.5 w-2.5" />
              TOOL
            </span>
            <code className="text-sm font-mono font-semibold text-blackberry">{toolName}</code>
          </div>
          {timestamp && (
            <span className="text-xs text-grey">{new Date(timestamp).toLocaleTimeString()}</span>
          )}
        </div>

        {/* Code block */}
        <div className="rounded-lg overflow-hidden border border-soft-fawn/20">
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
            <div className="text-xs" style={{ maxHeight: isLong ? "none" : undefined }}>
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
