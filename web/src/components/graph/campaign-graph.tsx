"use client";

import { select } from "d3-selection";
import { zoom as d3zoom, zoomIdentity, type ZoomBehavior, type ZoomTransform } from "d3-zoom";
import "d3-transition";
import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { ImageOff } from "lucide-react";
import { plainTitle } from "@/components/campaign-title";
import { smartTruncate } from "@/lib/format";
import { operatorColor } from "@/lib/palette";
import { cn } from "@/lib/utils";
import { bounds, type Layout, type PlacedNode } from "./layout";

export type CampaignGraphHandle = {
  fit: (animate?: boolean) => void;
  zoomBy: (factor: number) => void;
  center: (id: string) => void;
};

type Props = {
  layout: Layout;
  width: number;
  height: number;
  selected: string | null;
  highlightGroup: number | null;
  onSelect: (id: string | null) => void;
};

type Box = [number, number, number, number];
const overlaps = (a: Box, b: Box) => a[0] < b[0] + b[2] && b[0] < a[0] + a[2] && a[1] < b[1] + b[3] && b[1] < a[1] + a[3];

let measureCtx: CanvasRenderingContext2D | null = null;
function measure(text: string, weight: number) {
  if (typeof document === "undefined") return text.length * 6.4;
  measureCtx ??= document.createElement("canvas").getContext("2d");
  if (!measureCtx) return text.length * 6.4;
  measureCtx.font = `${weight} 12px ${getComputedStyle(document.body).fontFamily}`;
  return measureCtx.measureText(text).width;
}

export const CampaignGraph = forwardRef<CampaignGraphHandle, Props>(function CampaignGraph(
  { layout, width, height, selected, highlightGroup, onSelect },
  ref,
) {
  const svgRef = useRef<SVGSVGElement>(null);
  const zoomRef = useRef<ZoomBehavior<SVGSVGElement, unknown> | null>(null);
  const [t, setT] = useState<ZoomTransform>(zoomIdentity);
  const [hover, setHover] = useState<string | null>(null);
  const [focusId, setFocusId] = useState<string | null>(null);

  const neighbours = useMemo(() => {
    const map = new Map<string, Set<string>>();
    for (const l of layout.links) {
      if (!map.has(l.a.id)) map.set(l.a.id, new Set());
      if (!map.has(l.b.id)) map.set(l.b.id, new Set());
      map.get(l.a.id)!.add(l.b.id);
      map.get(l.b.id)!.add(l.a.id);
    }
    return map;
  }, [layout]);

  const fitTransform = useCallback(() => {
    const b = bounds(layout);
    // Leave room for the legend at the bottom and the zoom buttons at the top right.
    const pad = width < 640 ? { top: 24, bottom: 16, side: 16 } : { top: 28, bottom: 64, side: 56 };
    const k = Math.min(
      2.2,
      Math.min((width - pad.side * 2) / (b.x1 - b.x0), (height - pad.top - pad.bottom) / (b.y1 - b.y0)),
    );
    const tx = width / 2 - ((b.x0 + b.x1) / 2) * k;
    const ty = pad.top + (height - pad.top - pad.bottom) / 2 - ((b.y0 + b.y1) / 2) * k;
    return zoomIdentity.translate(tx, ty).scale(k);
  }, [layout, width, height]);

  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const z = d3zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 5])
      .filter((event: Event) => {
        // Wheel zooms only with a modifier so the page still scrolls; drag and pinch always work.
        if (event.type === "wheel") return (event as WheelEvent).ctrlKey || (event as WheelEvent).metaKey;
        return !(event as MouseEvent).button;
      })
      .on("zoom", (e) => setT(e.transform));
    zoomRef.current = z;
    const sel = select(svg);
    sel.call(z).on("dblclick.zoom", null);
    sel.call(z.transform, fitTransform());
    return () => {
      sel.on(".zoom", null);
    };
  }, [fitTransform]);

  useImperativeHandle(
    ref,
    () => ({
      fit: (animate = true) => {
        const svg = svgRef.current;
        if (!svg || !zoomRef.current) return;
        const sel = select(svg);
        if (animate) sel.transition().duration(300).call(zoomRef.current.transform, fitTransform());
        else sel.call(zoomRef.current.transform, fitTransform());
      },
      zoomBy: (factor) => {
        const svg = svgRef.current;
        if (!svg || !zoomRef.current) return;
        select(svg).transition().duration(200).call(zoomRef.current.scaleBy, factor);
      },
      center: (id) => {
        const svg = svgRef.current;
        const node = layout.nodes.find((n) => n.id === id);
        if (!svg || !zoomRef.current || !node) return;
        const k = Math.max(t.k, 1.3);
        const target = zoomIdentity.translate(width / 2 - node.x * k, height / 2 - node.y * k).scale(k);
        select(svg).transition().duration(300).call(zoomRef.current.transform, target);
      },
    }),
    [fitTransform, layout, t.k, width, height],
  );

  const focus = hover ?? focusId ?? selected;
  const lit = useMemo(() => {
    if (focus) return new Set([focus, ...(neighbours.get(focus) ?? [])]);
    if (highlightGroup !== null)
      return new Set(layout.nodes.filter((n) => n.group_index === highlightGroup).map((n) => n.id));
    return null;
  }, [focus, neighbours, highlightGroup, layout]);

  // Screen-space labels with greedy collision avoidance; priority labels first.
  const labels = useMemo(() => {
    const placed: { id: string | null; box: Box }[] = layout.nodes.map((n) => {
      const r = n.r * t.k;
      return { id: n.id, box: [t.applyX(n.x) - r, t.applyY(n.y) - r, r * 2, r * 2] };
    });
    const priority = (n: PlacedNode) =>
      n.id === focus ? 0 : n.id === selected ? 1 : lit?.has(n.id) ? 2 : n.size > 1 ? 3 : 4;
    const out: { id: string; x: number; y: number; w: number; text: string; strong: boolean }[] = [];
    const order = [...layout.nodes].sort((a, b) => priority(a) - priority(b) || b.size - a.size);
    for (const n of order) {
      const important = n.id === focus || n.id === selected;
      const wanted = important || (lit ? lit.has(n.id) : n.size > 1 || t.k > 1.7);
      if (!wanted) continue;
      const text = smartTruncate(plainTitle(n.label), important ? 54 : 30);
      const w = measure(text, important ? 600 : 500) + 12;
      const h = 20;
      const sx = t.applyX(n.x);
      const sy = t.applyY(n.y);
      const r = n.r * t.k;
      const candidates: Box[] = [
        [sx - w / 2, sy + r + 4, w, h],
        [sx + r + 6, sy - h / 2, w, h],
        [sx - r - 6 - w, sy - h / 2, w, h],
        [sx - w / 2, sy - r - 4 - h, w, h],
      ];
      const spot = candidates.find(
        (c) =>
          c[0] >= 2 && c[0] + c[2] <= width - 2 && c[1] >= 2 && c[1] + c[3] <= height - 2 &&
          !placed.some((p) => p.id !== n.id && overlaps(c, p.box)),
      ) ?? (important ? candidates[0] : undefined);
      if (!spot) continue;
      placed.push({ id: null, box: spot });
      out.push({ id: n.id, x: spot[0], y: spot[1], w, text, strong: important });
    }
    return out;
  }, [layout, t, focus, selected, lit, width, height]);

  return (
    <svg
      ref={svgRef}
      width={width}
      height={height}
      role="group"
      aria-label="Graf kampanii: węzły to kampanie, linie to ten sam sprawca lub ten sam program do tworzenia stron"
      className="block cursor-grab touch-none select-none active:cursor-grabbing"
      onClick={(e) => {
        if (e.target === svgRef.current) onSelect(null);
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") onSelect(null);
      }}
    >
      <defs>
        {layout.nodes.map((n) => (
          <clipPath key={n.id} id={`clip-${cssId(n.id)}`}>
            <circle cx={n.x} cy={n.y} r={n.r - 2.5} />
          </clipPath>
        ))}
      </defs>
      <g transform={t.toString()}>
        {layout.hulls.map((h) => {
          const on = !lit || h.ids.some((id) => lit.has(id));
          return (
            <circle
              key={h.index}
              cx={h.x}
              cy={h.y}
              r={h.r}
              fill={operatorColor(h.index)}
              fillOpacity={on ? 0.07 : 0.03}
              stroke={operatorColor(h.index)}
              strokeOpacity={on ? 0.35 : 0.12}
              strokeWidth={1 / t.k}
              strokeDasharray={`${3 / t.k} ${3 / t.k}`}
              className="transition-[fill-opacity,stroke-opacity] duration-200"
            />
          );
        })}
        {layout.links.map((l, i) => {
          const on = !lit || (lit.has(l.a.id) && lit.has(l.b.id) && (!focus || l.a.id === focus || l.b.id === focus));
          const operator = l.kind === "operator";
          const dx = l.b.x - l.a.x;
          const dy = l.b.y - l.a.y;
          const bend = operator ? 0 : 0.16 * (l.a.id < l.b.id ? 1 : -1);
          const mx = (l.a.x + l.b.x) / 2 - dy * bend;
          const my = (l.a.y + l.b.y) / 2 + dx * bend;
          return (
            <path
              key={i}
              d={`M${l.a.x},${l.a.y} Q${mx},${my} ${l.b.x},${l.b.y}`}
              fill="none"
              stroke={operator ? operatorColor(l.a.group_index) : "var(--muted-foreground)"}
              strokeWidth={(operator ? 2.5 : 1.25) / Math.sqrt(t.k)}
              strokeDasharray={operator ? undefined : `${5 / Math.sqrt(t.k)} ${4 / Math.sqrt(t.k)}`}
              strokeLinecap="round"
              opacity={on ? (operator ? 0.9 : 0.55) : 0.07}
              className="transition-opacity duration-200"
            />
          );
        })}
        {layout.nodes.map((n) => {
          const on = !lit || lit.has(n.id);
          const isSel = n.id === selected;
          return (
            <g
              key={n.id}
              role="button"
              tabIndex={0}
              aria-label={`${plainTitle(n.label)}. ${n.size} zgł. ${n.group ?? "Sprawca nieustalony"}`}
              aria-pressed={isSel}
              className="cursor-pointer outline-none transition-opacity duration-200"
              opacity={on ? 1 : 0.18}
              onMouseEnter={() => setHover(n.id)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setFocusId(n.id)}
              onBlur={() => setFocusId(null)}
              onClick={(e) => {
                e.stopPropagation();
                onSelect(isSel ? null : n.id);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onSelect(isSel ? null : n.id);
                }
              }}
            >
              {(isSel || focusId === n.id) && (
                <circle cx={n.x} cy={n.y} r={n.r + 5} fill="none" stroke="var(--foreground)" strokeWidth={2 / t.k} />
              )}
              <circle cx={n.x} cy={n.y} r={n.r} fill="var(--card)" stroke={operatorColor(n.group_index)} strokeWidth={3} />
              {n.thumb ? (
                <image
                  href={`${n.thumb}?w=96`}
                  x={n.x - n.r}
                  y={n.y - n.r}
                  width={n.r * 2}
                  height={n.r * 2}
                  preserveAspectRatio="xMidYMin slice"
                  clipPath={`url(#clip-${cssId(n.id)})`}
                />
              ) : (
                <g aria-hidden>
                  <circle cx={n.x} cy={n.y} r={n.r - 2.5} fill="var(--subtle)" />
                  <ImageOff x={n.x - 7} y={n.y - 7} width={14} height={14} stroke="var(--muted-foreground)" strokeWidth={1.6} />
                </g>
              )}
              {n.size > 1 && (
                <g>
                  <circle
                    cx={n.x + n.r * 0.72}
                    cy={n.y - n.r * 0.72}
                    r={8}
                    fill={operatorColor(n.group_index)}
                    stroke="var(--card)"
                    strokeWidth={1.5}
                  />
                  <text
                    x={n.x + n.r * 0.72}
                    y={n.y - n.r * 0.72}
                    textAnchor="middle"
                    dominantBaseline="central"
                    fontSize={9.5}
                    fontWeight={650}
                    fill="var(--card)"
                    className="tnum"
                  >
                    {n.size}
                  </text>
                </g>
              )}
            </g>
          );
        })}
      </g>
      <g aria-hidden className="pointer-events-none">
        {layout.hulls.map((h) => {
          const x = t.applyX(h.x);
          const y = t.applyY(h.y - h.r) - 6;
          return (
            <text
              key={h.index}
              x={x}
              y={y}
              textAnchor="middle"
              fontSize={11}
              fontWeight={600}
              letterSpacing="0.04em"
              fill={operatorColor(h.index)}
              opacity={!lit || h.ids.some((id) => lit.has(id)) ? 1 : 0.3}
              className="uppercase transition-opacity duration-200"
            >
              {h.label}
            </text>
          );
        })}
        {labels.map((l) => (
          <g key={l.id} className={cn("transition-opacity duration-200")}>
            <rect
              x={l.x}
              y={l.y}
              width={l.w}
              height={20}
              rx={6}
              fill="var(--card)"
              fillOpacity={0.94}
              stroke="var(--border)"
            />
            <text
              x={l.x + l.w / 2}
              y={l.y + 10.5}
              textAnchor="middle"
              dominantBaseline="central"
              fontSize={12}
              fontWeight={l.strong ? 600 : 500}
              fill="var(--foreground)"
            >
              {l.text}
            </text>
          </g>
        ))}
      </g>
    </svg>
  );
});

function cssId(id: string) {
  return id.replace(/[^a-zA-Z0-9_-]/g, "_");
}
