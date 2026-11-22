import { notFound } from "next/navigation";
import { api } from "@/lib/api";
import { CampaignView } from "@/components/campaign-view";
import type { CampaignDetail } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function CampaignPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const c = await api<CampaignDetail>(`/api/campaigns/${encodeURIComponent(decodeURIComponent(id))}`);
  if (!c) notFound();
  return <CampaignView c={c} />;
}
