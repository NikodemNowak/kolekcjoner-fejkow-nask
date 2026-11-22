import type { Metadata } from "next";
import { api } from "@/lib/api";
import { PageHeader } from "@/components/page-header";
import { HowToRead } from "@/components/how-to-read";
import { EmptyState } from "@/components/empty-state";
import { GraphExplorer } from "@/components/graph/explorer";
import type { CampaignSummary, GraphData, Network } from "@/lib/types";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Graf powiązań" };

async function network(): Promise<Network | null> {
  // Older API builds have no /api/network: fall back to the campaign map.
  try {
    return await api<Network>("/api/network");
  } catch {
    return null;
  }
}

export default async function GraphPage({ searchParams }: { searchParams: Promise<{ focus?: string }> }) {
  const [graph, campaigns, net, params] = await Promise.all([
    api<GraphData>("/api/graph?level=campaign"),
    api<CampaignSummary[]>("/api/campaigns"),
    network(),
    searchParams,
  ]);
  return (
    <>
      <PageHeader
        title="Graf powiązań"
        description="Wszystkie zgłoszenia na jednej mapie: które reklamy tworzą kampanię, kto za nimi stoi i jakie ślady je łączą."
      />
      <HowToRead
        className="mb-4 max-w-3xl"
        items={[
          "Sieć powiązań: każde kółko z miniaturą to jedno zgłoszenie, a okrąg wokół nich to kampania. Zdjęcia osób, loga i litery sprawców to wspólne ślady.",
          "Kliknij linię, a panel obok wyjaśni, dlaczego elementy są połączone. Przyciski nad mapą włączają i wyłączają rodzaje śladów.",
          "Kampanie i sprawcy: jedna kampania to jedno kółko, kolor oznacza sprawcę. Ślady kampanii: tabela tego, co łączy reklamy wybranej kampanii.",
        ]}
      />
      {graph && campaigns ? (
        <GraphExplorer graph={graph} campaigns={campaigns} network={net} focus={params.focus ?? null} />
      ) : (
        <EmptyState title="Brak danych grafu" text="Serwer analizy nie zwrócił grafu. Sprawdź, czy działa, i odśwież stronę." />
      )}
    </>
  );
}
