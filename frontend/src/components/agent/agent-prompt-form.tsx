import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import type { ToolHint } from "@/types";
import { ArrowUp, Plus, X, ChevronDown, ChevronUp, Square } from "lucide-react";

interface AgentPromptFormProps {
  onSubmit: (prompt: string, toolHints: ToolHint[]) => void;
  onStop?: () => void;
  isLoading?: boolean;
}

export function AgentPromptForm({ onSubmit, onStop, isLoading }: AgentPromptFormProps) {
  const [prompt, setPrompt] = useState("");
  const [toolHints, setToolHints] = useState<ToolHint[]>([]);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showHintForm, setShowHintForm] = useState(false);
  const [hintName, setHintName] = useState("");
  const [hintDescription, setHintDescription] = useState("");
  const [hintSource, setHintSource] = useState("");

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim() || isLoading) return;
    onSubmit(prompt.trim(), toolHints);
    setPrompt("");
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      if (prompt.trim() && !isLoading) {
        onSubmit(prompt.trim(), toolHints);
        setPrompt("");
      }
    }
  };

  const addHint = () => {
    if (!hintName.trim() || !hintDescription.trim()) return;
    setToolHints((prev) => [
      ...prev,
      { name: hintName.trim(), description: hintDescription.trim(), source: hintSource.trim() },
    ]);
    setHintName("");
    setHintDescription("");
    setHintSource("");
    setShowHintForm(false);
  };

  const removeHint = (index: number) => {
    setToolHints((prev) => prev.filter((_, i) => i !== index));
  };

  if (isLoading) {
    return (
      <div className="border-t border-soft-fawn/20 bg-surface p-4">
        <div className="flex items-center justify-between rounded-xl bg-white border border-soft-fawn/20 px-4 py-3">
          <div className="flex items-center gap-2">
            <div className="h-2 w-2 rounded-full bg-muted-teal animate-pulse" />
            <span className="text-sm text-grey">Agent is researching…</span>
          </div>
          {onStop && (
            <Button
              variant="destructive"
              size="sm"
              onClick={onStop}
            >
              <Square className="h-3 w-3" />
              Stop
            </Button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="border-t border-soft-fawn/20 bg-surface p-4 space-y-2">
      {/* Advanced tool hints */}
      <div>
        <button
          type="button"
          onClick={() => setShowAdvanced(!showAdvanced)}
          className="text-xs text-grey hover:text-blackberry flex items-center gap-1 transition-colors"
        >
          {showAdvanced ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          Advanced (tool hints {toolHints.length > 0 ? `· ${toolHints.length}` : ""})
        </button>
        {showAdvanced && (
          <div className="mt-2 space-y-2 p-3 bg-white rounded-xl border border-soft-fawn/20">
            {toolHints.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {toolHints.map((hint, i) => (
                  <div key={i} className="flex items-center gap-1 rounded-full bg-wheat/30 px-2.5 py-0.5 text-xs text-blackberry">
                    <span>{hint.name}</span>
                    <button type="button" onClick={() => removeHint(i)} className="text-grey hover:text-blackberry">
                      <X className="h-2.5 w-2.5" />
                    </button>
                  </div>
                ))}
              </div>
            )}
            {!showHintForm ? (
              <button
                type="button"
                onClick={() => setShowHintForm(true)}
                className="text-xs text-grey hover:text-blackberry flex items-center gap-1 transition-colors"
              >
                <Plus className="h-3 w-3" />
                Add tool hint
              </button>
            ) : (
              <div className="space-y-1.5">
                <Input placeholder="Tool name" value={hintName} onChange={(e) => setHintName(e.target.value)} className="text-xs h-8" />
                <Input placeholder="Description" value={hintDescription} onChange={(e) => setHintDescription(e.target.value)} className="text-xs h-8" />
                <Input placeholder="Source URL (optional)" value={hintSource} onChange={(e) => setHintSource(e.target.value)} className="text-xs h-8" />
                <div className="flex gap-1.5">
                  <Button type="button" size="sm" variant="secondary" onClick={addHint} className="text-xs h-7">Add</Button>
                  <Button type="button" size="sm" variant="ghost" onClick={() => setShowHintForm(false)} className="text-xs h-7">Cancel</Button>
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Main input */}
      <form onSubmit={handleSubmit} className="flex items-end gap-2">
        <Textarea
          placeholder="Enter research prompt… (Enter to send, Shift+Enter for newline)"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={handleKeyDown}
          className="flex-1 min-h-[44px] max-h-[120px] resize-none py-2.5"
          rows={1}
        />
        <Button
          type="submit"
          disabled={!prompt.trim()}
          className="h-11 w-11 rounded-full p-0 shrink-0"
        >
          <ArrowUp className="h-4 w-4" />
        </Button>
      </form>
    </div>
  );
}
