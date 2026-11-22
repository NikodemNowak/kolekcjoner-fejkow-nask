import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import type { NetCampaign, NetKind, NetLink, NetNode, Network } from "@/lib/types";

export type PNode = NetNode & SimulationNodeDatum & { x: number; y: number; r: number; ax?: number; ay?: number };
export type PLink = NetLink & { a: PNode; b: PNode; i: number };
export type Hull = { campaign: NetCampaign; x: number; y: number; r: number; members: PNode[] };
export type NetLayout = { nodes: PNode[]; links: PLink[]; hulls: Hull[]; byId: Map<string, PNode> };

/** Radius of a node on the map: traces grow a little with the number of reports they link. */
export function radius(kind: NetKind, count: number) {
  switch (kind) {
    case "report":
      return 11;
    case "person":
      return 13 + Math.min(7, Math.sqrt(count) * 2);
    case "operator":
      return 15 + Math.min(8, Math.sqrt(count) * 2);
    case "brand":
      return 10 + Math.min(5, Math.sqrt(count) * 1.5);
    default:
      return 6 + Math.min(4, Math.sqrt(count));
  }
}

const GOLDEN = Math.PI * (3 - Math.sqrt(5));

/** Deterministic pseudo-random jitter so the same data always gives the same picture. */
function jitter(seed: string) {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++) h = Math.imul(h ^ seed.charCodeAt(i), 16777619);
  return ((h >>> 0) / 4294967295 - 0.5) * 2;
}

/**
 * Force layout of the whole network, computed once: reports are pulled to their campaign's
 * anchor (campaigns on a sunflower spiral, the largest in the middle), traces settle between
 * the reports they link. Hiding a node type later does not move anything.
 */
export function layoutNetwork(net: Network): NetLayout {
  const order = [...net.campaigns].sort(
    (a, b) => b.size - a.size || (a.group_index ?? 99) - (b.group_index ?? 99) || a.id.localeCompare(b.id),
  );
  const anchors = new Map<string, { x: number; y: number }>();
  let area = 0;
  order.forEach((c, i) => {
    const r = 14 * Math.sqrt(c.size) + 34;
    area += Math.PI * r * r * 1.6;
    const dist = i === 0 ? 0 : Math.sqrt(area / Math.PI);
    anchors.set(c.id, { x: Math.cos(i * GOLDEN) * dist, y: Math.sin(i * GOLDEN) * dist });
  });

  const nodes: PNode[] = net.nodes.map((n) => {
    const anchor = n.campaign ? anchors.get(n.campaign) : undefined;
    return {
      ...n,
      r: radius(n.kind, n.count),
      x: (anchor?.x ?? 0) + jitter(n.id) * 20,
      y: (anchor?.y ?? 0) + jitter(`${n.id}#`) * 20,
      ax: anchor?.x,
      ay: anchor?.y,
    };
  });
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const links: PLink[] = [];
  net.links.forEach((l, i) => {
    const a = byId.get(l.source);
    const b = byId.get(l.target);
    if (a && b) links.push({ ...l, a, b, i });
  });
  // Traces start between the reports they link.
  const sums = new Map<string, { x: number; y: number; n: number }>();
  for (const l of links) {
    if (l.b.kind === "report") continue;
    const s = sums.get(l.b.id) ?? { x: 0, y: 0, n: 0 };
    s.x += l.a.x;
    s.y += l.a.y;
    s.n += 1;
    sums.set(l.b.id, s);
  }
  for (const n of nodes) {
    const s = sums.get(n.id);
    if (s) {
      n.x = s.x / s.n + jitter(n.id) * 40;
      n.y = s.y / s.n + jitter(`${n.id}#`) * 40;
    }
  }

  type SL = SimulationLinkDatum<PNode> & { l: PLink };
  const simLinks: SL[] = links.map((l) => ({ source: l.a, target: l.b, l }));
  const sim = forceSimulation<PNode>(nodes)
    .force(
      "link",
      forceLink<PNode, SL>(simLinks)
        .distance(({ l }) => (l.kind === "pair" ? 26 : l.kind === "operator" ? 110 : 56 + l.b.r))
        .strength(({ l }) => {
          if (l.kind === "pair") return l.tier === "campaign" ? 0.5 : 0.02;
          if (l.kind === "operator") return 0.03;
          return 0.35 / Math.sqrt(Math.max(1, l.b.count));
        }),
    )
    .force("charge", forceManyBody<PNode>().strength((n) => (n.kind === "report" ? -26 : -70)).distanceMax(260))
    .force("collide", forceCollide<PNode>((n) => n.r + (n.kind === "report" ? 2.5 : 6)).strength(0.9))
    .force("x", forceX<PNode>((n) => n.ax ?? 0).strength((n) => (n.ax !== undefined ? 0.32 : 0.015)))
    .force("y", forceY<PNode>((n) => n.ay ?? 0).strength((n) => (n.ay !== undefined ? 0.32 : 0.015)))
    .stop();
  const ticks = nodes.length > 300 ? 220 : 300;
  for (let i = 0; i < ticks; i++) sim.tick();

  const hulls: Hull[] = [];
  const members = new Map<string, PNode[]>();
  for (const n of nodes) if (n.kind === "report" && n.campaign) members.set(n.campaign, [...(members.get(n.campaign) ?? []), n]);
  for (const c of net.campaigns) {
    const list = members.get(c.id);
    if (!list?.length) continue;
    const x = list.reduce((s, n) => s + n.x, 0) / list.length;
    const y = list.reduce((s, n) => s + n.y, 0) / list.length;
    const r = Math.max(...list.map((n) => Math.hypot(n.x - x, n.y - y) + n.r)) + 9;
    hulls.push({ campaign: c, x, y, r, members: list });
  }
  return { nodes, links, hulls, byId };
}
