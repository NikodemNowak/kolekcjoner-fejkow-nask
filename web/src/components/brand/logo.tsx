import { cn } from "@/lib/utils";

/**
 * Logomark: two linked nodes, one solid and one hollow. A real report and its fake twin,
 * joined by the trace that connects them. One colour (currentColor), legible at 16 px.
 */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" fill="none" aria-hidden className={cn("size-6 shrink-0 text-foreground", className)}>
      <path d="M12.6 19.4 19.4 12.6" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
      <circle cx="9" cy="23" r="6" fill="currentColor" />
      <circle cx="23" cy="9" r="4.5" stroke="currentColor" strokeWidth="3" />
    </svg>
  );
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn("text-[15px] leading-none font-semibold tracking-[-0.025em] whitespace-nowrap text-foreground", className)}>
      Kolekcjoner <span className="font-normal text-muted-foreground">Fejków</span>
    </span>
  );
}
