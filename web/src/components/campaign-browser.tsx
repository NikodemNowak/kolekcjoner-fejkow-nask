"use client";

import { plural } from "@/lib/plural";
import Link from "next/link";
import { useMemo, useState } from "react";
import { ArrowUpRight, Search, X } from "lucide-react";
import { CampaignTitle } from "@/components/campaign-title";
import { OperatorDot } from "@/components/operator-badge";
import { ThumbImage } from "@/components/thumb";
import { campaignHref, int } from "@/lib/format";
import { cn } from "@/lib/utils";
import { GLOSSARY } from "@/lib/glossary";
import type { CampaignSummary } from "@/lib/types";

type Sort = "size" | "operator" | "title";
const SORTS: { id: Sort; label: string }[] = [
  { id: "size", label: "największe" },
  { id: "operator", label: "sprawca" },
  { id: "title", label: "A–Z" },
];

function matches(c: CampaignSummary, q: string) {
  if (!q) return true;
  const hay = [c.label, c.operator?.label ?? "", ...c.chips, ...c.persons, ...c.rotating, ...c.domains]
    .join(" ")
    .toLowerCase()
    .replace(/\[\.\]/g, ".");
  return q
    .toLowerCase()
    .split(/\s+/)
    .every((t) => hay.includes(t));
}

function sorted(list: CampaignSummary[], sort: Sort) {
  const out = [...list];
  if (sort === "title") out.sort((a, b) => a.label.localeCompare(b.label, "pl"));
  else if (sort === "operator")
    out.sort(
      (a, b) =>
        (a.operator_index ?? 99) - (b.operator_index ?? 99) || b.size - a.size || a.label.localeCompare(b.label, "pl"),
    );
  else out.sort((a, b) => b.size - a.size || (a.operator_index ?? 99) - (b.operator_index ?? 99));
  return out;
}

/** Up to three plain-word traits the reports share; raw values (domains, slugs) are left out. */
function sharedTraits(c: CampaignSummary) {
  return c.chips
    .filter((t) => !t.includes("[.]") && /\s/.test(t))
    .map((t) => {
      const m = /^Domena: (\d+)$/.exec(t);
      return m ? plural(Number(m[1]), ["wspólna domena", "wspólne domeny", "wspólnych domen"]) : t;
    })
    .slice(0, 3);
}

export function CampaignBrowser({ campaigns }: { campaigns: CampaignSummary[] }) {
  const [query, setQuery] = useState("");
  const [operator, setOperator] = useState<string | null>(null);
  const [sort, setSort] = useState<Sort>("size");
  const operators = useMemo(() => {
    const seen = new Map<string, { label: string; index: number | null; count: number }>();
    for (const c of campaigns) {
      if (!c.operator) continue;
      const prev = seen.get(c.operator.id);
      seen.set(c.operator.id, { label: c.operator.label, index: c.operator_index, count: (prev?.count ?? 0) + 1 });
    }
    return [...seen.entries()].sort((a, b) => a[1].label.localeCompare(b[1].label, "pl"));
  }, [campaigns]);

  const visible = useMemo(
    () => sorted(campaigns.filter((c) => matches(c, query) && (!operator || c.operator?.id === operator)), sort),
    [campaigns, query, operator, sort],
  );
  const groups = visible.filter((c) => c.size > 1);
  const singles = visible.filter((c) => c.size === 1);
  const filtering = Boolean(query || operator);
  // A large base is mostly singles: show the first ones, the rest on request.
  const [allSingles, setAllSingles] = useState(false);
  const shownSingles = allSingles || filtering ? singles : singles.slice(0, 30);

  return (
    <div>
      <div className="mb-8 flex flex-col gap-3 border-y py-3 lg:flex-row lg:items-center lg:gap-6">
        <label className="relative block lg:w-72">
          <span className="sr-only">Szukaj kampanii</span>
          <Search className="pointer-events-none absolute top-1/2 left-0 size-4 -translate-y-1/2 text-muted-foreground" strokeWidth={1.75} />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Szukaj: nagłówek, osoba, domena"
            className="h-8 w-full bg-transparent pr-6 pl-6 text-sm outline-none placeholder:text-muted-foreground"
          />
          {query && (
            <button type="button" onClick={() => setQuery("")} aria-label="Wyczyść wyszukiwanie" className="absolute top-1/2 right-0 -translate-y-1/2 rounded p-0.5 text-muted-foreground hover:text-foreground">
              <X className="size-3.5" />
            </button>
          )}
        </label>
        <div className="hidden h-5 w-px bg-border lg:block" />
        <div role="group" aria-label="Filtr sprawcy" className="-mx-1 flex flex-wrap items-center gap-x-1 gap-y-1 text-[13px]">
          <FilterButton active={operator === null} onClick={() => setOperator(null)}>
            Wszyscy sprawcy
          </FilterButton>
          {operators.map(([id, op]) => (
            <FilterButton key={id} active={operator === id} onClick={() => setOperator(operator === id ? null : id)}>
              <OperatorDot index={op.index} />
              {op.label.replace("Sprawca ", "")}
              <span className="text-muted-foreground tnum">{op.count}</span>
            </FilterButton>
          ))}
        </div>
        <div className="flex items-center gap-1 text-[13px] lg:ml-auto">
          <span className="mr-1 text-muted-foreground">Sortuj</span>
          {SORTS.map((s) => (
            <FilterButton key={s.id} active={sort === s.id} onClick={() => setSort(s.id)}>
              {s.label}
            </FilterButton>
          ))}
        </div>
      </div>

      {visible.length === 0 ? (
        <div className="py-16 text-center">
          <p className="text-sm font-medium">Brak kampanii dla tych filtrów</p>
          <button
            type="button"
            className="mt-2 text-[13px] text-muted-foreground underline underline-offset-4 hover:text-foreground"
            onClick={() => {
              setQuery("");
              setOperator(null);
            }}
          >
            Wyczyść filtry
          </button>
        </div>
      ) : (
        <div className="space-y-12">
          {groups.length > 0 && (
            <section aria-labelledby="groups-title">
              <ListHeading id="groups-title" title="Kampanie" count={groups.length} note="co najmniej dwa zgłoszenia połączone wspólnymi śladami" />
              <ul className="border-t">
                {groups.map((c) => (
                  <CampaignRow key={c.id} c={c} />
                ))}
              </ul>
            </section>
          )}
          {singles.length > 0 && (
            <section aria-labelledby="singles-title">
              <ListHeading id="singles-title" title="Pojedyncze zgłoszenia" count={singles.length} note="bez wystarczająco silnych śladów wspólnych z innymi" />
              <ul className="border-t">
                {shownSingles.map((c) => (
                  <SingleRow key={c.id} c={c} />
                ))}
              </ul>
              {shownSingles.length < singles.length && (
                <button
                  type="button"
                  onClick={() => setAllSingles(true)}
                  className="mt-3 text-[13px] font-medium text-link underline-offset-4 hover:underline"
                >
                  Pokaż wszystkie pojedyncze zgłoszenia ({int(singles.length)})
                </button>
              )}
            </section>
          )}
          {filtering && (
            <p className="text-xs text-muted-foreground tnum">
              Pokazano {int(visible.length)} z {int(campaigns.length)}.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function ListHeading({ id, title, count, note }: { id: string; title: string; count: number; note: string }) {
  return (
    <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
      <h2 id={id} className="text-[15px] font-semibold">
        {title} <span className="ml-1 font-normal text-muted-foreground tnum">{int(count)}</span>
      </h2>
      <p className="text-[13px] text-muted-foreground">{note}</p>
    </div>
  );
}

function FilterButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "inline-flex h-7 items-center gap-1.5 rounded-md px-2 whitespace-nowrap transition-colors",
        active ? "bg-foreground text-background [&_.text-muted-foreground]:text-background/70" : "text-muted-foreground hover:bg-muted hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

function Operator({ c }: { c: CampaignSummary }) {
  if (!c.operator) return <span className="text-muted-foreground">sprawca nieustalony</span>;
  return (
    <span title={GLOSSARY.operator} className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <OperatorDot index={c.operator_index} />
      {c.operator.label}
    </span>
  );
}

function CampaignRow({ c }: { c: CampaignSummary }) {
  const traits = sharedTraits(c);
  return (
    <li className="border-b">
      <Link
        href={campaignHref(c.id)}
        className="group grid grid-cols-[72px_minmax(0,1fr)] gap-x-4 gap-y-3 py-4 transition-colors hover:bg-surface sm:grid-cols-[88px_minmax(0,1fr)] sm:gap-x-5 sm:px-3 lg:grid-cols-[88px_minmax(0,1.15fr)_minmax(0,1fr)_20px] lg:gap-x-8"
      >
        <ThumbImage thumb={c.thumbs[0] ?? null} width={240} alt="" fit="contain" className="aspect-[4/5] w-full rounded-md border" />
        <div className="min-w-0 self-center">
          <h3 className="text-base leading-snug font-semibold text-pretty sm:text-[17px]">
            <CampaignTitle text={c.label} />
          </h3>
          {c.plain && <p className="mt-1.5 text-sm leading-snug text-pretty first-letter:uppercase">{c.plain}.</p>}
          {c.persons.length > 0 && (
            <p className="mt-1 line-clamp-1 text-[13px] text-muted-foreground">Wizerunek: {c.persons.join(", ")}</p>
          )}
          <p className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px]">
            <Operator c={c} />
          </p>
        </div>
        <dl className="col-span-2 grid min-w-0 gap-2 self-center text-[13px] leading-relaxed lg:col-span-1">
          {traits.length > 0 && (
            <div className="grid grid-cols-[84px_minmax(0,1fr)] gap-2">
              <dt className="text-muted-foreground">Łączy je</dt>
              <dd>{traits.join(", ")}</dd>
            </div>
          )}
          {c.rotating.length > 0 && (
            <div className="grid grid-cols-[84px_minmax(0,1fr)] gap-2">
              <dt className="text-muted-foreground">Zmienia się</dt>
              <dd className="text-muted-foreground">{c.rotating.slice(0, 3).join(", ")}</dd>
            </div>
          )}
        </dl>
        <ArrowUpRight className="hidden size-4 self-center text-muted-foreground/60 transition-colors group-hover:text-foreground lg:block" strokeWidth={1.75} aria-hidden />
      </Link>
    </li>
  );
}

function SingleRow({ c }: { c: CampaignSummary }) {
  return (
    <li className="border-b">
      <Link
        href={campaignHref(c.id)}
        className="group grid grid-cols-[36px_minmax(0,1fr)] items-center gap-x-3 py-2 text-[13px] transition-colors hover:bg-surface sm:grid-cols-[36px_minmax(0,1fr)_200px_110px] sm:gap-x-5 sm:px-3"
      >
        <ThumbImage thumb={c.thumbs[0] ?? null} width={96} alt="" className="size-9 rounded border" />
        <span className="min-w-0">
          <span className="block truncate text-sm font-medium">
            <CampaignTitle text={c.label} />
          </span>
          <span className="block truncate text-xs text-muted-foreground sm:hidden">
            {[c.domains[0], c.operator?.label].filter(Boolean).join(" · ") || "brak strony docelowej"}
          </span>
        </span>
        <span className="hidden truncate font-mono text-xs text-muted-foreground sm:block">{c.domains[0] ?? "—"}</span>
        <span className="hidden sm:block">
          <Operator c={c} />
        </span>
      </Link>
    </li>
  );
}
