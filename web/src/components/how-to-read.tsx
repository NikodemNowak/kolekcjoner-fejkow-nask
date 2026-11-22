import { ChevronDown, CircleHelp } from "lucide-react";
import { cn } from "@/lib/utils";

/** A small collapsible "how to read this page" hint: three plain bullets for a first-time reader. */
export function HowToRead({ items, className, open }: { items: React.ReactNode[]; className?: string; open?: boolean }) {
  return (
    <details open={open} className={cn("group rounded-lg border bg-card text-[13px] shadow-card", className)}>
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 font-medium [&::-webkit-details-marker]:hidden">
        <CircleHelp className="size-4 text-muted-foreground" strokeWidth={1.75} aria-hidden />
        Jak czytać tę stronę
        <ChevronDown className="ml-auto size-4 text-muted-foreground transition-transform group-open:rotate-180" aria-hidden />
      </summary>
      <ol className="space-y-1.5 border-t px-3 py-3 leading-relaxed text-muted-foreground">
        {items.map((item, i) => (
          <li key={i} className="grid grid-cols-[1.25rem_minmax(0,1fr)]">
            <span className="font-medium text-foreground tnum">{i + 1}.</span>
            <span>{item}</span>
          </li>
        ))}
      </ol>
    </details>
  );
}
