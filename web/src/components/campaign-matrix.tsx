import Link from "next/link";
import { ChevronDown, Megaphone, PanelTop } from "lucide-react";
import { ThumbImage } from "@/components/thumb";
import { ValueText } from "@/components/value-text";
import { Coverage } from "@/components/coverage";
import { caseHref, num } from "@/lib/format";
import { plural } from "@/lib/plural";
import { TIER_META, TIERS, type Tier } from "@/lib/palette";
import type { Matrix, MatrixCell, MatrixRow, Member } from "@/lib/types";

const TOP_PER_TIER = 6;
/** Beyond this many reports a column per report stops being readable: rows show totals instead. */
const MAX_COLUMNS = 8;

/**
 * Reports × shared traces. Every cell says where the trace was found in that report (in the ad
 * itself or on the landing page) and shows the source picture when there is one. Rendered from
 * the campaign payload without a client fetch or entry animation, so it cannot come up empty.
 */
export function CampaignMatrix({ matrix, members }: { matrix: Matrix; members: Member[] }) {
  const byId = new Map(members.map((m) => [m.id, m]));
  const groups = TIERS.map((tier) => ({
    tier,
    rows: matrix.rows.filter((r) => ((r.tier as Tier) ?? "context") === tier),
  })).filter((g) => g.rows.length > 0);
  if (groups.length === 0) {
    return (
      <p className="border-y py-6 text-sm text-muted-foreground">
        Wspólne ślady tej kampanii są zbyt pospolite, by je tu pokazać (na przykład popularne biblioteki). O powiązaniu
        zdecydowało podobieństwo treści i obrazu opisane wyżej.
      </p>
    );
  }
  // Main view: readable traces only. Paths, endpoints and the long tail wait behind "show more".
  const main = groups
    .map((g) => ({ tier: g.tier, rows: g.rows.filter((r) => !r.technical).slice(0, TOP_PER_TIER) }))
    .filter((g) => g.rows.length > 0);
  const shown = new Set(main.flatMap((g) => g.rows));
  const rest = groups.map((g) => ({ tier: g.tier, rows: g.rows.filter((r) => !shown.has(r)) })).filter((g) => g.rows.length > 0);
  const restCount = rest.reduce((sum, g) => sum + g.rows.length, 0);
  const n = matrix.columns.length;
  if (n > MAX_COLUMNS) return <WideMatrix main={main} rest={rest} restCount={restCount} members={members} hidden={matrix.hidden} />;
  const cols = `minmax(128px, 1.1fr) repeat(${n}, minmax(104px, 1fr))`;

  const body = (items: { tier: Tier; rows: MatrixRow[] }[]) =>
    items.map((g) => (
      <div key={g.tier} role="rowgroup">
        <div className="sticky left-0 max-w-[calc(100vw-2.5rem)] px-3 pt-4 pb-1.5 sm:px-4 lg:max-w-none">
          <div className="flex items-center gap-2 text-[13px] font-semibold">
            <span aria-hidden className="size-2 rounded-full" style={{ background: TIER_META[g.tier].color }} />
            {TIER_META[g.tier].label}
          </div>
          <p className="mt-0.5 max-w-2xl text-xs leading-snug text-muted-foreground">{TIER_META[g.tier].hint}</p>
        </div>
        {g.rows.map((r, i) => (
          <div
            role="row"
            key={`${r.group}-${r.label}-${i}`}
            className="grid items-center gap-x-2 border-b px-3 py-2 sm:px-4"
            style={{ gridTemplateColumns: cols }}
          >
            <div role="rowheader" className="min-w-0 text-[13px] leading-snug">
              <span className="block text-[11px] text-muted-foreground">{r.group}</span>
              <span className="line-clamp-2 break-words">
                <ValueText value={{ text: r.label, raw: r.raw, mono: r.mono }} />
              </span>
            </div>
            {r.cells.map((cell, ci) => (
              <Cell key={ci} cell={cell} row={r} />
            ))}
          </div>
        ))}
      </div>
    ));

  return (
    <div className="overflow-hidden rounded-xl border bg-card shadow-card">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1 border-b px-3 py-2.5 text-xs text-muted-foreground sm:px-4">
        <span className="font-medium text-foreground">Gdzie znaleziono ślad:</span>
        <span className="inline-flex items-center gap-1.5">
          <Megaphone className="size-3.5" strokeWidth={1.75} aria-hidden /> w reklamie
        </span>
        <span className="inline-flex items-center gap-1.5">
          <PanelTop className="size-3.5" strokeWidth={1.75} aria-hidden /> na stronie docelowej
        </span>
        <span>— brak w tej reklamie</span>
      </div>
      <div className="overflow-x-auto">
        <div role="table" aria-label="Macierz: reklamy i wspólne ślady" className="min-w-fit">
          <div role="row" className="grid items-end gap-x-2 border-b bg-surface px-3 py-2.5 sm:px-4" style={{ gridTemplateColumns: cols }}>
            <div role="columnheader" className="text-xs font-medium text-muted-foreground">
              Wspólny ślad
            </div>
            {matrix.columns.map((c, i) => {
              const member = byId.get(c.id);
              return (
                <div role="columnheader" key={c.id}>
                  <Link href={caseHref(c.id)} title={c.label} className="group flex items-center gap-2">
                    <ThumbImage thumb={member?.thumb ?? null} width={96} alt="" className="size-9 shrink-0 rounded-md border" />
                    <span className="min-w-0 text-xs leading-tight">
                      <span className="block font-medium group-hover:underline">Reklama {i + 1}</span>
                      <span className="block truncate text-[11px] text-muted-foreground">{shortCase(c.label)}</span>
                    </span>
                  </Link>
                </div>
              );
            })}
          </div>
          {body(main)}
          {restCount > 0 && (
            <details className="group">
              <summary className="flex cursor-pointer list-none items-center justify-center gap-1.5 px-3 py-2.5 text-[13px] font-medium text-muted-foreground transition-colors hover:bg-surface hover:text-foreground [&::-webkit-details-marker]:hidden">
                <ChevronDown className="size-4 transition-transform group-open:rotate-180" />
                <span className="group-open:hidden">Pokaż pozostałe ślady, także techniczne ({restCount})</span>
                <span className="hidden group-open:inline">Pokaż tylko najważniejsze</span>
              </summary>
              <div className="border-t">{body(rest)}</div>
            </details>
          )}
        </div>
      </div>
    </div>
  );
}

type Group = { tier: Tier; rows: MatrixRow[] };

/** The same traces for a large campaign: one line per trace with totals and the list on demand. */
function WideMatrix({ main, rest, restCount, members, hidden }: { main: Group[]; rest: Group[]; restCount: number; members: Member[]; hidden: number }) {
  const body = (items: Group[]) =>
    items.map((g) => (
      <div key={g.tier}>
        <div className="px-3 pt-4 pb-1.5 sm:px-4">
          <div className="flex items-center gap-2 text-[13px] font-semibold">
            <span aria-hidden className="size-2 rounded-full" style={{ background: TIER_META[g.tier].color }} />
            {TIER_META[g.tier].label}
          </div>
          <p className="mt-0.5 max-w-2xl text-xs leading-snug text-muted-foreground">{TIER_META[g.tier].hint}</p>
        </div>
        {g.rows.map((r, i) => {
          const present = r.cells.map((cell, index) => (cell.ad + cell.page > 0 ? index : -1)).filter((index) => index >= 0);
          const ad = r.cells.filter((cell) => cell.ad > 0).length;
          const page = r.cells.filter((cell) => cell.page > 0).length;
          const thumb = r.cells.find((cell) => cell.thumb)?.thumb;
          return (
            <div key={`${r.group}-${r.label}-${i}`} className="grid items-center gap-x-4 gap-y-1.5 border-b px-3 py-2 sm:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,1.1fr)] sm:px-4">
              <div className="flex min-w-0 items-center gap-2.5 text-[13px] leading-snug">
                {thumb && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={`${thumb}${thumb.includes("?") ? "&" : "?"}w=96`} alt="" loading="lazy" className="size-9 shrink-0 rounded-md border bg-subtle object-cover" />
                )}
                <span className="min-w-0">
                  <span className="block text-[11px] text-muted-foreground">{r.group}</span>
                  <span className="line-clamp-2 break-words">
                    <ValueText value={{ text: r.label, raw: r.raw, mono: r.mono }} />
                  </span>
                </span>
              </div>
              <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs">
                {ad > 0 && (
                  <span className="inline-flex items-center gap-1 whitespace-nowrap tnum">
                    <Megaphone className="size-3.5" strokeWidth={1.75} aria-hidden /> w reklamie: {ad}
                  </span>
                )}
                {page > 0 && (
                  <span className="inline-flex items-center gap-1 whitespace-nowrap tnum">
                    <PanelTop className="size-3.5" strokeWidth={1.75} aria-hidden /> na stronie: {page}
                  </span>
                )}
              </div>
              <Coverage members={members} indices={present} />
            </div>
          );
        })}
      </div>
    ));
  return (
    <div className="overflow-hidden rounded-xl border bg-card shadow-card">
      <p className="border-b px-3 py-2.5 text-xs text-muted-foreground sm:px-4">
        Kampania jest duża, więc zamiast kolumny na każde zgłoszenie pokazujemy, w ilu zgłoszeniach ślad występuje. Kliknij „które?”, aby zobaczyć listę.
      </p>
      {body(main)}
      {restCount > 0 && (
        <details className="group">
          <summary className="flex cursor-pointer list-none items-center justify-center gap-1.5 px-3 py-2.5 text-[13px] font-medium text-muted-foreground transition-colors hover:bg-surface hover:text-foreground [&::-webkit-details-marker]:hidden">
            <ChevronDown className="size-4 transition-transform group-open:rotate-180" />
            <span className="group-open:hidden">Pokaż pozostałe ślady, także techniczne ({restCount})</span>
            <span className="hidden group-open:inline">Pokaż tylko najważniejsze</span>
          </summary>
          <div className="border-t">{body(rest)}</div>
        </details>
      )}
      {hidden > 0 && <p className="border-t px-3 py-2 text-xs text-muted-foreground sm:px-4">Poza listą: {plural(hidden, "trace")} tego samego rodzaju co pokazane.</p>}
    </div>
  );
}

function Cell({ cell, row }: { cell: MatrixCell; row: MatrixRow }) {
  if (cell.ad + cell.page === 0) {
    return (
      <div role="cell" aria-label="brak" className="text-sm text-muted-foreground/60">
        —
      </div>
    );
  }
  // Counting occurrences only helps for faces and logos (how many pictures show them).
  const counted = row.entity_type === "Person" || row.entity_type.startsWith("Brand");
  const where = (
    <span className="min-w-0 space-y-0.5 text-xs leading-tight">
      {cell.ad > 0 && (
        <span className="flex items-center gap-1 whitespace-nowrap">
          <Megaphone className="size-3.5 shrink-0" strokeWidth={1.75} aria-hidden />
          reklama{counted && cell.ad > 1 ? ` ×${cell.ad}` : ""}
        </span>
      )}
      {cell.page > 0 && (
        <span className="flex items-center gap-1 whitespace-nowrap">
          <PanelTop className="size-3.5 shrink-0" strokeWidth={1.75} aria-hidden />
          strona{counted && cell.page > 1 ? ` ×${cell.page}` : ""}
        </span>
      )}
      {cell.confidence !== null && cell.confidence < 0.995 && (
        <span className="block whitespace-nowrap text-[11px] text-muted-foreground tnum">podobieństwo {num(cell.confidence, 2)}</span>
      )}
    </span>
  );
  return (
    <div role="cell" className="flex min-w-0 items-center gap-2">
      {cell.thumb && (
        // eslint-disable-next-line @next/next/no-img-element
        <img
          src={`${cell.thumb}${cell.thumb.includes("?") ? "&" : "?"}w=96`}
          alt=""
          loading="lazy"
          decoding="async"
          className="size-9 shrink-0 rounded-md border bg-subtle object-cover"
        />
      )}
      {where}
    </div>
  );
}

function shortCase(label: string) {
  // "Kopia NASK · p1" -> "NASK p1"; "Materiały mentora · 2" -> "mentora 2".
  const parts = label.split("·").map((x) => x.trim());
  return parts.length > 1 ? `${parts[0].split(" ").pop()} ${parts[1]}` : label;
}
