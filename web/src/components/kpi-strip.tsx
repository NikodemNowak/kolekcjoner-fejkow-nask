import { int } from "@/lib/format";
import { cn } from "@/lib/utils";

export type Kpi = { label: string; value: number; note?: string };

/** A quiet summary line: figures first, labels beneath, hairlines between. */
export function KpiStrip({ items, className }: { items: Kpi[]; className?: string }) {
  return (
    <dl className={cn("grid grid-cols-2 gap-y-5 sm:grid-cols-3 lg:flex lg:gap-0", className)}>
      {items.map((k) => (
        <div key={k.label} className="lg:flex-1 lg:border-l lg:pl-5 lg:first:border-l-0 lg:first:pl-0">
          <dd className="text-[28px] leading-none font-semibold tracking-tight tnum">{int(k.value)}</dd>
          <dt className="mt-2 text-[13px] font-medium">{k.label}</dt>
          {k.note && <p className="text-xs text-muted-foreground">{k.note}</p>}
        </div>
      ))}
    </dl>
  );
}
