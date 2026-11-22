"use client";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { GLOSSARY, type GlossaryKey } from "@/lib/glossary";
import { cn } from "@/lib/utils";

/** A technical word with its plain explanation in a tooltip (hover, focus or tap). */
export function Term({ k, children, className }: { k: GlossaryKey; children: React.ReactNode; className?: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          tabIndex={0}
          className={cn("cursor-help underline decoration-muted-foreground/50 decoration-dotted underline-offset-4", className)}
        >
          {children}
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-72 leading-relaxed text-pretty">{GLOSSARY[k]}</TooltipContent>
    </Tooltip>
  );
}
