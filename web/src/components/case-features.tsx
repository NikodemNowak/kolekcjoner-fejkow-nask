"use client";

import { useState } from "react";
import { ValueText } from "@/components/value-text";
import { plural } from "@/lib/plural";
import { cn } from "@/lib/utils";
import type { FeatureFamily, Value } from "@/lib/types";

type Row = FeatureFamily["rows"][number];
const SHOWN = 4;

function MoreButton({ open, onClick, more }: { open: boolean; onClick: () => void; more?: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-expanded={open}
      className="text-xs text-muted-foreground underline decoration-border underline-offset-4 transition-colors hover:text-foreground hover:decoration-foreground/40"
    >
      {open ? "pokaż mniej" : (more ?? "pokaż więcej")}
    </button>
  );
}

/** Short values on one or a few lines; the rest behind "+N". */
function ShortValues({ values, total }: { values: Value[]; total: number }) {
  const [open, setOpen] = useState(false);
  const shown = open ? values : values.slice(0, SHOWN);
  const hidden = total - SHOWN;
  const inline = values.every((v) => !v.mono && v.text.length <= 28);
  return (
    <div className={cn(inline ? "flex flex-wrap gap-x-1.5" : "space-y-0.5")}>
      {shown.map((v, i) => (
        <span key={i} className={cn("min-w-0 break-words", !inline && "block")}>
          <ValueText value={v} className={v.mono ? "text-[12.5px]" : undefined} />
          {inline && i < shown.length - 1 && <span className="text-muted-foreground">,</span>}
        </span>
      ))}
      {hidden > 0 && (
        <span className={cn(!inline && "block pt-0.5")}>
          <MoreButton open={open} onClick={() => setOpen(!open)} more={`+${hidden} więcej`} />
          {open && total > values.length && <span className="ml-2 text-xs text-muted-foreground">(pokazano {values.length} z {total})</span>}
        </span>
      )}
    </div>
  );
}

/** Long prose: two lines, expandable. */
function LongText({ values }: { values: Value[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="space-y-1">
      <div className={cn("space-y-2 text-muted-foreground", !open && "line-clamp-2")}>
        {(open ? values : values.slice(0, 1)).map((v, i) => (
          <p key={i}>{v.text}</p>
        ))}
      </div>
      <MoreButton open={open} onClick={() => setOpen(!open)} />
    </div>
  );
}

/** Machine-read text is noisy: only a count until the analyst asks for it. */
function OcrText({ values, total }: { values: Value[]; total: number }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <span className="mr-2 text-muted-foreground">{plural(total, "fragment")}</span>
      <MoreButton open={open} onClick={() => setOpen(!open)} more="pokaż" />
      {open && (
        <ul className="mt-2 max-h-72 space-y-1.5 overflow-y-auto rounded-md bg-subtle p-3 font-mono text-xs leading-relaxed text-muted-foreground">
          {values.map((v, i) => (
            <li key={i} className="break-words">
              {v.text}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function FeatureValue({ row }: { row: Row }) {
  if (row.style === "text") return <LongText values={row.values} />;
  if (row.style === "ocr") return <OcrText values={row.values} total={row.total} />;
  return <ShortValues values={row.values} total={row.total} />;
}

/** All features of a case as one definition list, grouped by family. */
export function CaseFeatures({ families }: { families: FeatureFamily[] }) {
  return (
    <div className="border-t">
      {families.map((f) => (
        <section key={f.family} className="grid gap-x-8 gap-y-2 border-b py-5 md:grid-cols-[180px_minmax(0,1fr)]">
          <h3 className="text-sm font-semibold first-letter:uppercase">{f.label}</h3>
          <dl className="space-y-2.5 text-sm">
            {f.rows.map((r) => (
              <div key={r.kind} className="grid gap-x-6 gap-y-0.5 sm:grid-cols-[200px_minmax(0,1fr)]">
                <dt className="text-muted-foreground">{r.label}</dt>
                <dd className="min-w-0">
                  <FeatureValue row={r} />
                </dd>
              </div>
            ))}
          </dl>
        </section>
      ))}
    </div>
  );
}
