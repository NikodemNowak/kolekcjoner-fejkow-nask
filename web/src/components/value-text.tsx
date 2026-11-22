"use client";

import { Copy } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { Value } from "@/lib/types";

/** A readable value; the raw value (hash, full path) only in a tooltip with a copy button. */
export function ValueText({ value, className }: { value: Value; className?: string }) {
  const text = (
    <span className={cn(value.mono && "font-mono text-[0.8125rem]", "break-words", className)}>
      {value.text}
    </span>
  );
  if (!value.raw) return text;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="cursor-help underline decoration-dotted decoration-muted-foreground/50 underline-offset-4">
          {text}
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-sm">
        <span className="font-mono text-[11px] break-all">{value.raw}</span>
        <button
          type="button"
          className="ml-1 rounded p-0.5 opacity-70 hover:opacity-100"
          onClick={() => navigator.clipboard?.writeText(value.raw ?? "")}
          aria-label="Kopiuj"
        >
          <Copy className="size-3" />
        </button>
      </TooltipContent>
    </Tooltip>
  );
}
