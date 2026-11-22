import { api } from "@/lib/api";
import { plural } from "@/lib/format";
import { CampaignBrowser } from "@/components/campaign-browser";
import { KpiStrip } from "@/components/kpi-strip";
import { PageHeader } from "@/components/page-header";
import { EmptyState } from "@/components/empty-state";
import { CollectorFeed } from "@/components/collector-feed";
import { Intro } from "@/components/intro";
import type { CampaignSummary, CollectorReport, Summary } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function Overview() {
  const [summary, campaigns, collector] = await Promise.all([
    api<Summary>("/api/summary"),
    api<CampaignSummary[]>("/api/campaigns"),
    // The collector is optional: older API builds have no endpoint, and it may never have run.
    api<CollectorReport>("/api/collector").catch(() => null),
  ]);
  if (!summary || !campaigns) {
    return <EmptyState title="Brak danych analizy" text="Serwer analizy nie zwrócił wyników. Uruchom analizę i odśwież stronę." />;
  }
  const duplicates = summary.reports - summary.unique;
  const singles = summary.campaigns - summary.multi_campaigns;
  return (
    <>
      <PageHeader
        title="Kampanie"
        description="Zgłoszenia reklam-oszustw połączone w kampanie na podstawie wspólnych, sprawdzalnych śladów."
      />
      <Intro />
      <KpiStrip
        className="mb-8"
        items={[
          {
            label: "Zgłoszenia",
            value: summary.reports,
            note: duplicates ? `${plural(summary.unique, "unique")}, ${plural(duplicates, "duplicate")}` : "bez duplikatów",
          },
          { label: "Kampanie", value: summary.multi_campaigns, note: "to samo oszustwo w co najmniej dwóch odsłonach" },
          { label: "Pojedyncze", value: singles, note: "bez pary w bazie" },
          { label: "Sprawcy", value: summary.operators, note: "ta sama osoba lub grupa, rozpoznana po koncie lub pikselu" },
          { label: "Wspólne narzędzia", value: summary.toolkits, note: "ten sam program do tworzenia stron w kilku kampaniach" },
        ]}
      />
      <CollectorFeed report={collector} campaigns={campaigns} />
      <CampaignBrowser campaigns={campaigns} />
    </>
  );
}
