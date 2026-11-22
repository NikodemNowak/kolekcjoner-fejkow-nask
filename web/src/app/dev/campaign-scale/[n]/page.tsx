import { notFound } from "next/navigation";
import { api } from "@/lib/api";
import { inflateCampaign } from "@/lib/inflate";
import { CampaignView } from "@/components/campaign-view";
import type { CampaignDetail, CampaignSummary } from "@/lib/types";

export const dynamic = "force-dynamic";
export const metadata = { title: "Test skali kampanii", robots: { index: false } };

/**
 * Layout test: the largest real campaign with its members repeated to `n` reports (e.g. 25, 60),
 * to check that the campaign page scales. Enabled only with KF_DEV_PAGES=1.
 */
export default async function CampaignScalePage({
  params,
  searchParams,
}: {
  params: Promise<{ n: string }>;
  searchParams: Promise<{ id?: string }>;
}) {
  if (process.env.KF_DEV_PAGES !== "1") notFound();
  const { n } = await params;
  const { id } = await searchParams;
  const size = Math.max(2, Math.min(200, Number.parseInt(n, 10) || 25));
  let campaign = id;
  if (!campaign) {
    const list = await api<CampaignSummary[]>("/api/campaigns");
    campaign = list?.[0]?.id;
  }
  if (!campaign) notFound();
  const c = await api<CampaignDetail>(`/api/campaigns/${encodeURIComponent(campaign)}`);
  if (!c) notFound();
  return (
    <>
      <p className="mb-4 rounded-lg border border-dashed px-3 py-2 text-xs text-muted-foreground">
        Strona testowa: zgłoszenia prawdziwej kampanii powielone do {size}, żeby sprawdzić układ przy dużych kampaniach.
      </p>
      <CampaignView c={inflateCampaign(c, size)} />
    </>
  );
}
