import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceRadial,
  forceSimulation,
  forceX,
  forceY,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import type { GraphLink, GraphNode } from "@/lib/types";

export type PlacedNode = GraphNode & { x: number; y: number; r: number };
export type PlacedLink = GraphLink & { a: PlacedNode; b: PlacedNode };
export type Hull = { index: number; label: string; x: number; y: number; r: number; ids: string[] };
export type Layout = { nodes: PlacedNode[]; links: PlacedLink[]; hulls: Hull[] };

type SimNode = SimulationNodeDatum & { id: string; r: number; group: number | null };

export const nodeRadius = (size: number) => 15 + Math.sqrt(Math.max(1, size) - 1) * 7;

/**
 * Deterministic campaign layout: operator clusters sit on an inner ring, campaigns without
 * an operator on an outer ring. Fixed initial positions and a fixed tick count make the
 * picture identical on every load (d3-force uses a seeded random source).
 */
export function layoutCampaigns(nodes: GraphNode[], links: GraphLink[]): Layout {
  const groups = [...new Set(nodes.map((n) => n.group_index).filter((g): g is number => g !== null))].sort(
    (a, b) => a - b,
  );
  const k = groups.length;
  const inner = k <= 1 ? 0 : 40 + 26 * k;
  const centers = new Map<number, { x: number; y: number }>();
  groups.forEach((g, i) => {
    const angle = -Math.PI / 2 + (i * 2 * Math.PI) / Math.max(1, k);
    centers.set(g, { x: Math.cos(angle) * inner, y: Math.sin(angle) * inner });
  });
  const loose = nodes.filter((n) => n.group_index === null);
  const outer = inner + 120 + loose.length * 2;

  const seen = new Map<number, number>();
  let looseIndex = 0;
  const sim: SimNode[] = nodes.map((n) => {
    const r = nodeRadius(n.size);
    if (n.group_index !== null) {
      const c = centers.get(n.group_index)!;
      const j = seen.get(n.group_index) ?? 0;
      seen.set(n.group_index, j + 1);
      const a = j * 2.4;
      return { id: n.id, r, group: n.group_index, x: c.x + Math.cos(a) * 30, y: c.y + Math.sin(a) * 30 };
    }
    const a = -Math.PI / 2 + ((looseIndex++ + 0.5) * 2 * Math.PI) / Math.max(1, loose.length);
    return { id: n.id, r, group: null, x: Math.cos(a) * outer, y: Math.sin(a) * outer };
  });
  const byId = new Map(sim.map((s) => [s.id, s]));
  type SimLink = SimulationLinkDatum<SimNode> & { kind: string };
  const simLinks: SimLink[] = links
    .filter((l) => byId.has(l.source) && byId.has(l.target))
    .map((l) => ({ source: l.source, target: l.target, kind: l.kind }));

  const simulation = forceSimulation<SimNode>(sim)
    .force(
      "link",
      forceLink<SimNode, SimLink>(simLinks)
        .id((d) => d.id)
        .distance((l) => {
          const s = l.source as SimNode;
          const t = l.target as SimNode;
          return l.kind === "operator" ? s.r + t.r + 22 : 200;
        })
        .strength((l) => (l.kind === "operator" ? 0.8 : 0.015)),
    )
    .force("charge", forceManyBody<SimNode>().strength(-90).distanceMax(260))
    .force("collide", forceCollide<SimNode>((d) => d.r + 14).iterations(3))
    .force("x", forceX<SimNode>((d) => (d.group !== null ? centers.get(d.group)!.x : 0)).strength((d) => (d.group !== null ? 0.35 : 0)))
    .force("y", forceY<SimNode>((d) => (d.group !== null ? centers.get(d.group)!.y : 0)).strength((d) => (d.group !== null ? 0.35 : 0)))
    .force("radial", forceRadial<SimNode>(outer, 0, 0).strength((d) => (d.group === null ? 0.25 : 0)))
    .stop();
  for (let i = 0; i < 360; i++) simulation.tick();

  const placed: PlacedNode[] = nodes.map((n) => {
    const s = byId.get(n.id)!;
    return { ...n, x: s.x ?? 0, y: s.y ?? 0, r: s.r };
  });
  const placedById = new Map(placed.map((p) => [p.id, p]));
  const placedLinks: PlacedLink[] = links
    .filter((l) => placedById.has(l.source) && placedById.has(l.target))
    .map((l) => ({ ...l, a: placedById.get(l.source)!, b: placedById.get(l.target)! }));

  const hulls: Hull[] = groups.map((g) => {
    const members = placed.filter((p) => p.group_index === g);
    const cx = members.reduce((s, m) => s + m.x, 0) / members.length;
    const cy = members.reduce((s, m) => s + m.y, 0) / members.length;
    const r = Math.max(...members.map((m) => Math.hypot(m.x - cx, m.y - cy) + m.r)) + 12;
    return { index: g, label: members[0]?.group ?? "", x: cx, y: cy, r, ids: members.map((m) => m.id) };
  });
  return { nodes: placed, links: placedLinks, hulls };
}

export function bounds(layout: Layout) {
  let x0 = Infinity;
  let y0 = Infinity;
  let x1 = -Infinity;
  let y1 = -Infinity;
  for (const n of layout.nodes) {
    x0 = Math.min(x0, n.x - n.r);
    y0 = Math.min(y0, n.y - n.r);
    x1 = Math.max(x1, n.x + n.r);
    y1 = Math.max(y1, n.y + n.r + 18);
  }
  for (const h of layout.hulls) {
    x0 = Math.min(x0, h.x - h.r);
    y0 = Math.min(y0, h.y - h.r - 18);
    x1 = Math.max(x1, h.x + h.r);
    y1 = Math.max(y1, h.y + h.r);
  }
  if (!Number.isFinite(x0)) return { x0: -100, y0: -100, x1: 100, y1: 100 };
  return { x0, y0, x1, y1 };
}
