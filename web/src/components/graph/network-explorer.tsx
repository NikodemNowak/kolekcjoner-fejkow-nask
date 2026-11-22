"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import {
  ArrowRight,
  Link2,
  Maximize,
  Minus,
  MousePointerClick,
  Plus,
  Search,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { OperatorDot } from "@/components/operator-badge";
import { CampaignTitle, plainTitle } from "@/components/campaign-title";
import { EASE_OUT } from "@/components/motion";
import { campaignHref, caseHref, int, num, plural, pluralWord, smartTruncate } from "@/lib/format";
import { operatorColor, tierMeta } from "@/lib/palette";
import { cn } from "@/lib/utils";
import type { NetKind, Network } from "@/lib/types";
import { NetworkGraph, KIND_WORD, linkColor, linkStrokeDashed, type NetworkGraphHandle, type Selection } from "./network-graph";
import { layoutNetwork, type PLink, type PNode } from "./network-layout";

type TraceKind = Exclude<NetKind, "report">;

const KINDS: { kind: TraceKind; label: string; hint: string }[] = [
  { kind: "person", label: "Osoby", hint: "Znane osoby, których wizerunek rozpoznaliśmy (zdjęcie wzorcowe)." },
  { kind: "operator", label: "Sprawcy", hint: "Ta sama osoba lub grupa: wspólne konto, piksel śledzący, reklamodawca." },
  { kind: "brand", label: "Marki", hint: "Loga i nazwy mediów, pod które podszywa się reklama." },
  { kind: "infra", label: "Domeny i konta", hint: "Domeny, serwery, piksele śledzące i konta reklamodawców." },
  { kind: "template", label: "Szablony i pliki", hint: "Te same pliki, nagłówki i wzorce adresów stron." },
];
const DEFAULT_ON: TraceKind[] = ["person", "operator", "brand"];

export function NetworkExplorer({ net, focus }: { net: Network; focus?: string | null }) {
  const layout = useMemo(() => layoutNetwork(net), [net]);
  const campaignById = useMemo(() => new Map(net.campaigns.map((c) => [c.id, c])), [net]);
  const [visible, setVisible] = useState<Set<NetKind>>(() => new Set(DEFAULT_ON));
  const [showPairs, setShowPairs] = useState(true);
  const singles = useMemo(() => net.campaigns.filter((c) => c.size === 1).length, [net]);
  // A large base is mostly single reports: start with campaigns only, singles one click away.
  const [showSingles, setShowSingles] = useState(singles <= 40);
  const [selection, setSelection] = useState<Selection>(null);
  const handle = useRef<NetworkGraphHandle>(null);
  const [box, size] = useSize();
  const panel = useRef<HTMLElement>(null);
  // Phones show the panel under the map: bring it into view after a tap.
  useEffect(() => {
    if (!selection || typeof window === "undefined" || window.innerWidth >= 1024) return;
    const id = setTimeout(() => panel.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 120);
    return () => clearTimeout(id);
  }, [selection]);

  const counts = useMemo(() => {
    const c = new Map<NetKind, number>();
    for (const n of net.nodes) c.set(n.kind, (c.get(n.kind) ?? 0) + 1);
    return c;
  }, [net]);

  const toggle = (kind: TraceKind) => {
    setVisible((prev) => {
      const next = new Set(prev);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });
    setSelection((s) => (s?.type === "node" && layout.byId.get(s.id)?.kind === kind ? null : s));
  };
  // Fit after the visible set changes (new node types widen the picture).
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    const id = setTimeout(() => handle.current?.fit(), 30);
    return () => clearTimeout(id);
  }, [visible, showSingles]);

  const pick = useCallback(
    (s: Selection, center = false) => {
      if (s?.type === "node") {
        const n = layout.byId.get(s.id);
        if (n && n.kind !== "report" && !visible.has(n.kind)) setVisible((v) => new Set([...v, n.kind]));
        if (n?.kind === "report" && n.campaign && campaignById.get(n.campaign)?.size === 1) setShowSingles(true);
      }
      if (s?.type === "campaign" && campaignById.get(s.id)?.size === 1) setShowSingles(true);
      setSelection(s);
      if (center && s && s.type !== "link") setTimeout(() => handle.current?.center(s.id), 40);
    },
    [layout, visible, campaignById],
  );

  // Deep link: /graph?focus=<report, trace or campaign id>.
  const focused = useRef(false);
  useEffect(() => {
    if (focused.current || !focus || size.width === 0) return;
    focused.current = true;
    if (layout.byId.has(focus)) pick({ type: "node", id: focus }, true);
    else if (campaignById.has(focus)) pick({ type: "campaign", id: focus }, true);
  }, [focus, layout, campaignById, pick, size.width]);

  const reports = counts.get("report") ?? 0;
  const multi = net.campaigns.filter((c) => c.size > 1).length;

  return (
    <div className="space-y-3">
      <div className="flex flex-col gap-2 xl:flex-row xl:items-center">
        <div className="flex flex-wrap items-center gap-1.5" role="group" aria-label="Pokaż na mapie">
          <span className="mr-1 text-[13px] text-muted-foreground">Pokaż:</span>
          {KINDS.map(({ kind, label, hint }) => {
            const on = visible.has(kind);
            const n = counts.get(kind) ?? 0;
            return (
              <button
                key={kind}
                type="button"
                aria-pressed={on}
                title={hint}
                disabled={n === 0}
                onClick={() => toggle(kind)}
                className={cn(
                  "inline-flex h-8 items-center gap-1.5 rounded-full border px-2.5 text-[13px] transition-colors disabled:hidden",
                  on ? "border-foreground/25 bg-card font-medium text-foreground shadow-card" : "bg-transparent text-muted-foreground hover:bg-card",
                )}
              >
                <KindGlyph kind={kind} on={on} />
                {label}
                <span className="text-xs text-muted-foreground tnum">{int(n)}</span>
              </button>
            );
          })}
          {singles > 0 && (
            <button
              type="button"
              aria-pressed={showSingles}
              title="Zgłoszenia, które nie mają pary w bazie (kampanie z jednym zgłoszeniem)"
              onClick={() => setShowSingles((v) => !v)}
              className={cn(
                "inline-flex h-8 items-center gap-1.5 rounded-full border px-2.5 text-[13px] transition-colors",
                showSingles ? "border-foreground/25 bg-card font-medium shadow-card" : "text-muted-foreground hover:bg-card",
              )}
            >
              <KindGlyph kind="report" />
              Pojedyncze
              <span className="text-xs text-muted-foreground tnum">{int(singles)}</span>
            </button>
          )}
          <button
            type="button"
            aria-pressed={showPairs}
            title="Linie między zgłoszeniami tej samej kampanii (z powodami podobieństwa)"
            onClick={() => setShowPairs((v) => !v)}
            className={cn(
              "inline-flex h-8 items-center gap-1.5 rounded-full border px-2.5 text-[13px] transition-colors",
              showPairs ? "border-foreground/25 bg-card font-medium shadow-card" : "text-muted-foreground hover:bg-card",
            )}
          >
            <Link2 className="size-3.5" strokeWidth={1.75} aria-hidden />
            Podobieństwo
          </button>
        </div>
        <NodeSearch nodes={layout.nodes} campaigns={net.campaigns} onPick={(s) => pick(s, true)} />
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-3 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="relative overflow-hidden rounded-xl border bg-card shadow-card">
          <div ref={box} className="h-[62vh] min-h-[420px] lg:h-[calc(100dvh-250px)] lg:min-h-[560px] lg:max-h-[860px]">
            {size.width > 0 && size.height > 0 && (
              <NetworkGraph
                ref={handle}
                layout={layout}
                width={size.width}
                height={size.height}
                visible={visible}
                showPairs={showPairs}
                showSingles={showSingles}
                keep={selection?.type === "node" ? selection.id : null}
                selection={selection}
                onSelect={(s) => setSelection(s)}
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
            <IconButton label="Pokaż całość" onClick={() => handle.current?.fit()}>
              <Maximize className="size-4" />
            </IconButton>
          </div>
          <Legend />
        </div>

        <aside ref={panel} className="scroll-mt-16 rounded-xl border bg-card shadow-card lg:max-h-[860px] lg:overflow-y-auto">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div
              key={selection ? `${selection.type}:${selection.type === "link" ? selection.index : selection.id}` : "help"}
              initial={{ opacity: 0, x: 8 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -8 }}
              transition={{ duration: 0.16, ease: EASE_OUT }}
              className="p-4"
            >
              {selection === null ? (
                <Help
                  reports={reports}
                  campaigns={net.campaigns.length}
                  multi={multi}
                  persons={counts.get("person") ?? 0}
                  operators={counts.get("operator") ?? 0}
                  onPick={(s) => pick(s, true)}
                  layoutNodes={layout.nodes}
                />
              ) : (
                <Details
                  selection={selection}
                  net={net}
                  layoutLinks={layout.links}
                  byId={layout.byId}
                  campaignById={campaignById}
                  visible={visible}
                  showPairs={showPairs}
                  onPick={pick}
                  onClose={() => setSelection(null)}
                />
              )}
            </motion.div>
          </AnimatePresence>
        </aside>
      </div>
    </div>
  );
}

function KindGlyph({ kind, on = true, className }: { kind: NetKind; on?: boolean; className?: string }) {
  const stroke = on ? "currentColor" : "var(--muted-foreground)";
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden className={cn("shrink-0", className)}>
      {kind === "report" && <circle cx="7" cy="7" r="5" fill="var(--subtle)" stroke={operatorColor(0)} strokeWidth="2" />}
      {kind === "person" && <circle cx="7" cy="7" r="5.2" fill="var(--card)" stroke={stroke} strokeWidth="1.8" />}
      {kind === "operator" && <circle cx="7" cy="7" r="5.5" fill={on ? operatorColor(0) : "var(--muted-foreground)"} />}
      {kind === "brand" && <rect x="2" y="2" width="10" height="10" rx="3" fill="var(--card)" stroke={on ? "var(--tier-context)" : stroke} strokeWidth="1.8" />}
      {kind === "infra" && <rect x="3.5" y="3.5" width="7" height="7" transform="rotate(45 7 7)" fill="var(--card)" stroke={on ? "var(--tier-operator)" : stroke} strokeWidth="1.8" />}
      {kind === "template" && <rect x="2.5" y="2.5" width="9" height="9" rx="1" fill={on ? "var(--tier-campaign)" : "transparent"} fillOpacity={0.2} stroke={on ? "var(--tier-campaign)" : stroke} strokeWidth="1.6" />}
    </svg>
  );
}

function Legend() {
  const line = (color: string, dashed: string | undefined, width = 2) => (
    <svg width="20" height="6" aria-hidden>
      <line x1="1" y1="3" x2="19" y2="3" stroke={color} strokeWidth={width} strokeDasharray={dashed} strokeLinecap="round" />
    </svg>
  );
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t bg-card px-2.5 py-2 text-xs text-muted-foreground sm:absolute sm:bottom-3 sm:left-3 sm:max-w-[calc(100%-24px)] sm:rounded-lg sm:border sm:bg-card/95 sm:py-1.5 sm:shadow-card sm:backdrop-blur">
      <span className="inline-flex items-center gap-1.5">
        <KindGlyph kind="report" /> zgłoszenie (kolor obwódki = sprawca)
      </span>
      <span className="inline-flex items-center gap-1.5">
        <svg width="16" height="12" aria-hidden><circle cx="8" cy="6" r="5" fill="var(--op-0)" fillOpacity="0.1" stroke="var(--op-0)" strokeOpacity="0.6" strokeDasharray="3 2" /></svg>
        kampania
      </span>
      <span className="hidden h-3 w-px bg-border sm:block" />
      <span className="inline-flex items-center gap-1.5">{line("var(--tier-campaign)", undefined)} ta sama kampania</span>
      <span className="inline-flex items-center gap-1.5">{line("var(--tier-operator)", undefined)} ten sam sprawca</span>
      <span className="inline-flex items-center gap-1.5">{line("var(--tier-toolkit)", "5 4")} wskazówka</span>
      <span className="inline-flex items-center gap-1.5">{line("var(--tier-context)", "5 4", 1.5)} kontekst (osoba, marka)</span>
    </div>
  );
}

function Help({
  reports,
  campaigns,
  multi,
  persons,
  operators,
  onPick,
  layoutNodes,
}: {
  reports: number;
  campaigns: number;
  multi: number;
  persons: number;
  operators: number;
  onPick: (s: Selection) => void;
  layoutNodes: PNode[];
}) {
  const topPersons = layoutNodes.filter((n) => n.kind === "person").sort((a, b) => b.count - a.count).slice(0, 4);
  return (
    <div className="space-y-4 text-[13px]">
      <div className="flex items-center gap-2 font-medium">
        <MousePointerClick className="size-4 text-muted-foreground" strokeWidth={1.75} />
        Jak czytać sieć powiązań
      </div>
      <ol className="list-decimal space-y-2 pl-4 text-muted-foreground marker:text-foreground/60">
        <li>
          <span className="font-medium text-foreground">Kółko z miniaturą</span> to jedno zgłoszenie. Zgłoszenia jednej kampanii leżą
          razem w podpisanym, przerywanym okręgu.
        </li>
        <li>
          <span className="font-medium text-foreground">Zdjęcia osób, loga i litery sprawców</span> to wspólne ślady. Linia prowadzi do
          każdego zgłoszenia, w którym ślad znaleźliśmy.
        </li>
        <li>
          <span className="font-medium text-foreground">Kliknij linię</span>, a panel wyjaśni, dlaczego elementy są połączone.
          Kliknij kółko lub okrąg kampanii, by zobaczyć szczegóły.
        </li>
        <li>
          Sama osoba czy marka <span className="font-medium text-foreground">nie łączy</span> reklam w kampanię: o tym decydują wspólne
          pliki, konta, piksele i domeny.
        </li>
      </ol>
      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border bg-border text-center">
        <Stat label={pluralWord(reports, "report")} value={reports} />
        <Stat label={`${pluralWord(campaigns, "campaign")}, w tym ${int(multi)} z wieloma zgłoszeniami`} value={campaigns} />
        <Stat label={pluralWord(persons, ["rozpoznana osoba", "rozpoznane osoby", "rozpoznanych osób"])} value={persons} />
        <Stat label={pluralWord(operators, ["sprawca", "sprawcy", "sprawców"])} value={operators} />
      </dl>
      {topPersons.length > 0 && (
        <div>
          <div className="mb-1.5 text-xs font-medium text-muted-foreground">Najczęściej wykorzystywane wizerunki</div>
          <ul className="space-y-1">
            {topPersons.map((p) => (
              <li key={p.id}>
                <button type="button" onClick={() => onPick({ type: "node", id: p.id })} className="flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left hover:bg-surface">
                  <Avatar node={p} size={28} />
                  <span className="min-w-0 flex-1 truncate">{p.label}</span>
                  <span className="text-xs text-muted-foreground tnum">{plural(p.count, "report")}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="text-xs text-muted-foreground">
        Przeciągnij, aby przesunąć; <kbd className="rounded border bg-muted px-1 text-[11px]">Ctrl</kbd> + kółko lub gest
        szczypania przybliża.
      </p>
    </div>
  );
}

/* eslint-disable @next/next/no-img-element */
function Avatar({ node, size = 40 }: { node: PNode; size?: number }) {
  const round = node.kind === "person" || node.kind === "report" || node.kind === "operator";
  if (node.kind === "operator")
    return (
      <span
        className="grid shrink-0 place-items-center rounded-full font-bold text-white"
        style={{ width: size, height: size, background: operatorColor(node.group_index), fontSize: size * 0.45 }}
      >
        {node.label.split(" ").at(-1)}
      </span>
    );
  if (!node.image)
    return (
      <span
        className={cn("grid shrink-0 place-items-center border bg-subtle text-muted-foreground", round ? "rounded-full" : "rounded-md")}
        style={{ width: size, height: size }}
      >
        <KindGlyph kind={node.kind} />
      </span>
    );
  const src = `${node.image}${node.image.includes("?") ? "&" : "?"}w=${size * 2}`;
  return (
    <img
      src={src}
      alt=""
      width={size}
      height={size}
      className={cn(
        "shrink-0 border bg-subtle",
        round ? "rounded-full" : "rounded-md",
        node.kind === "brand" ? "object-contain p-0.5" : "object-cover object-top",
      )}
      style={{ width: size, height: size, borderColor: node.kind === "report" ? operatorColor(node.group_index) : undefined }}
    />
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-card px-2 py-2">
      <dd className="text-lg font-semibold tnum">{int(value)}</dd>
      <dt className="text-[11px] leading-tight text-muted-foreground">{label}</dt>
    </div>
  );
}

function Details({
  selection,
  net,
  layoutLinks,
  byId,
  campaignById,
  visible,
  showPairs,
  onPick,
  onClose,
}: {
  selection: NonNullable<Selection>;
  net: Network;
  layoutLinks: PLink[];
  byId: Map<string, PNode>;
  campaignById: Map<string, Network["campaigns"][number]>;
  visible: Set<NetKind>;
  showPairs: boolean;
  onPick: (s: Selection, center?: boolean) => void;
  onClose: () => void;
}) {
  const close = (
    <button type="button" onClick={onClose} className="rounded p-0.5 text-muted-foreground hover:bg-muted hover:text-foreground" aria-label="Zamknij szczegóły">
      <X className="size-4" />
    </button>
  );
  if (selection.type === "link") {
    const l = layoutLinks[selection.index];
    if (!l) return null;
    return <LinkWhy link={l} close={close} campaignById={campaignById} onPick={onPick} />;
  }
  if (selection.type === "campaign") {
    const c = campaignById.get(selection.id);
    if (!c) return null;
    const members = net.nodes.filter((n) => n.campaign === c.id).map((n) => byId.get(n.id)!).filter(Boolean);
    const memberIds = new Set(members.map((m) => m.id));
    const traces = new Map<string, PNode>();
    for (const l of layoutLinks) if (memberIds.has(l.a.id) && l.kind !== "pair") traces.set(l.b.id, l.b);
    const persons = [...traces.values()].filter((n) => n.kind === "person");
    return (
      <div className="space-y-4">
        <div className="flex items-start justify-between gap-2">
          <div className="text-xs font-medium text-muted-foreground">
            {c.size > 1 ? `Kampania · ${plural(c.size, "report")}` : "Kampania z jednym zgłoszeniem"}
          </div>
          {close}
        </div>
        <h3 className="text-[15px] leading-snug font-semibold text-pretty">
          <CampaignTitle text={c.label} />
        </h3>
        <div className="flex items-center gap-1.5 text-xs">
          <OperatorDot index={c.group_index} />
          {c.operator ?? <span className="text-muted-foreground">sprawca nieustalony</span>}
        </div>
        {persons.length > 0 && (
          <Section title="Wykorzystane wizerunki">
            <div className="flex flex-wrap gap-1.5">
              {persons.map((p) => (
                <button key={p.id} type="button" onClick={() => onPick({ type: "node", id: p.id }, true)} className="inline-flex items-center gap-1.5 rounded-full border py-0.5 pr-2 pl-0.5 text-xs hover:bg-surface">
                  <Avatar node={p} size={22} />
                  {p.label}
                </button>
              ))}
            </div>
          </Section>
        )}
        <Section title={`Zgłoszenia (${int(members.length)})`}>
          <ul className="space-y-1">
            {members.map((m) => (
              <li key={m.id}>
                <button type="button" onClick={() => onPick({ type: "node", id: m.id }, true)} className="flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left text-[13px] hover:bg-surface">
                  <Avatar node={m} size={28} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate">{m.label}</span>
                    {m.detail && <span className="block truncate font-mono text-[11px] text-muted-foreground">{m.detail}</span>}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </Section>
        <div className="border-t pt-4">
          <Button asChild size="sm">
            <Link href={campaignHref(c.id)}>
              Otwórz kampanię <ArrowRight className="size-3.5" />
            </Link>
          </Button>
        </div>
      </div>
    );
  }

  const n = byId.get(selection.id);
  if (!n) return null;
  const own = layoutLinks.filter(
    (l) => (l.a.id === n.id || l.b.id === n.id) && (showPairs || l.kind !== "pair"),
  );
  if (n.kind === "report") {
    const c = n.campaign ? campaignById.get(n.campaign) : undefined;
    const groups: { title: string; items: PLink[] }[] = [
      { title: "Podobne zgłoszenia", items: own.filter((l) => l.kind === "pair") },
      { title: "Sprawca", items: own.filter((l) => l.kind === "operator") },
      { title: "Osoby", items: own.filter((l) => l.b.kind === "person") },
      { title: "Marki", items: own.filter((l) => l.b.kind === "brand") },
      { title: "Domeny i konta", items: own.filter((l) => l.b.kind === "infra") },
      { title: "Szablony i pliki", items: own.filter((l) => l.b.kind === "template") },
    ];
    return (
      <div className="space-y-4">
        <div className="flex items-start justify-between gap-2">
          <div className="text-xs font-medium text-muted-foreground">Zgłoszenie</div>
          {close}
        </div>
        <div className="flex items-center gap-3">
          <Avatar node={n} size={56} />
          <div className="min-w-0">
            <h3 className="text-[15px] font-semibold">{n.label}</h3>
            {n.detail && <div className="truncate font-mono text-xs text-muted-foreground">{n.detail}</div>}
          </div>
        </div>
        {c && (
          <button type="button" onClick={() => onPick({ type: "campaign", id: c.id }, true)} className="block w-full rounded-lg border bg-surface px-3 py-2 text-left text-[13px] hover:bg-muted">
            <span className="block text-xs text-muted-foreground">Należy do kampanii · {plural(c.size, "report")}</span>
            <span className="line-clamp-2 font-medium">
              <CampaignTitle text={c.label} />
            </span>
          </button>
        )}
        <p className="text-xs text-muted-foreground">Kliknij pozycję, aby zobaczyć, dlaczego jest połączona.</p>
        {groups
          .filter((g) => g.items.length > 0)
          .map((g) => (
            <Section key={g.title} title={`${g.title} (${int(g.items.length)})`}>
              <ul className="space-y-0.5">
                {g.items.slice(0, 12).map((l) => {
                  const other = l.a.id === n.id ? l.b : l.a;
                  const hidden = other.kind !== "report" && !visible.has(other.kind);
                  return (
                    <li key={l.i}>
                      <button type="button" onClick={() => onPick({ type: "link", index: l.i })} className="flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left text-[13px] hover:bg-surface">
                        <Avatar node={other} size={24} />
                        <span className="min-w-0 flex-1">
                          <span className={cn("block truncate", other.mono && "font-mono text-xs")}>{smartTruncate(plainTitle(other.label), 60)}</span>
                          <span className="block truncate text-[11px] text-muted-foreground">
                            {linkSummary(l)}
                            {hidden && " · ukryte na mapie"}
                          </span>
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </Section>
          ))}
        <div className="flex flex-wrap gap-2 border-t pt-4">
          <Button asChild size="sm">
            <Link href={caseHref(n.id)}>
              Otwórz zgłoszenie <ArrowRight className="size-3.5" />
            </Link>
          </Button>
          {c && (
            <Button asChild size="sm" variant="outline">
              <Link href={campaignHref(c.id)}>Kampania</Link>
            </Button>
          )}
        </div>
      </div>
    );
  }

  // A trace: person, brand, operator, domain or template.
  const reports = own.map((l) => (l.a.id === n.id ? l.b : l.a)).filter((r) => r.kind === "report");
  const byCampaign = new Map<string, PNode[]>();
  for (const r of reports) if (r.campaign) byCampaign.set(r.campaign, [...(byCampaign.get(r.campaign) ?? []), r]);
  const tier = n.kind === "operator" ? tierMeta("operator") : tierMeta(n.tier);
  const operatorReasons = n.kind === "operator" ? own.find((l) => l.reasons.length)?.reasons ?? [] : [];
  const conf = own.map((l) => l.confidence ?? 0).filter((v) => v > 0);
  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-2">
        <div className="text-xs font-medium text-muted-foreground">{n.kind === "operator" ? "Sprawca" : n.detail ?? KIND_WORD[n.kind]}</div>
        {close}
      </div>
      <div className="flex items-center gap-3">
        <Avatar node={n} size={n.kind === "person" ? 64 : 48} />
        <div className="min-w-0">
          <h3 className={cn("text-[15px] font-semibold break-words", n.mono && "font-mono text-sm")}>{plainTitle(n.label)}</h3>
          <div className="text-xs text-muted-foreground">
            {inReports(reports.length)} · {inCampaigns(byCampaign.size)}
          </div>
        </div>
      </div>
      <div className="rounded-lg border px-3 py-2 text-xs" style={{ borderColor: tier.color }}>
        <div className="font-semibold" style={{ color: tier.color }}>
          {tier.label}
        </div>
        <div className="text-muted-foreground">
          {n.kind === "person"
            ? "Wizerunek tej osoby występuje w wielu niezależnych oszustwach. Sama osoba nie wystarcza do połączenia reklam w kampanię: decydują wspólne pliki, konta, piksele i domeny."
            : tier.hint}
        </div>
        {n.kind === "person" && conf.length > 0 && (
          <div className="mt-1 text-muted-foreground">
            Podobieństwo twarzy do zdjęcia wzorcowego: do <span className="font-medium text-foreground tnum">{num(Math.max(...conf))}</span>
          </div>
        )}
      </div>
      {operatorReasons.length > 0 && (
        <Section title="Co łączy zgłoszenia tego sprawcy">
          <ul className="space-y-1 text-[13px]">
            {operatorReasons.map((r) => (
              <li key={r} className="break-words">· {r}</li>
            ))}
          </ul>
        </Section>
      )}
      <Section title={`Kampanie (${int(byCampaign.size)})`}>
        <ul className="space-y-1">
          {[...byCampaign.entries()]
            .sort((a, b) => b[1].length - a[1].length)
            .map(([cid, rs]) => {
              const c = campaignById.get(cid);
              return (
                <li key={cid}>
                  <button type="button" onClick={() => onPick({ type: "campaign", id: cid }, true)} className="flex w-full items-start gap-2 rounded-md px-1.5 py-1 text-left text-[13px] hover:bg-surface">
                    <OperatorDot index={c?.group_index ?? null} className="mt-1.5" />
                    <span className="min-w-0 flex-1">
                      <span className="line-clamp-2">{c ? plainTitle(c.label) : "Kampania"}</span>
                      <span className="text-[11px] text-muted-foreground">
                        {int(rs.length)} z {int(c?.size ?? rs.length)} {(c?.size ?? rs.length) === 1 ? "zgłoszenia" : "zgłoszeń"}
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
        </ul>
      </Section>
    </div>
  );
}

/** Locative counts: "w 1 zgłoszeniu", "w 5 zgłoszeniach". */
export const inReports = (n: number) => `w ${int(n)} ${n === 1 ? "zgłoszeniu" : "zgłoszeniach"}`;
export const inCampaigns = (n: number) => `w ${int(n)} ${n === 1 ? "kampanii" : "kampaniach"}`;

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 text-xs font-medium text-muted-foreground">{title}</div>
      {children}
    </div>
  );
}

function linkSummary(l: PLink) {
  if (l.kind === "pair") return l.reasons.slice(0, 2).join(", ") || tierMeta(l.tier).label.toLowerCase();
  if (l.kind === "operator") return "ten sam sprawca";
  const parts = [l.where, l.confidence ? `podobieństwo ${num(l.confidence)}` : null].filter(Boolean);
  return parts.join(", ") || tierMeta(l.tier).label.toLowerCase();
}

function LinkWhy({
  link: l,
  close,
  campaignById,
  onPick,
}: {
  link: PLink;
  close: React.ReactNode;
  campaignById: Map<string, Network["campaigns"][number]>;
  onPick: (s: Selection, center?: boolean) => void;
}) {
  const tier = l.kind === "operator" ? tierMeta("operator") : tierMeta(l.tier);
  const end = (n: PNode) => (
    <button type="button" onClick={() => onPick({ type: "node", id: n.id }, true)} className="flex w-full items-center gap-2 rounded-md px-1.5 py-1 text-left text-[13px] hover:bg-surface">
      <Avatar node={n} size={32} />
      <span className="min-w-0 flex-1">
        <span className="block text-[11px] text-muted-foreground">{n.kind === "report" ? "Zgłoszenie" : n.detail ?? KIND_WORD[n.kind]}</span>
        <span className={cn("block truncate font-medium", n.mono && "font-mono text-xs")}>{smartTruncate(plainTitle(n.label), 60)}</span>
        {n.kind === "report" && n.campaign && (
          <span className="block truncate text-[11px] text-muted-foreground">{plainTitle(campaignById.get(n.campaign)?.label ?? "")}</span>
        )}
      </span>
    </button>
  );
  let why: string[] = [];
  if (l.kind === "pair") why = l.reasons;
  else if (l.kind === "operator") why = l.reasons.length ? l.reasons : ["wspólne ślady sprawcy"];
  else {
    const what = l.b.kind === "person" ? "Wizerunek tej osoby rozpoznano" : l.b.kind === "brand" ? "Markę rozpoznano" : `${l.b.detail ?? "Ślad"} znaleziono`;
    why = [`${what} ${l.where ?? "w materiałach zgłoszenia"}.`];
    if (l.confidence) why.push(`${l.b.kind === "person" ? "Podobieństwo twarzy do zdjęcia wzorcowego" : "Pewność rozpoznania"}: ${num(l.confidence)}.`);
  }
  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-2">
        <div className="text-xs font-medium text-muted-foreground">Dlaczego połączone</div>
        {close}
      </div>
      <div className="space-y-1">
        {end(l.a)}
        <div className="flex items-center gap-2 pl-5">
          <svg width="22" height="18" aria-hidden>
            <line x1="11" y1="0" x2="11" y2="18" stroke={linkColor(l)} strokeWidth="2.5" strokeDasharray={linkStrokeDashed(l) ? "4 3" : undefined} />
          </svg>
          <span className="text-xs font-medium" style={{ color: tier.color }}>
            {l.kind === "pair" ? `podobieństwo ${num(l.strength)}` : tier.label}
          </span>
        </div>
        {end(l.b)}
      </div>
      <Section title="Powód">
        <ul className="space-y-1 text-[13px]">
          {why.map((w) => (
            <li key={w} className="break-words">
              · {w}
            </li>
          ))}
        </ul>
      </Section>
      <div className="rounded-lg border px-3 py-2 text-xs" style={{ borderColor: tier.color }}>
        <div className="font-semibold" style={{ color: tier.color }}>
          {tier.label}
        </div>
        <div className="text-muted-foreground">
          {l.kind === "pair"
            ? l.tier === "campaign"
              ? "Zgłoszenia mają wspólne mocne ślady, dlatego należą do tej samej kampanii."
              : "Różne kampanie, ale wspólne ślady wskazują na tę samą osobę lub grupę."
            : l.b.kind === "person"
              ? "Osoba to kontekst: pomaga się zorientować, ale sama nie łączy reklam w kampanię."
              : tier.hint}
        </div>
      </div>
    </div>
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

/** Search over every node and campaign; picking a hidden trace type turns it on. */
function NodeSearch({
  nodes,
  campaigns,
  onPick,
}: {
  nodes: PNode[];
  campaigns: Network["campaigns"];
  onPick: (s: Selection) => void;
}) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  type Hit = { key: string; label: string; sub: string; sel: NonNullable<Selection>; node?: PNode; op?: number | null };
  const hits = useMemo<Hit[]>(() => {
    const t = q.trim().toLowerCase();
    if (!t) return [];
    const out: Hit[] = [];
    for (const c of campaigns)
      if (plainTitle(c.label).toLowerCase().includes(t))
        out.push({ key: `c:${c.id}`, label: plainTitle(c.label), sub: `kampania · ${plural(c.size, "report")}`, sel: { type: "campaign", id: c.id }, op: c.group_index });
    for (const n of nodes)
      if (`${n.label} ${n.detail ?? ""}`.toLowerCase().includes(t))
        out.push({ key: n.id, label: plainTitle(n.label), sub: n.kind === "report" ? `zgłoszenie${n.detail ? ` · ${n.detail}` : ""}` : `${(n.detail ?? KIND_WORD[n.kind]).toLowerCase()} · ${plural(n.count, "report")}`, sel: { type: "node", id: n.id }, node: n });
    const rank = (h: Hit) => (h.node?.kind === "person" ? 0 : h.sel.type === "campaign" ? 1 : h.node?.kind === "report" ? 3 : 2);
    return out.sort((a, b) => rank(a) - rank(b)).slice(0, 10);
  }, [q, nodes, campaigns]);
  const pick = (h: Hit) => {
    onPick(h.sel);
    setOpen(false);
    setQ("");
  };
  return (
    <div className="relative w-full xl:ml-auto xl:w-60">
      <Search className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
      <input
        role="combobox"
        aria-expanded={open && hits.length > 0}
        aria-controls="net-search-list"
        aria-activedescendant={open && hits[active] ? `ns-${active}` : undefined}
        aria-label="Szukaj na mapie"
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
            pick(hits[active]);
          } else if (e.key === "Escape") {
            setOpen(false);
          }
        }}
        placeholder="Szukaj osoby, kampanii…"
        className="h-9 w-full rounded-lg border bg-card pr-3 pl-8.5 text-sm shadow-card outline-none placeholder:text-muted-foreground focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/25"
      />
      {open && q && (
        <ul id="net-search-list" role="listbox" className="absolute inset-x-0 top-full z-30 mt-1 overflow-hidden rounded-lg border bg-popover p-1 shadow-raised">
          {hits.length === 0 && <li className="px-2.5 py-2 text-[13px] text-muted-foreground">Brak wyników</li>}
          {hits.map((h, i) => (
            <li
              key={h.key}
              id={`ns-${i}`}
              role="option"
              aria-selected={i === active}
              onMouseDown={(e) => {
                e.preventDefault();
                pick(h);
              }}
              onMouseEnter={() => setActive(i)}
              className={cn("flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-[13px]", i === active && "bg-muted")}
            >
              {h.node ? <Avatar node={h.node} size={22} /> : <OperatorDot index={h.op ?? null} className="mx-[7px]" />}
              <span className="min-w-0 flex-1">
                <span className="block truncate">{h.label}</span>
                <span className="block truncate text-[11px] text-muted-foreground">{h.sub}</span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
