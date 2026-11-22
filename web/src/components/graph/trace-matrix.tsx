"use client";

import { useEffect, useState } from "react";
import { CampaignMatrix } from "@/components/campaign-matrix";
import { EmptyState } from "@/components/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { CampaignDetail } from "@/lib/types";

/** The campaign's trace matrix for the graph page, where the campaign is picked on the client. */
export function TraceMatrix({ campaign, className }: { campaign: string; className?: string }) {
  const [data, setData] = useState<CampaignDetail | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let live = true;
    setData(null);
    setError(false);
    fetch(`/api/campaigns/${encodeURIComponent(campaign)}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((c: CampaignDetail) => live && setData(c))
      .catch(() => live && setError(true));
    return () => {
      live = false;
    };
  }, [campaign]);

  if (error) return <EmptyState title="Nie udało się wczytać śladów" text="Serwer analizy nie odpowiada. Spróbuj odświeżyć stronę." className={className} />;
  if (!data) {
    return (
      <div className={cn("space-y-2 rounded-xl border bg-card p-4", className)}>
        {Array.from({ length: 7 }).map((_, i) => (
          <Skeleton key={i} className="h-6 w-full" />
        ))}
      </div>
    );
  }
  if (data.size < 2) {
    return (
      <EmptyState
        title="To pojedyncza reklama"
        text="Macierz pokazuje ślady wspólne dla kilku reklam jednej kampanii. Wybierz kampanię z co najmniej dwiema reklamami."
        className={className}
      />
    );
  }
  return (
    <div className={className}>
      <CampaignMatrix matrix={data.matrix} members={data.members} />
    </div>
  );
}
