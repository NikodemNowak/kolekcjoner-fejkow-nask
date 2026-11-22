"use client";

import { useState } from "react";
import { ValueText } from "@/components/value-text";
import { cn } from "@/lib/utils";
import type { Value } from "@/lib/types";

/** Readable values (file names, domains, names); the first few shown, the rest behind "+N". */
export function ValueList({ values, shown = 4, className }: { values: Value[]; shown?: number; className?: string }) {
  const [open, setOpen] = useState(false);
  const visible = open ? values : values.slice(0, shown);
  const hidden = values.length - shown;
  const inline = values.every((v) => !v.mono && !v.raw && v.text.length <= 28);
  return (
    <div className={cn(inline ? "flex flex-wrap gap-x-1.5" : "space-y-0.5", className)}>
      {visible.map((v, i) => (
        <span key={i} className={cn("min-w-0 break-words", !inline && "block")}>
          <ValueText value={v} className={v.mono ? "text-[12.5px]" : undefined} />
          {inline && i < visible.length - 1 && <span className="text-muted-foreground">,</span>}
        </span>
      ))}
      {hidden > 0 && (
        <button
          type="button"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          className={cn(
            "text-xs text-muted-foreground underline decoration-border underline-offset-4 transition-colors hover:text-foreground hover:decoration-foreground/40",
            !inline && "block pt-0.5",
          )}
        >
          {open ? "pokaż mniej" : `+${hidden} więcej`}
        </button>
      )}
    </div>
  );
}
