"use client";

import { select } from "d3-selection";
import { zoom as d3zoom, zoomIdentity, type ZoomBehavior, type ZoomTransform } from "d3-zoom";
import "d3-transition";
import { forwardRef, memo, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { plainTitle } from "@/components/campaign-title";
import { smartTruncate } from "@/lib/format";
import { operatorColor, tierMeta } from "@/lib/palette";
import type { NetKind } from "@/lib/types";
import type { Hull, NetLayout, PLink, PNode } from "./network-layout";

export type NetworkGraphHandle = {
  fit: (animate?: boolean) => void;
  zoomBy: (factor: number) => void;
  center: (id: string) => void;
};

export type Selection =
  | { type: "node"; id: string }
  | { type: "link"; index: number }
  | { type: "campaign"; id: string }
  | null;

type Props = {
  layout: NetLayout;
  width: number;
  height: number;
  visible: Set<NetKind>;
  showPairs: boolean;
  /** Show campaigns with a single report. */
  showSingles: boolean;
  /** A node that stays visible whatever the filters (the current selection). */
  keep: string | null;
  selection: Selection;
  onSelect: (s: Selection) => void;
};

type Box = [number, number, number, number];
const overlaps = (a: Box, b: Box) => a[0] < b[0] + b[2] && b[0] < a[0] + a[2] && a[1] < b[1] + b[3] && b[1] < a[1] + a[3];

let measureCtx: CanvasRenderingContext2D | null = null;
function measure(text: string, size: number, weight: number) {
  if (typeof document === "undefined") return text.length * size * 0.55;
  measureCtx ??= document.createElement("canvas").getContext("2d");
  if (!measureCtx) return text.length * size * 0.55;
  measureCtx.font = `${weight} ${size}px ${getComputedStyle(document.body).fontFamily}`;
  return measureCtx.measureText(text).width;
}

export function linkColor(l: { kind: string; tier: string | null; a?: PNode }) {
  if (l.kind === "operator") return operatorColor(l.a?.group_index);
  return tierMeta(l.tier).color;
}

export const NetworkGraph = forwardRef<NetworkGraphHandle, Props>(function NetworkGraph(
  { layout, width, height, visible, showPairs, showSingles, keep, selection, onSelect },
  ref,
) {
  const svgRef = useRef<SVGSVGElement>(null);
  const sceneRef = useRef<SVGGElement>(null);
  const zoomRef = useRef<ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const transform = useRef<ZoomTransform>(zoomIdentity);
  const [t, setT] = useState<ZoomTransform>(zoomIdentity);
  const frame = useRef(0);
  const [hover, setHover] = useState<string | null>(null);
  const [tip, setTip] = useState<{ x: number; y: number; node: PNode } | null>(null);

  // Single-report campaigns can be hidden on a large base; traces left without a visible report go too.
  const shownIds = useMemo(() => {
    const size = new Map(layout.hulls.map((h) => [h.campaign.id, h.members.length]));
    const ids = new Set<string>();
    for (const n of layout.nodes)
      if (n.kind === "report" && (showSingles || (size.get(n.campaign ?? "") ?? 1) > 1 || n.id === keep)) ids.add(n.id);
    for (const l of layout.links)
      if (ids.has(l.a.id) && l.b.kind !== "report" && visible.has(l.b.kind)) ids.add(l.b.id);
    if (keep && layout.byId.has(keep)) ids.add(keep);
    return ids;
  }, [layout, visible, showSingles, keep]);
  const shown = useCallback((n: PNode) => shownIds.has(n.id), [shownIds]);
  const links = useMemo(
    () => layout.links.filter((l) => shown(l.a) && shown(l.b) && (showPairs || l.kind !== "pair")),
    [layout, shown, showPairs],
  );
  const nodes = useMemo(() => layout.nodes.filter(shown), [layout, shown]);
  const hulls = useMemo(() => layout.hulls.filter((h) => h.members.some((m) => shownIds.has(m.id))), [layout, shownIds]);
  const neighbours = useMemo(() => {
    const map = new Map<string, Set<string>>();
    for (const l of links) {
      if (!map.has(l.a.id)) map.set(l.a.id, new Set());
      if (!map.has(l.b.id)) map.set(l.b.id, new Set());
      map.get(l.a.id)!.add(l.b.id);
      map.get(l.b.id)!.add(l.a.id);
    }
    return map;
  }, [links]);

  // What is lit: the hovered node, else the selection, with its direct neighbours.
  const focus = hover ?? (selection?.type === "node" ? selection.id : null);
  const lit = useMemo(() => {
    if (focus) return new Set([focus, ...(neighbours.get(focus) ?? [])]);
    if (selection?.type === "link") {
      const l = layout.links[selection.index];
      return l ? new Set([l.a.id, l.b.id]) : null;
    }
    if (selection?.type === "campaign") {
      const h = layout.hulls.find((x) => x.campaign.id === selection.id);
      if (!h) return null;
      const ids = new Set(h.members.map((m) => m.id));
      for (const m of h.members) for (const n of neighbours.get(m.id) ?? []) ids.add(n);
      return ids;
    }
    return null;
  }, [focus, neighbours, selection, layout]);

  const fitTransform = useCallback(() => {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const n of nodes) {
      x0 = Math.min(x0, n.x - n.r);
      y0 = Math.min(y0, n.y - n.r);
      x1 = Math.max(x1, n.x + n.r);
      y1 = Math.max(y1, n.y + n.r);
    }
    for (const h of hulls) {
      x0 = Math.min(x0, h.x - h.r);
      y0 = Math.min(y0, h.y - h.r - 14);
      x1 = Math.max(x1, h.x + h.r);
      y1 = Math.max(y1, h.y + h.r);
    }
    if (!Number.isFinite(x0)) return zoomIdentity.translate(width / 2, height / 2);
    const pad = width < 640 ? 14 : 30;
    const k = Math.min(2, Math.min((width - pad * 2) / (x1 - x0), (height - pad * 2) / (y1 - y0)));
    return zoomIdentity.translate(width / 2 - ((x0 + x1) / 2) * k, height / 2 - ((y0 + y1) / 2) * k).scale(k);
  }, [nodes, hulls, width, height]);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const z = d3zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.15, 6])
      .filter((event: Event) => {
        if (event.type === "wheel") return (event as WheelEvent).ctrlKey || (event as WheelEvent).metaKey;
        return !(event as MouseEvent).button;
      })
      .on("zoom", (e) => {
        transform.current = e.transform;
        sceneRef.current?.setAttribute("transform", e.transform.toString());
        // Labels live in screen space: refresh them at most once per frame.
        cancelAnimationFrame(frame.current);
        frame.current = requestAnimationFrame(() => setT(e.transform));
        setTip(null);
      });
    zoomRef.current = z;
    const sel = select(svg);
    sel.call(z).on("dblclick.zoom", null);
    sel.call(z.transform, fitTransform());
    return () => {
      sel.on(".zoom", null);
    };
    // Fit once per layout and size; toggles fit through the handle.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layout, width, height]);

  useImperativeHandle(
    ref,
    () => ({
      fit: (animate = true) => {
        const svg = svgRef.current;
        if (!svg || !zoomRef.current) return;
        const s = select(svg);
        if (animate) s.transition().duration(350).call(zoomRef.current.transform, fitTransform());
        else s.call(zoomRef.current.transform, fitTransform());
      },
      zoomBy: (factor) => {
        const svg = svgRef.current;
        if (!svg || !zoomRef.current) return;
        select(svg).transition().duration(200).call(zoomRef.current.scaleBy, factor);
      },
      center: (id) => {
        const svg = svgRef.current;
        const node = layout.byId.get(id);
        const hull = layout.hulls.find((h) => h.campaign.id === id);
        const target = node ?? hull;
        if (!svg || !zoomRef.current || !target) return;
        const k = Math.max(transform.current.k, hull && !node ? Math.min(2, (Math.min(width, height) * 0.35) / hull.r) : 1.4);
        const to = zoomIdentity.translate(width / 2 - target.x * k, height / 2 - target.y * k).scale(k);
        select(svg).transition().duration(400).call(zoomRef.current.transform, to);
      },
    }),
    [fitTransform, layout, width, height],
  );

  const selectedLink = selection?.type === "link" ? selection.index : null;
  const selectedNode = selection?.type === "node" ? selection.id : null;
  const selectedCampaign = selection?.type === "campaign" ? selection.id : null;

  return (
    <div className="relative size-full">
      <svg
        ref={svgRef}
        width={width}
        height={height}
        role="group"
        aria-label="Sieć powiązań: zgłoszenia zgrupowane w kampanie oraz wspólne ślady (osoby, marki, sprawcy, domeny, szablony)"
        className="block cursor-grab touch-none select-none active:cursor-grabbing"
        onClick={(e) => {
          if (e.target === svgRef.current) onSelect(null);
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape") onSelect(null);
        }}
      >
        <defs>
          <clipPath id="net-circle" clipPathUnits="objectBoundingBox">
            <circle cx={0.5} cy={0.5} r={0.5} />
          </clipPath>
          <clipPath id="net-square" clipPathUnits="objectBoundingBox">
            <rect width={1} height={1} rx={0.18} />
          </clipPath>
        </defs>
        <g ref={sceneRef}>
          <Hulls hulls={hulls} lit={lit} selected={selectedCampaign} onSelect={onSelect} />
          <Links links={links} lit={lit} focus={focus} selected={selectedLink} onSelect={onSelect} />
          <Nodes
            nodes={nodes}
            lit={lit}
            selected={selectedNode}
            onSelect={onSelect}
            onHover={(n, e) => {
              setHover(n?.id ?? null);
              if (!n || !e) return setTip(null);
              const box = svgRef.current?.getBoundingClientRect();
              if (box) setTip({ x: e.clientX - box.left, y: e.clientY - box.top, node: n });
            }}
          />
        </g>
        <Labels
          layout={layout}
          nodes={nodes}
          t={t}
          width={width}
          height={height}
          lit={lit}
          focus={focus ?? selectedNode}
          selectedCampaign={selectedCampaign}
          onSelect={onSelect}
        />
      </svg>
      {tip && <Tooltip tip={tip} width={width} />}
    </div>
  );
});

const KIND_WORD: Record<NetKind, string> = {
  report: "Zgłoszenie",
  person: "Osoba",
  brand: "Marka",
  infra: "Domena lub konto",
  template: "Szablon lub plik",
  operator: "Sprawca",
};

function Tooltip({ tip, width }: { tip: { x: number; y: number; node: PNode }; width: number }) {
  const n = tip.node;
  const left = Math.min(Math.max(8, tip.x + 14), width - 248);
  return (
    <div
      className="pointer-events-none absolute z-20 w-max max-w-60 rounded-md border bg-popover px-2.5 py-1.5 text-xs shadow-raised"
      style={{ left, top: tip.y + 14 }}
    >
      <div className="text-[11px] text-muted-foreground">{n.kind === "report" ? KIND_WORD.report : n.detail ?? KIND_WORD[n.kind]}</div>
      <div className="font-medium break-words">{smartTruncate(plainTitle(n.label), 80)}</div>
      {n.kind !== "report" && (
        <div className="text-muted-foreground tnum">
          w {n.count.toLocaleString("pl-PL")} {n.count === 1 ? "zgłoszeniu" : "zgłoszeniach"}
        </div>
      )}
      {n.kind === "report" && n.detail && <div className="font-mono text-[11px] text-muted-foreground">{n.detail}</div>}
    </div>
  );
}

const Hulls = memo(function Hulls({
  hulls,
  lit,
  selected,
  onSelect,
}: {
  hulls: Hull[];
  lit: Set<string> | null;
  selected: string | null;
  onSelect: (s: Selection) => void;
}) {
  return (
    <g>
      {hulls.map((h) => {
        const on = !lit || h.members.some((m) => lit.has(m.id));
        const multi = h.members.length > 1;
        const color = operatorColor(h.campaign.group_index);
        return (
          <circle
            key={h.campaign.id}
            cx={h.x}
            cy={h.y}
            r={h.r}
            fill={color}
            fillOpacity={on ? (multi ? 0.08 : 0.04) : 0.02}
            stroke={color}
            strokeOpacity={selected === h.campaign.id ? 0.9 : on ? (multi ? 0.45 : 0.2) : 0.1}
            strokeWidth={selected === h.campaign.id ? 2 : 1}
            strokeDasharray={multi ? "4 3" : undefined}
            vectorEffect="non-scaling-stroke"
            className="cursor-pointer transition-[fill-opacity,stroke-opacity] duration-200"
            onClick={(e) => {
              e.stopPropagation();
              onSelect({ type: "campaign", id: h.campaign.id });
            }}
          />
        );
      })}
    </g>
  );
});

const Links = memo(function Links({
  links,
  lit,
  focus,
  selected,
  onSelect,
}: {
  links: PLink[];
  lit: Set<string> | null;
  focus: string | null;
  selected: number | null;
  onSelect: (s: Selection) => void;
}) {
  return (
    <g>
      {links.map((l) => {
        const touches = focus ? l.a.id === focus || l.b.id === focus : lit ? lit.has(l.a.id) && lit.has(l.b.id) : true;
        const isSel = selected === l.i;
        const strong = l.kind === "pair" || l.kind === "operator";
        const dashed = l.kind === "operator" || l.tier === "context" || l.tier === "toolkit";
        const base = l.kind === "pair" ? 0.75 : l.kind === "operator" ? 0.45 : 0.4;
        return (
          <g key={l.i}>
            <line
              x1={l.a.x}
              y1={l.a.y}
              x2={l.b.x}
              y2={l.b.y}
              stroke={linkColor(l)}
              strokeWidth={isSel ? 3.5 : strong ? 1.8 : 1.1}
              strokeDasharray={dashed ? (l.kind === "operator" ? "2 4" : "5 4") : undefined}
              strokeLinecap="round"
              vectorEffect="non-scaling-stroke"
              opacity={isSel ? 1 : touches ? (lit ? 0.95 : base) : 0.05}
              className="pointer-events-none transition-opacity duration-200"
            />
            <line
              x1={l.a.x}
              y1={l.a.y}
              x2={l.b.x}
              y2={l.b.y}
              stroke="transparent"
              strokeWidth={10}
              vectorEffect="non-scaling-stroke"
              className="cursor-pointer"
              onClick={(e) => {
                e.stopPropagation();
                onSelect({ type: "link", index: l.i });
              }}
            >
              <title>Kliknij, aby zobaczyć, dlaczego te elementy są połączone</title>
            </line>
          </g>
        );
      })}
    </g>
  );
});

const Nodes = memo(function Nodes({
  nodes,
  lit,
  selected,
  onSelect,
  onHover,
}: {
  nodes: PNode[];
  lit: Set<string> | null;
  selected: string | null;
  onSelect: (s: Selection) => void;
  onHover: (n: PNode | null, e?: React.MouseEvent) => void;
}) {
  // Reports first so traces (persons, operators) are drawn on top.
  const ordered = useMemo(
    () => [...nodes].sort((a, b) => Number(a.kind !== "report") - Number(b.kind !== "report") || a.r - b.r),
    [nodes],
  );
  return (
    <g>
      {ordered.map((n) => {
        const on = !lit || lit.has(n.id);
        const isSel = n.id === selected;
        return (
          <g
            key={n.id}
            role="button"
            tabIndex={-1}
            aria-label={`${KIND_WORD[n.kind]}: ${plainTitle(n.label)}`}
            className="cursor-pointer transition-opacity duration-200"
            opacity={on ? 1 : 0.14}
            onMouseEnter={(e) => onHover(n, e)}
            onMouseMove={(e) => onHover(n, e)}
            onMouseLeave={() => onHover(null)}
            onClick={(e) => {
              e.stopPropagation();
              onSelect(isSel ? null : { type: "node", id: n.id });
            }}
          >
            {isSel && (
              <circle cx={n.x} cy={n.y} r={n.r + 5} fill="none" stroke="var(--foreground)" strokeWidth={2} vectorEffect="non-scaling-stroke" />
            )}
            <NodeShape n={n} />
          </g>
        );
      })}
    </g>
  );
});

function initials(text: string) {
  const words = text.replace(/[^\p{L}\p{N} ]/gu, " ").split(/\s+/).filter(Boolean);
  return (words.length > 1 ? words[0][0] + words[1][0] : (words[0] ?? "?").slice(0, 2)).toUpperCase();
}

function NodeShape({ n }: { n: PNode }) {
  const { x, y, r } = n;
  switch (n.kind) {
    case "report":
      return (
        <>
          <circle cx={x} cy={y} r={r} fill="var(--subtle)" stroke={operatorColor(n.group_index)} strokeWidth={2.5} />
          {n.image && (
            <image
              href={`${n.image}?w=64`}
              x={x - r + 1.5}
              y={y - r + 1.5}
              width={(r - 1.5) * 2}
              height={(r - 1.5) * 2}
              preserveAspectRatio="xMidYMin slice"
              clipPath="url(#net-circle)"
            />
          )}
        </>
      );
    case "person":
      return (
        <>
          <circle cx={x} cy={y} r={r} fill="var(--card)" stroke="var(--foreground)" strokeWidth={2} />
          {n.image ? (
            <image
              href={`${n.image}${n.image.includes("?") ? "&" : "?"}w=96`}
              x={x - r + 2}
              y={y - r + 2}
              width={(r - 2) * 2}
              height={(r - 2) * 2}
              preserveAspectRatio="xMidYMid slice"
              clipPath="url(#net-circle)"
            />
          ) : (
            <text x={x} y={y} textAnchor="middle" dominantBaseline="central" fontSize={r * 0.7} fontWeight={600} fill="var(--foreground)">
              {initials(n.label)}
            </text>
          )}
        </>
      );
    case "operator":
      return (
        <>
          <circle cx={x} cy={y} r={r} fill={operatorColor(n.group_index)} stroke="var(--card)" strokeWidth={2.5} />
          <text x={x} y={y + 0.5} textAnchor="middle" dominantBaseline="central" fontSize={r * 0.95} fontWeight={700} fill="var(--card)">
            {n.label.split(" ").at(-1)}
          </text>
        </>
      );
    case "brand":
      return (
        <>
          <rect x={x - r} y={y - r} width={r * 2} height={r * 2} rx={r * 0.3} fill="var(--card)" stroke="var(--tier-context)" strokeWidth={1.8} />
          {n.image ? (
            <image
              href={`${n.image}?w=64`}
              x={x - r + 2.5}
              y={y - r + 2.5}
              width={(r - 2.5) * 2}
              height={(r - 2.5) * 2}
              preserveAspectRatio="xMidYMid meet"
              clipPath="url(#net-square)"
            />
          ) : (
            <text x={x} y={y} textAnchor="middle" dominantBaseline="central" fontSize={r * 0.75} fontWeight={700} fill="var(--muted-foreground)">
              {initials(n.label)}
            </text>
          )}
        </>
      );
    case "infra":
      return (
        <rect
          x={x - r * 0.85}
          y={y - r * 0.85}
          width={r * 1.7}
          height={r * 1.7}
          transform={`rotate(45 ${x} ${y})`}
          fill="var(--card)"
          stroke={tierMeta(n.tier).color}
          strokeWidth={2}
        />
      );
    default:
      return (
        <rect x={x - r} y={y - r} width={r * 2} height={r * 2} rx={1.5} fill={tierMeta(n.tier).color} fillOpacity={0.18} stroke={tierMeta(n.tier).color} strokeWidth={1.6} />
      );
  }
}

type Label = { key: string; x: number; y: number; w: number; text: string; kind: "cluster" | "node"; strong: boolean; color?: string; target: Selection };

/** Screen-space labels with greedy collision avoidance: the selection first, then clusters, people, operators. */
function Labels({
  layout,
  nodes,
  t,
  width,
  height,
  lit,
  focus,
  selectedCampaign,
  onSelect,
}: {
  layout: NetLayout;
  nodes: PNode[];
  t: ZoomTransform;
  width: number;
  height: number;
  lit: Set<string> | null;
  focus: string | null;
  selectedCampaign: string | null;
  onSelect: (s: Selection) => void;
}) {
  const labels = useMemo(() => {
    const placed: Box[] = [];
    const out: Label[] = [];
    const inView = (b: Box) => b[0] >= 2 && b[0] + b[2] <= width - 2 && b[1] >= 2 && b[1] + b[3] <= height - 2;
    const labelBoxes: Box[] = [];
    const tryPlace = (cands: Box[], must: boolean, overNodes = false) => {
      const free = (c: Box) => !labelBoxes.some((p) => overlaps(c, p)) && (overNodes || !placed.some((p) => overlaps(c, p)));
      const clear = (c: Box) => !labelBoxes.some((p) => overlaps(c, p)) && !placed.some((p) => overlaps(c, p));
      const spot = cands.find((c) => inView(c) && clear(c)) ?? cands.find((c) => inView(c) && free(c)) ?? (must ? cands[0] : undefined);
      if (spot) labelBoxes.push(spot);
      return spot;
    };
    const nodeLabel = (n: PNode, strong: boolean) => {
      const size = strong ? 12.5 : 11.5;
      const text = smartTruncate(plainTitle(n.label), strong ? 56 : n.kind === "person" ? 26 : 24);
      const w = measure(text, size, strong ? 600 : 500) + 12;
      const h = 19;
      const sx = t.applyX(n.x);
      const sy = t.applyY(n.y);
      const r = n.r * t.k;
      const spot = tryPlace(
        [
          [sx - w / 2, sy + r + 3, w, h],
          [sx + r + 5, sy - h / 2, w, h],
          [sx - r - 5 - w, sy - h / 2, w, h],
          [sx - w / 2, sy - r - 3 - h, w, h],
        ],
        strong,
      );
      if (spot) out.push({ key: n.id, x: spot[0], y: spot[1], w, text, kind: "node", strong, target: { type: "node", id: n.id } });
    };
    // Node boxes block labels too.
    for (const n of nodes) {
      const r = n.r * t.k;
      if (lit && !lit.has(n.id)) continue;
      placed.push([t.applyX(n.x) - r, t.applyY(n.y) - r, r * 2, r * 2]);
    }
    const focusNode = focus ? layout.byId.get(focus) : undefined;
    if (focusNode) nodeLabel(focusNode, true);
    // Campaign clusters: largest first.
    const visibleIds = new Set(nodes.map((n) => n.id));
    const hulls = [...layout.hulls]
      .filter((h) => h.members.some((m) => visibleIds.has(m.id)))
      .filter((h) => h.members.length > 1 || h.campaign.id === selectedCampaign)
      .sort((a, b) => Number(b.campaign.id === selectedCampaign) - Number(a.campaign.id === selectedCampaign) || b.members.length - a.members.length);
    // Zoomed out on a large base: only the biggest campaigns get a name, the rest on zoom-in.
    const clusterCap = t.k < 0.7 ? 8 : t.k < 1.1 ? 16 : 60;
    let clusterCount = 0;
    for (const h of hulls) {
      if (lit && !h.members.some((m) => lit.has(m.id)) && h.campaign.id !== selectedCampaign) continue;
      if (!lit && h.campaign.id !== selectedCampaign && clusterCount++ >= clusterCap) continue;
      const strong = h.campaign.id === selectedCampaign;
      const text = smartTruncate(plainTitle(h.campaign.label), strong ? 60 : t.k > 1.2 ? 44 : 30);
      const w = measure(text, 11, 600) + 14;
      const sx = t.applyX(h.x);
      const top = t.applyY(h.y - h.r);
      const spot = tryPlace(
        [
          [sx - w / 2, top - 22, w, 19],
          [sx - w / 2, t.applyY(h.y + h.r) + 3, w, 19],
          [sx - w / 2, top - 4, w, 19],
          [sx + t.k * h.r * 0.75, top - 6, w, 19],
          [sx - t.k * h.r * 0.75 - w, top - 6, w, 19],
        ],
        strong,
        true,
      );
      if (spot)
        out.push({
          key: `c:${h.campaign.id}`,
          x: spot[0],
          y: spot[1],
          w,
          text,
          kind: "cluster",
          strong,
          color: operatorColor(h.campaign.group_index),
          target: { type: "campaign", id: h.campaign.id },
        });
    }
    const rank: Record<NetKind, number> = { operator: 0, person: 1, brand: 2, infra: 3, template: 4, report: 5 };
    const rest = nodes
      .filter((n) => n.id !== focus && (!lit || lit.has(n.id)))
      .filter((n) => !!lit || t.k >= 0.7 || n.count >= 3 || n.kind === "operator")
      .filter((n) => n.kind === "person" || n.kind === "operator" || n.kind === "brand" || (n.kind !== "report" && (t.k > 1.3 || !!lit)) || (n.kind === "report" && (t.k > 2.2 || (!!lit && t.k > 1))))
      .sort((a, b) => rank[a.kind] - rank[b.kind] || b.count - a.count);
    for (const n of rest.slice(0, 90)) nodeLabel(n, false);
    return out;
  }, [layout, nodes, t, width, height, lit, focus, selectedCampaign]);

  return (
    <g>
      {labels.map((l) => (
        <g
          key={l.key}
          className={l.kind === "cluster" ? "cursor-pointer" : "pointer-events-none"}
          onClick={(e) => {
            e.stopPropagation();
            onSelect(l.target);
          }}
        >
          <rect
            x={l.x}
            y={l.y}
            width={l.w}
            height={19}
            rx={l.kind === "cluster" ? 9.5 : 5}
            fill="var(--card)"
            fillOpacity={0.94}
            stroke={l.kind === "cluster" ? l.color : "var(--border)"}
            strokeOpacity={l.kind === "cluster" ? 0.6 : 1}
            strokeWidth={l.strong ? 1.6 : 1}
          />
          <text
            x={l.x + l.w / 2}
            y={l.y + 10}
            textAnchor="middle"
            dominantBaseline="central"
            fontSize={l.kind === "cluster" ? 11 : l.strong ? 12.5 : 11.5}
            fontWeight={l.kind === "cluster" || l.strong ? 600 : 500}
            fill={l.kind === "cluster" ? l.color : "var(--foreground)"}
          >
            {l.text}
          </text>
        </g>
      ))}
    </g>
  );
}

export { KIND_WORD };
export const linkStrokeDashed = (l: { kind: string; tier: string | null }) =>
  l.kind === "operator" || l.tier === "context" || l.tier === "toolkit";
