/* eslint-disable @next/next/no-img-element */
import Link from "next/link";
import { ExternalLink, Radar } from "lucide-react";
import { CampaignTitle } from "@/components/campaign-title";
import { OperatorDot } from "@/components/operator-badge";
import { campaignHref, int, pct, plural, pluralWord } from "@/lib/format";
import type { CampaignSummary, CollectorReport, CollectorResult } from "@/lib/types";

const DATE = new Intl.DateTimeFormat("pl-PL", { day: "numeric", month: "long", year: "numeric" });
const DATE_TIME = new Intl.DateTimeFormat("pl-PL", {
  day: "numeric",
  month: "long",
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Europe/Warsaw",
});

function date(value: string | null | undefined, withTime = false) {
  if (!value) return null;
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return null;
  return (withTime ? DATE_TIME : DATE).format(d);
}

const VERDICT: Record<string, { label: string; color: string }> = {
  existing: { label: "Wariant znanej kampanii", color: "var(--success)" },
  review: { label: "Do weryfikacji", color: "var(--warning)" },
  new: { label: "Nowa kampania", color: "var(--link)" },
};

function safeUrl(url: string | undefined) {
  if (!url) return null;
  try {
    const u = new URL(url);
    return u.protocol === "https:" || u.protocol === "http:" ? u.toString() : null;
  } catch {
    return null;
  }
}

/**
 * Ads the automatic collector found in public fact-checking articles since its last pass.
 * Renders nothing when the collector has not run (no `<run>/collector/last.json`).
 */
export function CollectorFeed({ report, campaigns }: { report: CollectorReport | null; campaigns: CampaignSummary[] }) {
  const items = (report?.items ?? []).filter((r): r is CollectorResult => Boolean(r?.item?.id));
  if (!report || items.length === 0) return null;
  const byId = new Map(campaigns.map((c) => [c.id, c]));
  const counts = { existing: 0, review: 0, new: 0 } as Record<string, number>;
  for (const r of items) counts[r.decision ?? "new"] = (counts[r.decision ?? "new"] ?? 0) + 1;
  const when = date(report.finished_at ?? report.started_at, true);
  const sources = (report.sources ?? []).join(", ");
  return (
    <section aria-labelledby="collector-title" className="mb-10">
      <div className="mb-3 flex flex-col gap-1 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h2 id="collector-title" className="flex items-center gap-2 text-lg font-semibold tracking-tight">
            <Radar className="size-4.5 text-muted-foreground" strokeWidth={1.75} aria-hidden />
            Automatyczny zbieracz
          </h2>
          <p className="mt-1 max-w-prose text-[13px] text-muted-foreground">
            Program sam przegląda artykuły serwisów fact-checkingowych{sources ? ` (${sources})` : ""}, wyciąga z nich zrzuty
            reklam-oszustw i porównuje je z bazą.
            {when && <> Ostatni przebieg: {when}.</>}
          </p>
        </div>
        <p className="text-[13px] text-muted-foreground tnum sm:text-right">
          {report.articles_seen !== undefined && <>{plural(report.articles_seen, ["artykuł", "artykuły", "artykułów"])} · </>}
          {plural(items.length, ["nowa reklama", "nowe reklamy", "nowych reklam"])}
          {counts.existing > 0 && <> · {int(counts.existing)} {pluralWord(counts.existing, ["wariant", "warianty", "wariantów"])} znanych kampanii</>}
          {counts.new > 0 && <> · {plural(counts.new, ["nowa kampania", "nowe kampanie", "nowych kampanii"])}</>}
        </p>
      </div>
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {items.slice(0, 9).map((r) => {
          const it = r.item;
          const verdict = VERDICT[r.decision ?? "new"] ?? VERDICT.new;
          const campaign = r.campaign_id ? byId.get(r.campaign_id) : undefined;
          const article = safeUrl(it.article_url);
          const published = date(it.published);
          const persons = [...(it.persons ?? []), ...(it.brands ?? [])].slice(0, 4);
          return (
            <li key={it.id} className="grid grid-cols-[72px_minmax(0,1fr)] gap-3 rounded-xl border bg-card p-3 shadow-card">
              <img
                src={`/api/collector/${encodeURIComponent(it.id)}/image?w=200`}
                alt=""
                loading="lazy"
                className="aspect-[4/5] w-full rounded-md border bg-subtle object-cover object-top"
              />
              <div className="flex min-w-0 flex-col">
                <span className="inline-flex items-center gap-1.5 text-xs font-medium">
                  <span className="size-2 rounded-full" style={{ background: verdict.color }} aria-hidden />
                  {verdict.label}
                  {typeof r.score === "number" && r.decision !== "new" && (
                    <span className="font-normal text-muted-foreground tnum">· {pct(r.score)}</span>
                  )}
                </span>
                {campaign ? (
                  <Link href={campaignHref(campaign.id)} className="mt-1 line-clamp-2 text-[13px] leading-snug font-medium hover:underline">
                    <OperatorDot index={campaign.operator_index} className="mr-1.5 align-middle" />
                    <CampaignTitle text={campaign.label} />
                  </Link>
                ) : (
                  <p className="mt-1 line-clamp-2 text-[13px] leading-snug font-medium">{it.article_title || "Reklama z artykułu"}</p>
                )}
                {persons.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {persons.map((p) => (
                      <span key={p} className="rounded-md border bg-surface px-1.5 py-0.5 text-[11px]">
                        {p}
                      </span>
                    ))}
                  </div>
                )}
                <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-0.5 pt-2 text-xs text-muted-foreground">
                  <span className="truncate">
                    {it.publisher || it.source}
                    {published && <> · {published}</>}
                  </span>
                  {article && (
                    <a href={article} target="_blank" rel="noopener noreferrer nofollow" className="inline-flex items-center gap-1 text-link hover:underline">
                      Artykuł źródłowy <ExternalLink className="size-3" aria-hidden />
                    </a>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ul>
      {items.length > 9 && (
        <p className="mt-2 text-xs text-muted-foreground">
          Pokazano 9 z {int(items.length)}. Pełny raport: <span className="font-mono">collector/last.json</span>.
        </p>
      )}
    </section>
  );
}
