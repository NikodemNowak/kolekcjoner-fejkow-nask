"use client";

import Link from "next/link";
import { useCallback, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import {
  ArrowRight,
  Maximize,
  Minus,
  MousePointerClick,
  Plus,
  Repeat,
  Search,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { OperatorBadge, OperatorDot } from "@/components/operator-badge";
import { ThumbImage } from "@/components/thumb";
import { CampaignTitle, plainTitle } from "@/components/campaign-title";
import { EASE_OUT } from "@/components/motion";
import { campaignHref, int, plural, pluralWord, smartTruncate } from "@/lib/format";
import { operatorColor } from "@/lib/palette";
import { cn } from "@/lib/utils";
import type { CampaignSummary, GraphData, Network } from "@/lib/types";
import { CampaignGraph, type CampaignGraphHandle } from "./campaign-graph";
import { layoutCampaigns } from "./layout";
import { TraceMatrix } from "./trace-matrix";
import { NetworkExplorer } from "./network-explorer";

/**
 * Size of an element that may unmount and remount (the map is swapped with the trace matrix).
 * A callback ref re-attaches the observer to each new element; an effect keyed on a ref object
 * would keep watching the detached one and report 0x0 forever.
 */
function useSize() {
  const [size, setSize] = useState({ width: 0, height: 0 });
  const observer = useRef<ResizeObserver | null>(null);
  const ref = useCallback((el: HTMLDivElement | null) => {
    observer.current?.disconnect();
    observer.current = null;
    if (!el) return;
    const read = (width: number, height: number) =>
      setSize((prev) => {
        const next = { width: Math.floor(width), height: Math.floor(height) };
        return prev.width === next.width && prev.height === next.height ? prev : next;
      });
    read(el.clientWidth, el.clientHeight);
    observer.current = new ResizeObserver(([entry]) => read(entry.contentRect.width, entry.contentRect.height));
    observer.current.observe(el);
  }, []);
  return [ref, size] as const;
}

type Mode = "network" | "map" | "traces";

export function GraphExplorer({
  graph,
  campaigns,
  network,
  focus,
}: {
  graph: GraphData;
  campaigns: CampaignSummary[];
  network: Network | null;
  focus?: string | null;
}) {
  const layout = useMemo(() => layoutCampaigns(graph.nodes, graph.links), [graph]);
  const byId = useMemo(() => new Map(campaigns.map((c) => [c.id, c])), [campaigns]);
  const multi = useMemo(() => campaigns.filter((c) => c.size > 1), [campaigns]);
  const [mode, setMode] = useState<Mode>(network ? "network" : "map");
  const [selected, setSelected] = useState<string | null>(null);
  const [traceCampaign, setTraceCampaign] = useState<string>(multi[0]?.id ?? campaigns[0]?.id ?? "");
  const [group, setGroup] = useState<number | null>(null);
  const handle = useRef<CampaignGraphHandle>(null);
  const [box, size] = useSize();

  const operators = useMemo(() => {
    const map = new Map<number, { label: string; count: number }>();
    for (const n of graph.nodes)
      if (n.group_index !== null) map.set(n.group_index, { label: n.group ?? "", count: (map.get(n.group_index)?.count ?? 0) + 1 });
    return [...map.entries()].sort((a, b) => a[0] - b[0]);
  }, [graph]);
  const loose = graph.nodes.filter((n) => n.group_index === null).length;
  const operatorLinks = graph.links.filter((l) => l.kind === "operator").length;
  const toolkitLinks = graph.links.length - operatorLinks;

  const select = (id: string | null, center = false) => {
    setSelected(id);
    setGroup(null);
    if (id && center) handle.current?.center(id);
  };
  const sel = selected ? byId.get(selected) ?? null : null;
  const links = selected ? graph.links.filter((l) => l.source === selected || l.target === selected) : [];

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <div role="tablist" aria-label="Widok grafu" className="inline-flex w-fit rounded-lg border bg-card p-0.5 shadow-card">
          {network && (
            <TabButton label="Sieć powiązań" active={mode === "network"} onClick={() => setMode("network")}>
              <span className="sm:hidden">Sieć</span>
              <span className="hidden sm:inline">Sieć powiązań</span>
            </TabButton>
          )}
          <TabButton label="Kampanie i sprawcy" active={mode === "map"} onClick={() => setMode("map")}>
            <span className="sm:hidden">Sprawcy</span>
            <span className="hidden sm:inline">Kampanie i sprawcy</span>
          </TabButton>
          <TabButton label="Ślady kampanii" active={mode === "traces"} onClick={() => setMode("traces")}>
            <span className="sm:hidden">Ślady</span>
            <span className="hidden sm:inline">Ślady kampanii</span>
          </TabButton>
        </div>
        {mode === "network" ? null : mode === "map" ? (
          <NodeSearch campaigns={campaigns} onPick={(id) => select(id, true)} />
        ) : (
          <label className="flex min-w-0 items-center gap-2 text-[13px] sm:ml-auto">
            <span className="shrink-0 text-muted-foreground">Kampania</span>
            <select
              value={traceCampaign}
              onChange={(e) => setTraceCampaign(e.target.value)}
              className="h-9 min-w-0 flex-1 rounded-lg border bg-card px-2.5 text-sm shadow-card outline-none focus-visible:ring-3 focus-visible:ring-ring/25 sm:w-96"
            >
              <optgroup label="Kampanie z wieloma zgłoszeniami">
                {multi.map((c) => (
                  <option key={c.id} value={c.id}>
                    {smartTruncate(plainTitle(c.label), 70)} ({c.size})
                  </option>
                ))}
              </optgroup>
              <optgroup label="Pojedyncze zgłoszenia">
                {campaigns
                  .filter((c) => c.size === 1)
                  .map((c) => (
                    <option key={c.id} value={c.id}>
                      {smartTruncate(plainTitle(c.label), 70)}
                    </option>
                  ))}
              </optgroup>
            </select>
          </label>
        )}
      </div>

      {mode === "network" && network ? (
        <NetworkExplorer net={network} focus={focus} />
      ) : mode === "map" ? (
        <div className="grid grid-cols-[minmax(0,1fr)] gap-3 lg:grid-cols-[minmax(0,1fr)_320px]">
          <div className="relative overflow-hidden rounded-xl border bg-card shadow-card">
            <div ref={box} className="h-[52vh] min-h-[360px] sm:h-[58vh] sm:min-h-[420px] lg:h-[calc(100dvh-230px)] lg:max-h-[760px]">
              {size.width > 0 && size.height > 0 && (
                <CampaignGraph
                  ref={handle}
                  layout={layout}
                  width={size.width}
                  height={size.height}
                  selected={selected}
                  highlightGroup={group}
                  onSelect={(id) => select(id)}
                />
              )}
            </div>
            <div className="absolute top-3 right-3 flex flex-col overflow-hidden rounded-lg border bg-card shadow-card">
              <IconButton label="Przybliż" onClick={() => handle.current?.zoomBy(1.4)}>
                <Plus className="size-4" />
              </IconButton>
              <IconButton label="Oddal" onClick={() => handle.current?.zoomBy(1 / 1.4)}>
                <Minus className="size-4" />
              </IconButton>
              <IconButton label="Dopasuj do widoku" onClick={() => handle.current?.fit()}>
                <Maximize className="size-4" />
              </IconButton>
            </div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t bg-card px-2.5 py-2 text-xs sm:absolute sm:bottom-3 sm:left-3 sm:max-w-[calc(100%-24px)] sm:rounded-lg sm:border sm:bg-card/95 sm:py-1.5 sm:shadow-card sm:backdrop-blur">
              {operators.map(([index, op]) => (
                <button
                  key={index}
                  type="button"
                  aria-pressed={group === index}
                  onClick={() => {
                    setSelected(null);
                    setGroup(group === index ? null : index);
                  }}
                  className={cn(
                    "inline-flex items-center gap-1.5 rounded px-1 py-0.5 transition-colors hover:bg-surface",
                    group === index && "bg-muted font-medium",
                  )}
                >
                  <OperatorDot index={index} />
                  {op.label}
                </button>
              ))}
              <span className="inline-flex items-center gap-1.5 px-1 text-muted-foreground">
                <OperatorDot index={null} /> sprawca nieustalony
              </span>
              <span className="hidden h-3 w-px bg-border sm:block" />
              <span className="inline-flex items-center gap-1.5 text-muted-foreground">
                <svg width="18" height="6" aria-hidden><line x1="1" y1="3" x2="17" y2="3" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" /></svg>
                ten sam sprawca
              </span>
              <span className="inline-flex items-center gap-1.5 text-muted-foreground">
                <svg width="18" height="6" aria-hidden><line x1="1" y1="3" x2="17" y2="3" stroke="currentColor" strokeWidth="1.4" strokeDasharray="4 3" /></svg>
                ten sam program do stron
              </span>
            </div>
          </div>

          <aside className="rounded-xl border bg-card shadow-card lg:max-h-[760px] lg:overflow-y-auto">
            <AnimatePresence mode="wait" initial={false}>
              {sel ? (
                <motion.div
                  key={sel.id}
                  initial={{ opacity: 0, x: 8 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -8 }}
                  transition={{ duration: 0.18, ease: EASE_OUT }}
                  className="space-y-4 p-4"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="text-xs font-medium text-muted-foreground">
                      {sel.size > 1 ? `Kampania · ${plural(sel.size, "report")}` : "Pojedyncze zgłoszenie"}
                    </div>
                    <button type="button" onClick={() => select(null)} className="rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground" aria-label="Zamknij szczegóły">
                      <X className="size-4" />
                    </button>
                  </div>
                  <div className="grid grid-cols-[64px_minmax(0,1fr)] items-start gap-3">
                    <ThumbImage thumb={sel.thumbs[0] ?? null} width={200} alt="" fit="contain" className="aspect-[4/5] w-full rounded-md border" />
                    <h3 className="text-[15px] leading-snug font-semibold text-pretty"><CampaignTitle text={sel.label} /></h3>
                  </div>
                  <OperatorBadge operator={sel.operator} index={sel.operator_index} />
                  {sel.chips.length > 0 && (
                    <div>
                      <div className="mb-1.5 text-xs font-medium text-muted-foreground">Dlaczego razem</div>
                      <div className="flex flex-wrap gap-1">
                        {sel.chips.map((c) => (
                          <span key={c} className="rounded-md border bg-surface px-1.5 py-0.5 text-xs">{c}</span>
                        ))}
                      </div>
                    </div>
                  )}
                  {sel.rotating.length > 0 && (
                    <div className="flex items-start gap-1.5 text-xs text-muted-foreground">
                      <Repeat className="mt-0.5 size-3 shrink-0" /> Zmienne: {sel.rotating.join(", ")}
                    </div>
                  )}
                  <div>
                    <div className="mb-1.5 text-xs font-medium text-muted-foreground">
                      Powiązania ({int(links.length)})
                    </div>
                    {links.length === 0 ? (
                      <p className="text-[13px] text-muted-foreground">Brak powiązań z innymi kampaniami.</p>
                    ) : (
                      <ul className="space-y-1">
                        {links.map((l, i) => {
                          const other = l.source === sel.id ? l.target : l.source;
                          const o = byId.get(other);
                          return (
                            <li key={i}>
                              <button
                                type="button"
                                onClick={() => select(other, true)}
                                className="flex w-full items-start gap-2 rounded-md px-1.5 py-1 text-left text-[13px] hover:bg-surface"
                              >
                                <svg width="16" height="16" className="mt-0.5 shrink-0" aria-hidden>
                                  <line
                                    x1="1" y1="8" x2="15" y2="8"
                                    stroke={l.kind === "operator" ? operatorColor(o?.operator_index) : "var(--muted-foreground)"}
                                    strokeWidth={l.kind === "operator" ? 2.5 : 1.4}
                                    strokeDasharray={l.kind === "operator" ? undefined : "3 2"}
                                  />
                                </svg>
                                <span className="min-w-0">
                                  <span className="line-clamp-1">{o ? plainTitle(o.label) : other}</span>
                                  <span className="text-xs text-muted-foreground">
                                    {l.kind === "operator" ? "ten sam sprawca" : "ten sam program do stron"}
                                  </span>
                                </span>
                              </button>
                            </li>
                          );
                        })}
                      </ul>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-2 border-t pt-4">
                    <Button asChild size="sm">
                      <Link href={campaignHref(sel.id)}>
                        Otwórz kampanię <ArrowRight className="size-3.5" />
                      </Link>
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setTraceCampaign(sel.id);
                        setMode("traces");
                      }}
                    >
                      Ślady
                    </Button>
                  </div>
                </motion.div>
              ) : (
                <motion.div
                  key="help"
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  exit={{ opacity: 0 }}
                  transition={{ duration: 0.15 }}
                  className="space-y-4 p-4 text-[13px]"
                >
                  <div className="flex items-center gap-2 font-medium">
                    <MousePointerClick className="size-4 text-muted-foreground" strokeWidth={1.75} />
                    Jak czytać mapę
                  </div>
                  <ul className="space-y-2.5 text-muted-foreground">
                    <li><span className="font-medium text-foreground">Węzeł</span> to kampania z miniaturą reklamy; liczba w rogu = zgłoszenia.</li>
                    <li><span className="font-medium text-foreground">Kolor obwódki i pole</span> to sprawca: ta sama osoba lub grupa prowadząca kampanie. Kampanie bez ustalonego sprawcy leżą na zewnętrznym okręgu.</li>
                    <li><span className="font-medium text-foreground">Linia ciągła</span>: ten sam sprawca. <span className="font-medium text-foreground">Przerywana</span>: ten sam program do tworzenia stron (wskazówka, nie dowód).</li>
                    <li>Kliknij węzeł, aby wyróżnić sąsiadów. Przeciągnij, aby przesunąć; <kbd className="rounded border bg-muted px-1 text-[11px]">Ctrl</kbd> + kółko przybliża. Tab i Enter działają z klawiatury.</li>
                  </ul>
                  <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border bg-border text-center">
                    <Stat label={pluralWord(graph.nodes.length, "campaign")} value={graph.nodes.length} />
                    <Stat label={pluralWord(operators.length, ["sprawca", "sprawcy", "sprawców"])} value={operators.length} />
                    <Stat label="powiązania: ten sam sprawca" value={operatorLinks} />
                    <Stat label="powiązania: ten sam program" value={toolkitLinks} />
                  </dl>
                  <p className="text-xs text-muted-foreground">
                    {plural(loose, "campaign")} {pluralWord(loose, ["nie ma", "nie mają", "nie ma"])} ustalonego sprawcy.
                  </p>
                </motion.div>
              )}
            </AnimatePresence>
          </aside>
        </div>
      ) : (
        <div className="space-y-2">
          <p className="text-[13px] text-muted-foreground">
            Co łączy reklamy wybranej kampanii i gdzie to znaleźliśmy: w samej reklamie czy na stronie, do której prowadzi. Najmocniejsze ślady są na górze.
          </p>
          {traceCampaign && <TraceMatrix campaign={traceCampaign} />}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-card px-2 py-2">
      <dd className="text-lg font-semibold tnum">{int(value)}</dd>
      <dt className="text-[11px] text-muted-foreground">{label}</dt>
    </div>
  );
}

function TabButton({ label, active, onClick, children }: { label: string; active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      role="tab"
      aria-label={label}
      aria-selected={active}
      onClick={onClick}
      className={cn(
        "relative inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-[13px] transition-colors",
        active ? "font-medium text-foreground" : "text-muted-foreground hover:text-foreground",
      )}
    >
      {active && <motion.span layoutId="graph-tab" className="absolute inset-0 rounded-md bg-muted" transition={{ duration: 0.2, ease: EASE_OUT }} />}
      <span className="relative inline-flex items-center gap-1.5">
        {children}
      </span>
    </button>
  );
}

function IconButton({ label, onClick, children }: { label: string; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="grid size-8 place-items-center text-muted-foreground transition-colors not-last:border-b hover:bg-surface hover:text-foreground"
    >
      {children}
    </button>
  );
}

/** Accessible combobox: type, move with arrows, Enter selects and centres the node. */
function NodeSearch({ campaigns, onPick }: { campaigns: CampaignSummary[]; onPick: (id: string) => void }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const hits = useMemo(() => {
    const t = q.trim().toLowerCase();
    if (!t) return [];
    return campaigns
      .filter((c) => [c.label, ...c.persons, ...c.chips, c.operator?.label ?? ""].join(" ").toLowerCase().includes(t))
      .slice(0, 8);
  }, [q, campaigns]);
  const pick = (id: string) => {
    onPick(id);
    setOpen(false);
    setQ("");
  };
  return (
    <div className="relative w-full sm:ml-auto sm:w-80">
      <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
      <input
        role="combobox"
        aria-expanded={open && hits.length > 0}
        aria-controls="graph-search-list"
        aria-activedescendant={open && hits[active] ? `gs-${active}` : undefined}
        aria-label="Znajdź kampanię na grafie"
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          setOpen(true);
          setActive(0);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setActive((a) => Math.min(hits.length - 1, a + 1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setActive((a) => Math.max(0, a - 1));
          } else if (e.key === "Enter" && hits[active]) {
            e.preventDefault();
            pick(hits[active].id);
          } else if (e.key === "Escape") {
            setOpen(false);
          }
        }}
        placeholder="Znajdź kampanię, osobę, cechę…"
        className="h-9 w-full rounded-lg border bg-card pr-3 pl-8.5 text-sm shadow-card outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/25"
      />
      {open && q && (
        <ul
          id="graph-search-list"
          role="listbox"
          className="absolute inset-x-0 top-full z-30 mt-1 overflow-hidden rounded-lg border bg-popover p-1 shadow-raised"
        >
          {hits.length === 0 && <li className="px-2.5 py-2 text-[13px] text-muted-foreground">Brak wyników</li>}
          {hits.map((c, i) => (
            <li
              key={c.id}
              id={`gs-${i}`}
              role="option"
              aria-selected={i === active}
              onMouseDown={(e) => {
                e.preventDefault();
                pick(c.id);
              }}
              onMouseEnter={() => setActive(i)}
              className={cn("flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-[13px]", i === active && "bg-muted")}
            >
              <OperatorDot index={c.operator_index} />
              <span className="min-w-0 flex-1 truncate">{plainTitle(c.label)}</span>
              <span className="text-xs text-muted-foreground tnum">{c.size}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
