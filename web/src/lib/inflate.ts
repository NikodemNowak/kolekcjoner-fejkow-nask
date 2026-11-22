import type { CampaignDetail } from "@/lib/types";

/**
 * Test helper for the scale page: repeats the members of a real campaign until it has `n`
 * reports, keeping every index-based structure consistent. Nothing here invents content.
 */
export function inflateCampaign(c: CampaignDetail, n: number): CampaignDetail {
  const m = c.members.length;
  if (m === 0 || n <= m) return c;
  const source = (j: number) => j % m;
  const all = Array.from({ length: n }, (_, j) => j);
  const spread = (indices: number[]) => {
    const set = new Set(indices);
    return all.filter((j) => set.has(source(j)));
  };
  const members = all.map((j) => {
    const base = c.members[source(j)];
    return j < m ? base : { ...base, id: `${base.id}#${j}`, title: `${base.title}-${Math.floor(j / m) + 1}` };
  });
  const count = new RegExp(`\\b${m}\\b`, "g");
  return {
    ...c,
    size: n,
    members,
    verdict: c.verdict.replace(/^Te (\d+) reklamy prowadzą/, "Tych $1 reklam prowadzi").replace(count, String(n)),
    summary: c.summary.map((s) => s.replace(count, String(n))),
    comparison: {
      same: c.comparison.same.map((r) => ({ ...r, members: spread(r.members) })),
      different: c.comparison.different.map((r) => ({ ...r, values: r.values.map((v) => ({ ...v, members: spread(v.members) })) })),
      variants: c.comparison.variants.map((v) => ({ ...v, members: spread(v.members) })),
    },
    recognised: c.recognised.map((r) => ({ ...r, members: spread(r.members), ad: spread(r.ad), page: spread(r.page) })),
    matrix: {
      ...c.matrix,
      columns: members.map((x) => ({ id: x.id, label: x.title })),
      rows: c.matrix.rows.map((r) => {
        const cells = all.map((j) => r.cells[source(j)]);
        return { ...r, cells, count: cells.filter((cell) => cell.ad + cell.page > 0).length };
      }),
    },
    pairs_total: Math.round((c.pairs_total / Math.max(1, (m * (m - 1)) / 2)) * ((n * (n - 1)) / 2)),
  };
}
