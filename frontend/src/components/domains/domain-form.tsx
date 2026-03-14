import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Plus } from "lucide-react";
import type { Domain, WorkspaceSource } from "@/types";

export interface WorkspaceFormData {
  source: WorkspaceSource;
  path: string;
  git_url: string;
  git_ref: string;
}

interface DomainFormProps {
  onSubmit: (data: {
    name: string;
    description: string;
    prompt: string;
    workspace?: WorkspaceFormData;
  }) => Promise<Domain | void>;
  isLoading?: boolean;
}

export function DomainForm({ onSubmit, isLoading }: DomainFormProps) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [prompt, setPrompt] = useState("");
  const [showPrompt, setShowPrompt] = useState(false);

  // Workspace state
  const [showWorkspace, setShowWorkspace] = useState(false);
  const [wsSource, setWsSource] = useState<WorkspaceSource>("local");
  const [wsPath, setWsPath] = useState("");
  const [wsGitUrl, setWsGitUrl] = useState("");
  const [wsGitRef, setWsGitRef] = useState("");

  const reset = () => {
    setName("");
    setDescription("");
    setPrompt("");
    setShowPrompt(false);
    setShowWorkspace(false);
    setWsSource("local");
    setWsPath("");
    setWsGitUrl("");
    setWsGitRef("");
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;

    const workspace: WorkspaceFormData | undefined = showWorkspace
      ? { source: wsSource, path: wsPath, git_url: wsGitUrl, git_ref: wsGitRef }
      : undefined;

    await onSubmit({ name: name.trim(), description, prompt, workspace });
    reset();
    setOpen(false);
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <Plus className="h-4 w-4" />
          New Domain
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="font-heading font-bold text-blackberry">
            Create Research Domain
          </DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4 mt-2">
          {/* Name */}
          <div>
            <label className="text-sm font-medium text-blackberry mb-1.5 block">
              Name <span className="text-danger">*</span>
            </label>
            <Input
              placeholder="e.g. Sentiment Analysis"
              value={name}
              onChange={(e) => setName(e.target.value)}
              maxLength={80}
            />
            <span className="text-xs text-grey mt-1 block text-right">
              {name.length}/80
            </span>
          </div>

          {/* Description */}
          <div>
            <label className="text-sm font-medium text-blackberry mb-1.5 block">
              Description
            </label>
            <Textarea
              placeholder="Brief description of this research domain"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              className="min-h-[80px]"
            />
          </div>

          {/* System Prompt (advanced, collapsible) */}
          <div>
            <button
              type="button"
              onClick={() => setShowPrompt(!showPrompt)}
              className="text-sm text-grey hover:text-blackberry transition-colors flex items-center gap-1"
            >
              <span>{showPrompt ? "▾" : "▸"}</span>
              Advanced: System Prompt
            </button>
            {showPrompt && (
              <Textarea
                className="mt-2 min-h-[100px]"
                placeholder="Steering prompt for the AI agent (optional)"
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
              />
            )}
          </div>

          {/* Workspace (collapsible) */}
          <div>
            <button
              type="button"
              onClick={() => setShowWorkspace(!showWorkspace)}
              className="text-sm text-grey hover:text-blackberry transition-colors flex items-center gap-1"
            >
              <span>{showWorkspace ? "▾" : "▸"}</span>
              Workspace Environment
            </button>
            {showWorkspace && (
              <div className="mt-3 space-y-3 rounded-xl border border-soft-fawn/20 p-4">
                {/* Source radio */}
                <div>
                  <label className="text-xs font-medium text-grey mb-2 block">
                    Source
                  </label>
                  <div className="flex gap-4">
                    {(["local", "git", "empty"] as const).map((src) => (
                      <label
                        key={src}
                        className="flex items-center gap-1.5 cursor-pointer"
                      >
                        <input
                          type="radio"
                          name="wsSource"
                          value={src}
                          checked={wsSource === src}
                          onChange={() => setWsSource(src)}
                          className="accent-blackberry"
                        />
                        <span className="text-sm text-blackberry">{src}</span>
                      </label>
                    ))}
                  </div>
                </div>

                {/* Local / Empty: path input */}
                {wsSource !== "git" && (
                  <div>
                    <label className="text-xs font-medium text-grey mb-1 block">
                      {wsSource === "empty"
                        ? "Directory path (will be created)"
                        : "Local path"}
                    </label>
                    <Input
                      placeholder="/Users/me/projects/my-ml-project"
                      value={wsPath}
                      onChange={(e) => setWsPath(e.target.value)}
                      className="font-mono text-xs"
                    />
                  </div>
                )}

                {/* Git: URL + ref */}
                {wsSource === "git" && (
                  <>
                    <div>
                      <label className="text-xs font-medium text-grey mb-1 block">
                        Git URL
                      </label>
                      <Input
                        placeholder="https://github.com/user/repo.git"
                        value={wsGitUrl}
                        onChange={(e) => setWsGitUrl(e.target.value)}
                        className="font-mono text-xs"
                      />
                    </div>
                    <div>
                      <label className="text-xs font-medium text-grey mb-1 block">
                        Branch / Tag / Commit{" "}
                        <span className="font-normal">(optional, default: main)</span>
                      </label>
                      <Input
                        placeholder="main"
                        value={wsGitRef}
                        onChange={(e) => setWsGitRef(e.target.value)}
                        className="font-mono text-xs"
                      />
                    </div>
                  </>
                )}
              </div>
            )}
          </div>

          <div className="flex gap-2 justify-end pt-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => { reset(); setOpen(false); }}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={!name.trim() || isLoading}>
              {isLoading ? "Creating…" : "Create Domain"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
