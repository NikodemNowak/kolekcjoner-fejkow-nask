import { notFound } from "next/navigation";
import { api } from "@/lib/api";
import { NetworkExplorer } from "@/components/graph/network-explorer";
import type { NetLink, NetNode, Network } from "@/lib/types";

export const dynamic = "force-dynamic";
export const metadata = { title: "Test skali grafu", robots: { index: false } };

/**
 * Scale test: the real network with its reports and campaigns copied `n` times (traces such as
 * persons and operators stay shared), to check the graph at 200–400 nodes. KF_DEV_PAGES=1 only.
 */
export default async function NetworkScalePage({ params }: { params: Promise<{ n: string }> }) {
  if (process.env.KF_DEV_PAGES !== "1") notFound();
  const copies = Math.max(1, Math.min(20, Number.parseInt((await params).n, 10) || 6));
  const net = await api<Network>("/api/network");
  if (!net) notFound();
  const reports = new Set(net.nodes.filter((n) => n.kind === "report").map((n) => n.id));
  const nodes: NetNode[] = net.nodes.filter((n) => n.kind !== "report");
  const links: NetLink[] = [];
  const campaigns = [];
  for (let k = 0; k < copies; k++) {
    const id = (x: string) => (k === 0 ? x : `${x}~${k}`);
    for (const c of net.campaigns) campaigns.push({ ...c, id: id(c.id) });
    for (const n of net.nodes)
      if (n.kind === "report") nodes.push({ ...n, id: id(n.id), label: k ? `${n.label} (${k + 1})` : n.label, campaign: n.campaign ? id(n.campaign) : null });
    for (const l of net.links) {
      // Traces of copies other than the first link only half of the time, like a real, sparser base.
      if (k > 0 && l.kind === "trace" && (l.source.length + k) % 2 === 0) continue;
      links.push({ ...l, source: reports.has(l.source) ? id(l.source) : l.source, target: reports.has(l.target) ? id(l.target) : l.target });
    }
  }
  const counts = new Map<string, number>();
  for (const l of links) counts.set(l.target, (counts.get(l.target) ?? 0) + 1);
  for (const n of nodes) if (n.kind !== "report") n.count = counts.get(n.id) ?? n.count;
  return <NetworkExplorer net={{ ...net, nodes, links, campaigns }} />;
}
