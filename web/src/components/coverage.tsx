import Link from "next/link";
import { ThumbImage } from "@/components/thumb";
import { caseHref } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { Member } from "@/lib/types";

const AVATARS = 8;

/** "Kopia NASK · p1" -> "NASK p1": a short name for a report. */
export function shortTitle(label: string) {
  const parts = label.split("·").map((x) => x.trim());
  if (parts.length > 1 && parts[0].startsWith("Źródła publiczne")) return parts[1];
  return parts.length > 1 ? `${parts[0].split(" ").pop()} ${parts[1]}` : label;
}

/**
 * In how many reports something occurs: a count, a strip of report thumbnails (collapsing to
 * "+N"), and on click the list of those reports. Works the same for 2 and for 60 reports.
 */
export function Coverage({
  members,
  indices,
  label,
  className,
}: {
  members: Member[];
  indices: number[];
  /** Replaces the default "w k z n zgłoszeń". */
  label?: React.ReactNode;
  className?: string;
}) {
  const shown = indices.slice(0, AVATARS);
  const more = indices.length - shown.length;
  return (
    <details className={cn("group min-w-0 text-[13px]", className)}>
      <summary className="flex cursor-pointer list-none flex-wrap items-center gap-x-2 gap-y-1 [&::-webkit-details-marker]:hidden">
        <span className="max-w-full truncate font-medium tnum" title={typeof label === "string" ? label : undefined}>
          {label ?? (
            <>
              w {indices.length} z {members.length} zgłoszeń
            </>
          )}
        </span>
        <span className="flex items-center -space-x-1.5">
          {shown.map((i) => (
            <ThumbImage key={i} thumb={members[i]?.thumb ?? null} width={64} alt="" className="size-6 rounded-full border-2 border-card" />
          ))}
          {more > 0 && (
            <span className="relative grid h-6 min-w-6 place-items-center rounded-full border-2 border-card bg-subtle px-1 text-[10px] font-medium tnum">
              +{more}
            </span>
          )}
        </span>
        <span className="text-xs text-muted-foreground underline decoration-border underline-offset-4 group-open:hidden">które?</span>
        <span className="hidden text-xs text-muted-foreground underline decoration-border underline-offset-4 group-open:inline">ukryj</span>
      </summary>
      <ul className="mt-2 flex max-h-40 flex-wrap gap-x-3 gap-y-1 overflow-y-auto text-xs">
        {indices.map((i) => (
          <li key={i}>
            <Link href={caseHref(members[i].id)} className="underline decoration-border underline-offset-4 hover:decoration-foreground/50">
              {shortTitle(members[i].title)}
            </Link>
          </li>
        ))}
      </ul>
    </details>
  );
}
