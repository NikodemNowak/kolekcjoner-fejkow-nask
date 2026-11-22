import Link from "next/link";
import { notFound } from "next/navigation";
import { api } from "@/lib/api";
import { campaignHref, caseHref, pct } from "@/lib/format";
import { plural } from "@/lib/plural";
import { CampaignTitle } from "@/components/campaign-title";
import { CaseFeatures } from "@/components/case-features";
import { SectionTitle } from "@/components/page-header";
import { PersonRow } from "@/components/campaign-view";
import { ThumbImage } from "@/components/thumb";
import { cn } from "@/lib/utils";
import type { CaseDetail } from "@/lib/types";

export const dynamic = "force-dynamic";

const FAMILIES: [string, string][] = [
  ["ids", "Identyf."],
  ["asset", "Pliki"],
  ["infra", "Infrastr."],
  ["template", "Szablon"],
  ["image", "Obraz"],
  ["text", "Tekst"],
  ["person", "Postać"],
];

export default async function CasePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const c = await api<CaseDetail>(`/api/cases/${encodeURIComponent(decodeURIComponent(id))}`);
  if (!c) notFound();
  const material = c.thumbs.filter((t) => !t.issue);
  const failed = c.thumbs.filter((t) => t.issue);
  const files = c.inputs.reduce((n, i) => n + i.count, 0);

  return (
    <>
      <nav aria-label="Ścieżka" className="mb-4 flex flex-wrap items-center gap-2 text-[13px] text-muted-foreground">
        <Link href="/" className="hover:text-foreground">Kampanie</Link>
        <span aria-hidden>/</span>
        {c.campaign ? (
          <Link href={campaignHref(c.campaign.id)} className="max-w-[48ch] truncate hover:text-foreground">
            <CampaignTitle text={c.campaign.label} />
          </Link>
        ) : (
          <span>bez kampanii</span>
        )}
      </nav>

      <header className="mb-10 max-w-4xl">
        <p className="text-[13px] font-medium text-muted-foreground">Zgłoszenie {c.title}</p>
        <h1 className="mt-1 text-[22px] leading-tight font-semibold text-balance sm:text-[26px]">
          {c.headline ? <CampaignTitle text={c.headline} /> : `Zgłoszenie ${c.title}`}
        </h1>
        <dl className="mt-5 grid grid-cols-2 gap-x-8 gap-y-4 text-sm sm:flex sm:flex-wrap">
          <Fact label="Domena docelowa">
            {c.domain ? <span className="font-mono text-[13px]">{c.domain}</span> : <span className="text-muted-foreground">brak</span>}
          </Fact>
          {c.captured_at && (
            <Fact label="Przechwycono">
              {new Date(c.captured_at).toLocaleString("pl-PL", { dateStyle: "medium", timeStyle: "short" })}
            </Fact>
          )}
          <Fact label="Sprawca">
            {c.operator ? (
              c.operator.label
            ) : (
              <span className="text-muted-foreground">nieustalony</span>
            )}
          </Fact>
          <Fact label="Pliki">{files}</Fact>
          <Fact label="Powiązania">
            <Link href={`/graph?focus=${encodeURIComponent(c.id)}`} className="text-link underline-offset-4 hover:underline">
              pokaż na grafie
            </Link>
          </Fact>
          {(c.flags.length > 0 || c.duplicate_of) && (
            <Fact label="Uwagi">
              <span className="flex flex-wrap gap-x-3">
                {c.flags.map((f) => (
                  <span key={f}>{f}</span>
                ))}
                {c.duplicate_of && (
                  <Link href={caseHref(c.duplicate_of)} className="underline decoration-border underline-offset-4 hover:decoration-foreground/40">
                    duplikat innego zgłoszenia
                  </Link>
                )}
              </span>
            </Fact>
          )}
        </dl>
      </header>

      <div className="mb-14 grid gap-x-12 gap-y-10 lg:grid-cols-[minmax(0,1fr)_300px]">
        <section>
          <SectionTitle title="Materiał" hint="Miniatury kreacji i zrzutów ekranu. Strony nie są otwierane." />
          {material.length === 0 ? (
            <p className="border-y py-6 text-sm text-muted-foreground">
              Zgłoszenie nie zawiera obrazu reklamy{failed.length > 0 ? " (tylko nieudane przechwycenie strony)" : ""}.
            </p>
          ) : (
            <div className={cn("grid gap-4", material.length === 1 ? "max-w-sm grid-cols-1" : "grid-cols-2 sm:grid-cols-3")}>
              {material.slice(0, 9).map((t) => (
                <figure key={t.artifact_id} className="min-w-0">
                  <ThumbImage thumb={t} width={640} className="aspect-[4/5] w-full rounded-md border" />
                  <figcaption className="mt-1.5 text-xs text-muted-foreground">
                    <span className="text-foreground">{t.kind_label}</span>
                    <span className="block truncate">{t.name}</span>
                  </figcaption>
                </figure>
              ))}
            </div>
          )}
          {material.length > 9 && <p className="mt-3 text-xs text-muted-foreground">Pokazano 9 z {material.length} obrazów.</p>}
          {failed.length > 0 && (
            <details className="group mt-5 border-y text-sm">
              <summary className="flex cursor-pointer list-none items-center gap-3 py-2.5 [&::-webkit-details-marker]:hidden">
                <span className="size-1.5 shrink-0 rounded-full bg-warning" aria-hidden />
                <span className="min-w-0 flex-1">
                  <span className="font-medium">{failed[0].issue}</span>
                  <span className="text-muted-foreground">
                    {" "}
                    · {failed.length === 1 ? failed[0].name : plural(failed.length, "image")} · pominięto jako materiał reklamy
                  </span>
                </span>
                <span className="shrink-0 text-xs text-muted-foreground underline decoration-border underline-offset-4 group-open:hidden">pokaż</span>
                <span className="hidden shrink-0 text-xs text-muted-foreground underline decoration-border underline-offset-4 group-open:inline">ukryj</span>
              </summary>
              <div className="flex flex-wrap gap-4 pb-4">
                {failed.map((t) => (
                  <figure key={t.artifact_id} className="w-56">
                    <ThumbImage thumb={t} width={480} className="aspect-video w-full rounded-md border opacity-80" />
                    <figcaption className="mt-1.5 truncate text-xs text-muted-foreground">{t.name}</figcaption>
                  </figure>
                ))}
              </div>
            </details>
          )}
        </section>

        <section>
          <SectionTitle title="Pliki zgłoszenia" />
          <ul className="border-t text-sm">
            {c.inputs.map((i) => (
              <li key={i.role} className="flex items-baseline justify-between gap-3 border-b py-2" title={i.names.join(", ") || undefined}>
                <span>{i.label}</span>
                <span className="text-muted-foreground tnum">{i.count}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>

      {(c.recognised?.length ?? 0) > 0 && (
        <section className="mb-14">
          <SectionTitle
            title="Rozpoznane osoby i marki"
            hint="Twarze porównujemy z bazą osób publicznych, nazwiska szukamy w tekście. Osoba to wskazówka: sama nie łączy reklam w kampanię."
          />
          <ul className="border-t">
            {c.recognised!.map((r) => (
              <PersonRow key={r.key} r={r} members={[]} single />
            ))}
          </ul>
        </section>
      )}

      <section className="mb-14">
        <SectionTitle
          title="Najbliższe zgłoszenia"
          hint="Wynik łączny pary i siła wspólnych śladów w każdej rodzinie cech. Kreska oznacza brak danych po jednej ze stron; nie obniża wyniku."
        />
        {c.neighbours.length === 0 ? (
          <p className="border-y py-6 text-sm text-muted-foreground">Brak powiązań powyżej progu z innymi zgłoszeniami.</p>
        ) : (
          <div className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
            <table className="w-full min-w-[760px] border-collapse text-sm">
              <thead>
                <tr className="border-y text-xs text-muted-foreground">
                  <th scope="col" className="py-2 pr-4 text-left font-medium">Zgłoszenie</th>
                  <th scope="col" className="w-20 py-2 pr-4 text-right font-medium">Wynik</th>
                  {FAMILIES.map(([f, label]) => (
                    <th key={f} scope="col" className="w-[72px] py-2 pl-2 text-right font-medium">
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {c.neighbours.map((n) => (
                  <tr key={n.id} className="border-b align-baseline">
                    <td className="py-2.5 pr-4">
                      <Link href={caseHref(n.id)} className="font-medium underline-offset-4 hover:underline">
                        {n.title}
                      </Link>
                      {n.campaign && n.campaign.id !== c.campaign?.id && (
                        <span className="ml-2 text-xs text-muted-foreground">inna kampania</span>
                      )}
                      {n.operator_link && <span className="ml-2 text-xs text-muted-foreground">ten sam sprawca</span>}
                    </td>
                    <td className="py-2.5 pr-4 text-right font-semibold tnum">{pct(n.score)}</td>
                    {FAMILIES.map(([f]) => {
                      const v = n.families[f];
                      return (
                        <td key={f} className={cn("py-2.5 pl-2 text-right tnum", v === null || v === undefined || v < 0.3 ? "text-muted-foreground/70" : "")}>
                          {v === null || v === undefined ? "–" : pct(v)}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <section>
        <SectionTitle title="Cechy zgłoszenia" hint="Wartości wyodrębnione z plików. Domeny zapisane bezpiecznie, na przykład example[.]com." />
        {c.features.length === 0 ? (
          <p className="border-y py-6 text-sm text-muted-foreground">Z plików zgłoszenia nie udało się wyodrębnić cech.</p>
        ) : (
          <CaseFeatures families={c.features} />
        )}
      </section>
    </>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5">{children}</dd>
    </div>
  );
}
