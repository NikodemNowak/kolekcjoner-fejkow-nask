import { operatorColor } from "@/lib/palette";
import { GLOSSARY } from "@/lib/glossary";
import { cn } from "@/lib/utils";
import type { Ref } from "@/lib/types";

export function OperatorDot({ index, className }: { index: number | null; className?: string }) {
  return (
    <span
      aria-hidden
      className={cn("inline-block size-2 shrink-0 rounded-full", className)}
      style={{ background: operatorColor(index) }}
    />
  );
}

export function OperatorBadge({
  operator,
  index,
  className,
}: {
  operator: Ref | null;
  index: number | null;
  className?: string;
}) {
  if (!operator)
    return (
      <span title={GLOSSARY.operator} className={cn("text-xs text-muted-foreground", className)}>
        sprawca nieustalony
      </span>
    );
  return (
    <span
      title={GLOSSARY.operator}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border bg-card px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        className,
      )}
    >
      <OperatorDot index={index} />
      {operator.label}
    </span>
  );
}
