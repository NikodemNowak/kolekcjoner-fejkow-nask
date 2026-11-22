"use client";

/* eslint-disable @next/next/no-img-element */
import Link from "next/link";
import { ArrowRight, Building2, Globe, Newspaper, UserRound } from "lucide-react";
import { CampaignTitle, plainTitle } from "@/components/campaign-title";
import { OperatorDot } from "@/components/operator-badge";
import { campaignHref, caseHref, num, pct, plural, smartTruncate } from "@/lib/format";
import { tierMeta } from "@/lib/palette";
import { cn } from "@/lib/utils";
import type { CampaignSummary, FoundItem, Ref, SimilarItem, Verdict } from "@/lib/types";

/*
 * Both sections read optional fields of the verdict (`found`, `similar`) defensively: older
 * API builds do not send them, and field names may vary a little between versions.
 */

type Person = {
  key: string;
  name: string;
  method: string | null;
  score: number | null;
  scoreText: string | null;
  matched: string | null;
  image: string | null;
  reference: string | null;
  reports: number | null;
  slug: string | null;
  campaigns: Ref[];
};

const METHOD: Record<string, string> = {
  face: "twarz",
  twarz: "twarz",
  arcface: "twarz",
  insightface: "twarz",
  ocr: "nazwisko w tekście",
  text: "nazwisko w tekście",
  name: "nazwisko w tekście",
  tekst: "nazwisko w tekście",
  logo: "logo",
  clip: "podobieństwo obrazu",
  siglip: "podobieństwo obrazu",
};

function methodLabel(m: string | null | undefined) {
  if (!m) return null;
  const k = m.toLowerCase();
  return METHOD[k] ?? Object.entries(METHOD).find(([key]) => k.includes(key))?.[1] ?? m;
}

function asRef(x: Ref | string, campaigns: Map<string, CampaignSummary>): Ref {
  if (typeof x === "string") return { id: x, label: campaigns.get(x)?.label ?? x };
  return { id: x.id, label: x.label || campaigns.get(x.id)?.label || x.id };
}

function imageOf(item: FoundItem): string | null {
  if (item.crop) return item.crop;
  if (item.thumb) return item.thumb;
  if (typeof item.reference === "string") return item.reference;
  if (item.reference && typeof item.reference === "object" && "url" in item.reference) return item.reference.url;
  if (item.slug) return `/api/faces/${encodeURIComponent(item.slug)}/ref`;
  return null;
}

function nameOf(item: FoundItem | string): string {
  if (typeof item === "string") return item;
  return item.name || item.label || item.slug || "";
}

const norm = (s: string) => s.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase().trim();

function persons(v: Verdict, campaigns: Map<string, CampaignSummary>): Person[] {
  const list = v.found?.persons ?? [];
  return list
    .filter((p) => nameOf(p))
    .map((p, i) => {
      const name = nameOf(p);
      let refs = (p.campaigns ?? []).map((c) => asRef(c, campaigns));
      if (refs.length === 0) {
        // Older API: find the person in the campaign list by name.
        refs = [...campaigns.values()].filter((c) => c.persons.some((x) => norm(x) === norm(name))).map((c) => ({ id: c.id, label: c.label }));
      }
      return {
        key: `${name}-${i}`,
        name,
        method: p.method_label || methodLabel(p.method),
        score: p.similarity ?? p.confidence ?? null,
        scoreText: p.similarity_text ?? null,
        matched: p.matched ?? null,
        image: imageOf(p),
        reference:
          p.crop && p.reference && typeof p.reference === "object" && "url" in p.reference ? p.reference.url : null,
        reports: p.reports ?? null,
        slug: p.slug ?? null,
        campaigns: refs,
      };
    });
}

function urlWithWidth(url: string, w: number) {
  return url.startsWith("/api/") ? `${url}${url.includes("?") ? "&" : "?"}w=${w}` : url;
}

/** "Co rozpoznaliśmy": persons, brands, domains and the headline found in the material. */
export function FoundSection({ verdict: v, campaigns }: { verdict: Verdict; campaigns: Map<string, CampaignSummary> }) {
  const found = v.found;
  if (!found) return null;
  const people = persons(v, campaigns);
  const brands = (found.brands ?? [])
    .map((b) => {
      const name = nameOf(b);
      const how = typeof b === "string" ? null : b.method_label || methodLabel(b.method);
      return name && how ? `${name} (${how})` : name;
    })
    .filter(Boolean);
  const domains = (found.domains ?? []).map(nameOf).filter(Boolean);
  const headline = found.headline?.trim();
  if (!people.length && !brands.length && !domains.length && !headline) {
    return (
      <section className="mt-10">
        <h3 className="text-[15px] font-semibold">Co rozpoznaliśmy</h3>
        <p className="mt-2 text-sm text-muted-foreground">
          Nie rozpoznaliśmy znanej osoby, marki ani domeny. Werdykt opiera się na pozostałych cechach materiału.
        </p>
      </section>
    );
  }
  return (
    <section className="mt-10" aria-labelledby={`found-${v.case_id}`}>
      <h3 id={`found-${v.case_id}`} className="text-[15px] font-semibold">
        Co rozpoznaliśmy
      </h3>
      <ul className="mt-3 divide-y border-y">
        {people.map((p) => (
          <li key={p.key} className="grid grid-cols-[48px_minmax(0,1fr)] gap-x-3 py-3">
            {p.image ? (
              <span className="relative size-12">
                <img src={urlWithWidth(p.image, 96)} alt="" className="size-12 rounded-full border bg-subtle object-cover object-top" />
                {p.reference && (
                  <img
                    src={urlWithWidth(p.reference, 64)}
                    alt=""
                    title="Zdjęcie wzorcowe z bazy osób publicznych"
                    className="absolute -right-1.5 -bottom-1.5 size-6 rounded-full border-2 border-background bg-subtle object-cover object-top"
                  />
                )}
              </span>
            ) : (
              <span className="grid size-12 place-items-center rounded-full border bg-subtle text-muted-foreground">
                <UserRound className="size-5" strokeWidth={1.5} />
              </span>
            )}
            <div className="min-w-0 text-sm">
              <div>
                <span className="text-muted-foreground">Rozpoznano: </span>
                <span className="font-semibold">{p.name}</span>
                {(p.method || p.score !== null || p.matched) && (
                  <span className="text-muted-foreground">
                    {" "}
                    (
                    {[
                      p.method,
                      p.score !== null ? `podobieństwo ${p.scoreText ?? num(p.score)}` : null,
                      p.matched ? `„${p.matched}”` : null,
                    ]
                      .filter(Boolean)
                      .join(", ")}
                    )
                  </span>
                )}
              </div>
              <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground">
                {p.campaigns.length > 0 ? (
                  <>
                    Ta osoba występuje też w {p.campaigns.length === 1 ? "kampanii" : `${p.campaigns.length} kampaniach`}
                    {p.reports ? ` (${plural(p.reports, "report")} w bazie)` : ""}:{" "}
                    {p.campaigns.slice(0, 3).map((c, i) => (
                      <span key={c.id}>
                        {i > 0 && ", "}
                        <Link href={campaignHref(c.id)} className="text-link underline-offset-4 hover:underline">
                          {smartTruncate(plainTitle(c.label), 60)}
                        </Link>
                      </span>
                    ))}
                    {p.campaigns.length > 3 && ` i ${p.campaigns.length - 3} innych`}. Sama osoba nie wystarcza jednak do połączenia
                    reklam w kampanię: jej wizerunek wykorzystuje wielu niezależnych oszustów.
                  </>
                ) : (
                  <>Tej osoby nie ma jeszcze w żadnej kampanii w bazie. Sama osoba nie wystarcza do połączenia reklam w kampanię.</>
                )}
              </p>
              {p.slug && p.campaigns.length > 0 && (
                <Link
                  href={`/graph?focus=${encodeURIComponent(`Person:${p.slug}`)}`}
                  className="mt-1 inline-flex items-center gap-1 text-[13px] font-medium text-link hover:underline"
                >
                  Pokaż tę osobę na grafie <ArrowRight className="size-3.5" />
                </Link>
              )}
            </div>
          </li>
        ))}
        {(brands.length > 0 || domains.length > 0 || headline) && (
          <li className="space-y-2 py-3 text-sm">
            {brands.length > 0 && (
              <FoundRow icon={<Building2 className="size-4" strokeWidth={1.75} />} label="Marki">
                {brands.join(", ")}
              </FoundRow>
            )}
            {domains.length > 0 && (
              <FoundRow icon={<Globe className="size-4" strokeWidth={1.75} />} label="Domeny">
                <span className="font-mono text-[13px] break-all">{domains.join(", ")}</span>
              </FoundRow>
            )}
            {headline && (
              <FoundRow icon={<Newspaper className="size-4" strokeWidth={1.75} />} label="Nagłówek">
                <span className="italic">„{headline}”</span>
              </FoundRow>
            )}
          </li>
        )}
      </ul>
    </section>
  );
}

function FoundRow({ icon, label, children }: { icon: React.ReactNode; label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[1.25rem_6.5rem_minmax(0,1fr)] items-baseline gap-x-2">
      <span className="translate-y-0.5 text-muted-foreground">{icon}</span>
      <span className="text-muted-foreground">{label}</span>
      <span className="min-w-0 break-words">{children}</span>
    </div>
  );
}

type Near = {
  key: string;
  href: string | null;
  kind: "report" | "campaign";
  label: string;
  sub: string | null;
  score: number | null;
  shared: { text: string; tier: string | null }[];
  thumb: string | null;
  operatorIndex: number | null;
};

function nearList(v: Verdict, campaigns: Map<string, CampaignSummary>): Near[] {
  return (v.similar ?? []).map((s: SimilarItem, i) => {
    const caseId = s.case_id ?? (s.kind === "report" || s.kind === "case" ? s.id : null) ?? null;
    const campaignId = s.campaign_id ?? s.campaign?.id ?? (s.kind === "campaign" ? s.id : null) ?? null;
    const summary = campaignId ? campaigns.get(campaignId) : undefined;
    const isReport = Boolean(caseId);
    const label = s.title || s.label || (isReport ? "Zgłoszenie" : s.campaign?.label || summary?.label) || "Kampania";
    const campaignLabel = s.campaign?.label || summary?.label;
    return {
      key: `${caseId ?? campaignId ?? i}`,
      href: caseId ? caseHref(caseId) : campaignId ? campaignHref(campaignId) : null,
      kind: isReport ? "report" : "campaign",
      label,
      sub: isReport && campaignLabel ? campaignLabel : s.reports ? plural(s.reports, "report") : summary ? plural(summary.size, "report") : null,
      score: s.score ?? null,
      shared: [...(s.shared ?? []), ...(s.traces ?? [])]
        .map((x) => (typeof x === "string" ? { text: x, tier: null } : { text: x.label || x.text || "", tier: x.tier ?? null }))
        .filter((x) => x.text),
      thumb: s.thumb ?? (summary?.thumbs[0]?.url ?? null),
      operatorIndex: summary?.operator_index ?? null,
    };
  });
}

/** "Najbliższe znane zgłoszenia": closest known material, also for a new pattern. */
export function SimilarSection({ verdict: v, campaigns }: { verdict: Verdict; campaigns: Map<string, CampaignSummary> }) {
  if (!v.similar) return null;
  const items = nearList(v, campaigns).slice(0, 6);
  return (
    <section className="mt-10" aria-labelledby={`similar-${v.case_id}`}>
      <h3 id={`similar-${v.case_id}`} className="text-[15px] font-semibold">
        Najbliższe znane zgłoszenia
      </h3>
      <p className="mt-1 text-[13px] text-muted-foreground">
        {v.decision === "existing"
          ? "Najbardziej podobny materiał w bazie i ślady, które ma wspólne z analizowaną reklamą."
          : "Nawet jeśli to nowy wzorzec, pokazujemy najbliższe materiały z bazy i to, co je łączy. Słabe ślady (osoba, marka) same nie wystarczają do połączenia."}
      </p>
      {items.length === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground">W bazie nie ma materiału z choćby jednym wspólnym śladem.</p>
      ) : (
        <ul className="mt-3 divide-y border-y">
          {items.map((n) => {
            const body = (
              <>
                {n.thumb ? (
                  <img src={urlWithWidth(n.thumb, 120)} alt="" className="aspect-[4/5] w-full rounded-md border bg-subtle object-cover object-top" />
                ) : (
                  <span className="aspect-[4/5] w-full rounded-md border bg-subtle" />
                )}
                <div className="min-w-0">
                  <div className="text-xs text-muted-foreground">{n.kind === "report" ? "Zgłoszenie" : "Kampania"}</div>
                  <div className="line-clamp-2 text-sm font-medium">
                    <CampaignTitle text={n.label} />
                  </div>
                  {n.sub && (
                    <div className="mt-0.5 flex items-center gap-1.5 truncate text-xs text-muted-foreground">
                      <OperatorDot index={n.operatorIndex} />
                      <span className="truncate">{plainTitle(n.sub)}</span>
                    </div>
                  )}
                  {n.shared.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {n.shared.slice(0, 5).map((s) => (
                        <span key={s.text} className="inline-flex items-center gap-1 rounded-md border bg-surface px-1.5 py-0.5 text-xs" title={s.tier ? tierMeta(s.tier).hint : undefined}>
                          {s.tier && <span className="size-1.5 rounded-full" style={{ background: tierMeta(s.tier).color }} aria-hidden />}
                          {s.text}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
                <div className="text-right">
                  {n.score !== null && n.score > 0.005 && <div className="text-sm font-medium tnum">{pct(n.score)}</div>}
                  {n.href && <ArrowRight className="ml-auto mt-1 size-3.5 text-muted-foreground" aria-hidden />}
                </div>
              </>
            );
            const cls = "grid grid-cols-[44px_minmax(0,1fr)_auto] items-start gap-x-3 py-3";
            return (
              <li key={n.key}>
                {n.href ? (
                  <Link href={n.href} className={cn(cls, "-mx-2 rounded-md px-2 hover:bg-surface")}>
                    {body}
                  </Link>
                ) : (
                  <div className={cls}>{body}</div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
