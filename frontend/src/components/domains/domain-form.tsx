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
import type { Domain } from "@/types";

interface DomainFormProps {
  onSubmit: (data: {
    name: string;
    description: string;
    prompt: string;
  }) => Promise<Domain | void>;
  isLoading?: boolean;
}

export function DomainForm({ onSubmit, isLoading }: DomainFormProps) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [prompt, setPrompt] = useState("");
  const [showPrompt, setShowPrompt] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    await onSubmit({ name: name.trim(), description, prompt });
    setName("");
    setDescription("");
    setPrompt("");
    setShowPrompt(false);
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
          <div className="flex gap-2 justify-end pt-2">
            <Button
              type="button"
              variant="ghost"
              onClick={() => setOpen(false)}
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
