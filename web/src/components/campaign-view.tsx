import Link from "next/link";
import { ArrowUpRight, Check, EqualNot, ImageOff, Link2, Megaphone, PanelTop, Pin, Repeat, ScanFace } from "lucide-react";
import { campaignHref, caseHref, num, pct, pct1 } from "@/lib/format";
import { plural, pluralWord } from "@/lib/plural";
import { CampaignMatrix } from "@/components/campaign-matrix";
import { CampaignTitle } from "@/components/campaign-title";
import { Coverage, shortTitle } from "@/components/coverage";
import { FamilyIcon } from "@/components/family-icon";
import { HowToRead } from "@/components/how-to-read";
import { OperatorBadge } from "@/components/operator-badge";
import { SectionTitle } from "@/components/page-header";
import { Term } from "@/components/term";
import { ThumbImage } from "@/components/thumb";
import { ValueList } from "@/components/value-list";
import { ValueText } from "@/components/value-text";
import { TIER_META, TIERS, tierMeta } from "@/lib/palette";
import type { CampaignDetail, DiffRow, Member, PairLink, Recognised, SharedRow, TraitRow, Variant } from "@/lib/types";

const FAMILY_ORDER = ["ids", "asset", "text", "image", "template", "infra", "person"];
const PAIRS_SHOWN = 5;
const VARIANTS_SHOWN = 12;
const MEMBERS_SHOWN = 24;
const VALUES_SHOWN = 6;

/** The whole campaign page. Built to read the same for 2 reports and for 60. */
export function CampaignView({ c }: { c: CampaignDetail }) {
  const single = c.size === 1;
  const byId = new Map(c.members.map((m) => [m.id, m]));
  const constant = groupByFamily(c.constant);
  const possiblePairs = (c.size * (c.size - 1)) / 2;

  return (
    <>
      <nav aria-label="Ścieżka" className="mb-4 flex flex-wrap items-center gap-2 text-[13px] text-muted-foreground">
        <Link href="/" className="hover:text-foreground">
          Kampanie
        </Link>
        <span aria-hidden>/</span>
        <span>{single ? "Pojedyncze zgłoszenie" : "Kampania"}</span>
      </nav>

      <header className="mb-6 max-w-4xl">
        <h1 className="text-[22px] leading-tight font-semibold text-balance sm:text-[26px]">
          <CampaignTitle text={c.label} />
        </h1>
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
          <span className="font-medium tnum">{plural(c.size, "report")}</span>
          <span aria-hidden className="text-border">
            |
          </span>
          <OperatorBadge operator={c.operator} index={c.operator_index} />
          {c.domains.length > 0 && (
            <>
              <span aria-hidden className="text-border">
                |
              </span>
              <span className="text-muted-foreground tnum">{plural(c.domains.length, "domain")}</span>
            </>
          )}
          <span aria-hidden className="text-border">
            |
          </span>
          <Link href={`/graph?focus=${encodeURIComponent(c.id)}`} className="text-link underline-offset-4 hover:underline">
            Pokaż na grafie
          </Link>
          {c.flags.map((f) => (
            <span key={f} className="rounded-full border px-2 py-0.5 text-xs text-warning-foreground">
              {f}
            </span>
          ))}
        </div>
        {single && <p className="mt-4 text-sm leading-relaxed text-muted-foreground">{c.why}</p>}
      </header>

      {!single && (
        <HowToRead
          className="mb-5 max-w-3xl"
          items={[
            "Zdanie na górze to wniosek: dlaczego uznajemy te reklamy za jedną kampanię, czyli jedno oszustwo w kilku odsłonach.",
            "Pod nim widać wersje reklamy, potem to, co mają takie samo (to są dowody, każdy pokazany raz), i to, czym się różnią.",
            "Sekcje niżej to szczegóły dla analityka: pełna lista wspólnych śladów i powiązania z innymi kampaniami.",
          ]}
        />
      )}

      {!single && <Story c={c} />}

      {single && (
        <section className="mb-12">
          <SectionTitle title="Zgłoszenie" />
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
            {c.members.map((m) => (
              <MemberCard key={m.id} member={m} />
            ))}
          </div>
        </section>
      )}

      {c.recognised.length > 0 && <People c={c} />}

      {!single && (
        <div className="mb-8 border-b pb-3">
          <h2 className="text-lg font-semibold">Szczegóły dla analityka</h2>
          <p className="mt-0.5 text-[13px] text-muted-foreground">Pełna lista śladów, na których opiera się wniosek powyżej.</p>
        </div>
      )}

      {!single && (
        <section className="mb-12">
          <SectionTitle
            title="Gdzie znaleziono wspólne ślady"
            hint="Każdy wiersz to jeden wspólny ślad: w ilu zgłoszeniach jest i czy widać go w samej reklamie, czy na stronie, do której prowadzi."
          />
          <CampaignMatrix matrix={c.matrix} members={c.members} />
        </section>
      )}

      {!single && c.size > 2 && (
        <section className="mb-12">
          <SectionTitle title={`Wszystkie zgłoszenia (${c.size})`} hint="Kliknij, aby otworzyć zgłoszenie z jego plikami i cechami." />
          <MemberGrid members={c.members.slice(0, MEMBERS_SHOWN)} />
          {c.members.length > MEMBERS_SHOWN && (
            <details className="group mt-3">
              <summary className="cursor-pointer list-none text-xs text-muted-foreground underline decoration-border underline-offset-4 hover:text-foreground [&::-webkit-details-marker]:hidden">
                <span className="group-open:hidden">pokaż wszystkie ({c.members.length})</span>
                <span className="hidden group-open:inline">pokaż mniej</span>
              </summary>
              <MemberGrid members={c.members.slice(MEMBERS_SHOWN)} className="mt-3" />
            </details>
          )}
        </section>
      )}

      {!single && c.size > 2 && c.pairs.length > 0 && (
        <section className="mb-12">
          <SectionTitle
            title="Siła powiązań między parami zgłoszeń"
            hint={`Połączone ${c.pairs_total} z ${plural(possiblePairs, ["możliwej pary", "możliwych par", "możliwych par"])}. Im wyższy procent, tym mocniejsze wspólne ślady.`}
          />
          <ul className="border-t text-sm">
            {c.pairs.slice(0, PAIRS_SHOWN).map((p) => (
              <PairRow key={`${p.a.id}-${p.b.id}`} pair={p} byId={byId} />
            ))}
          </ul>
          {c.pairs.length > PAIRS_SHOWN && (
            <details className="group text-sm">
              <summary className="cursor-pointer list-none py-2 text-xs text-muted-foreground underline decoration-border underline-offset-4 hover:text-foreground [&::-webkit-details-marker]:hidden">
                <span className="group-open:hidden">
                  pokaż {pluralWord(c.pairs.length - PAIRS_SHOWN, ["kolejną", "kolejne", "kolejnych"])}{" "}
                  {plural(c.pairs.length - PAIRS_SHOWN, ["parę", "pary", "par"])}
                </span>
                <span className="hidden group-open:inline">pokaż mniej</span>
              </summary>
              <ul className="border-t">
                {c.pairs.slice(PAIRS_SHOWN).map((p) => (
                  <PairRow key={`${p.a.id}-${p.b.id}`} pair={p} byId={byId} />
                ))}
              </ul>
              {c.pairs_total > c.pairs.length && (
                <p className="py-2 text-xs text-muted-foreground">
                  Pokazano {c.pairs.length} najmocniejszych z {c.pairs_total} połączonych par.
                </p>
              )}
            </details>
          )}
        </section>
      )}

      <div className="mb-12 grid gap-x-12 gap-y-10 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
        <section>
          <SectionTitle
            title={single ? "Cechy zgłoszenia" : "Co jest stałe we wszystkich reklamach"}
            hint={single ? "Najbardziej charakterystyczne ślady tego zgłoszenia." : "Ślady obecne w co najmniej 80% reklam tej kampanii. Po nich warto ją blokować."}
          />
          {constant.length === 0 ? (
            <p className="border-y py-6 text-sm text-muted-foreground">
              Żaden ślad nie występuje we wszystkich zgłoszeniach – kampanię łączą wspólne ślady par zgłoszeń (poniżej).
            </p>
          ) : (
            <div className="border-t">
              {constant.map(({ family, label, rows }) => (
                <div key={family} className="grid gap-x-6 gap-y-2 border-b py-4 sm:grid-cols-[150px_minmax(0,1fr)]">
                  <h3 className="flex items-center gap-2 self-start text-sm font-semibold">
                    <FamilyIcon family={family} />
                    <span className="first-letter:uppercase">{label}</span>
                  </h3>
                  <dl className="space-y-2.5 text-sm">
                    {rows.map((t, i) => (
                      <div key={i} className="grid gap-x-4 gap-y-0.5 sm:grid-cols-[150px_minmax(0,1fr)]">
                        <dt className="flex items-baseline gap-1.5 text-muted-foreground">
                          <span
                            aria-hidden
                            title={tierMeta(t.tier).label}
                            className="size-2 shrink-0 translate-y-[-1px] rounded-full"
                            style={{ background: tierMeta(t.tier).color }}
                          />
                          {t.type_label}
                        </dt>
                        <dd className="min-w-0">
                          {t.values.length > 3 && <div className="font-medium">{t.entity_type === "Asset" ? t.headline : plural(t.values.length, "value")}</div>}
                          <ValueList values={t.values} />
                          {!single && t.coverage < 0.995 && (
                            <div className="mt-0.5 text-xs text-muted-foreground tnum">w {pct(t.coverage)} reklam</div>
                          )}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </div>
              ))}
            </div>
          )}
          <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
            {TIERS.map((t) => (
              <li key={t} className="inline-flex items-center gap-1.5" title={TIER_META[t].hint}>
                <span aria-hidden className="size-2 rounded-full" style={{ background: TIER_META[t].color }} />
                {TIER_META[t].label}
              </li>
            ))}
          </ul>
        </section>

        {!single && (
          <section>
            <SectionTitle title="Co się zmienia" hint="Wartości wymieniane między reklamami. Blokada jednej nie zatrzyma kampanii." />
            {c.rotating_rows.length === 0 ? (
              <p className="border-y py-6 text-sm text-muted-foreground">Brak zmiennych cech.</p>
            ) : (
              <dl className="border-t text-sm">
                {c.rotating_rows.map((t, i) => (
                  <div key={i} className="grid gap-x-4 gap-y-0.5 border-b py-3 sm:grid-cols-[130px_minmax(0,1fr)]">
                    <dt className="flex items-baseline gap-1.5 text-muted-foreground">
                      <Repeat className="size-3.5 shrink-0 translate-y-0.5" strokeWidth={1.75} aria-hidden />
                      {t.type_label}
                    </dt>
                    <dd className="min-w-0">
                      <div className="font-medium tnum">{t.headline}</div>
                      <ValueList values={t.values} shown={5} className="text-muted-foreground" />
                    </dd>
                  </div>
                ))}
              </dl>
            )}
          </section>
        )}
      </div>

      {!single && c.evidence.length > 0 && (
        <section className="mb-12">
          <SectionTitle
            title="Siła dowodów według rodzin cech"
            hint="Ile par zgłoszeń łączy dana rodzina cech i jak mocno (średnio, 0–100%)."
          />
          <div className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
            <table className="w-full min-w-[600px] border-collapse text-sm">
              <thead>
                <tr className="border-y text-xs text-muted-foreground">
                  <th scope="col" className="py-2 pr-4 text-left font-medium">
                    Rodzina cech
                  </th>
                  <th scope="col" className="w-24 py-2 pr-4 text-right font-medium">
                    Pary
                  </th>
                  <th scope="col" className="w-20 py-2 pr-4 text-right font-medium">
                    Siła
                  </th>
                  <th scope="col" className="py-2 text-left font-medium">
                    Najmocniejsze ślady
                  </th>
                </tr>
              </thead>
              <tbody>
                {c.evidence.map((f) => (
                  <tr key={f.family} className="border-b align-baseline">
                    <td className="py-2.5 pr-4 font-medium whitespace-nowrap">
                      <span className="inline-flex items-center gap-2">
                        <FamilyIcon family={f.family} className="translate-y-0.5" />
                        <span className="first-letter:uppercase">{f.label}</span>
                      </span>
                    </td>
                    <td className="py-2.5 pr-4 text-right tnum">
                      {f.pairs} z {f.total_pairs}
                    </td>
                    <td className="py-2.5 pr-4 text-right font-semibold tnum">{pct(f.mean)}</td>
                    <td className="py-2.5 text-muted-foreground">
                      {f.kinds
                        .slice(0, 3)
                        .map((k) => k.label.toLowerCase())
                        .join(", ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {c.links.length > 0 && (
        <section className="mb-4">
          <SectionTitle
            title="Powiązania z innymi kampaniami"
            hint="Ten sam sprawca: ta sama osoba lub grupa, rozpoznana po wspólnym koncie lub pikselu śledzącym. Ten sam program do stron: tylko wskazówka, bo korzysta z niego wielu oszustów."
          />
          <div className="border-t">
            {c.links.map((l) => (
              <div key={l.id} className="grid gap-x-8 gap-y-3 border-b py-4 md:grid-cols-[220px_minmax(0,1fr)_minmax(0,1fr)]">
                <div>
                  <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <span
                      aria-hidden
                      className="size-2 rounded-full"
                      style={{ background: TIER_META[l.kind === "operator" ? "operator" : "toolkit"].color }}
                    />
                    {l.kind === "operator" ? "Ten sam sprawca" : "Ten sam program do stron"}
                  </div>
                  <div className="mt-0.5 text-sm font-medium break-words">{l.label}</div>
                </div>
                <ul className="min-w-0 space-y-1 text-sm text-muted-foreground">
                  {l.traces.slice(0, 5).map((t, i) => (
                    <li key={i} className="flex min-w-0 gap-2">
                      <Pin className="mt-1 size-3 shrink-0" strokeWidth={1.75} aria-hidden />
                      <ValueText value={t} className="text-[12.5px]" />
                    </li>
                  ))}
                </ul>
                <div className="min-w-0 text-sm">
                  {l.campaigns.length > 0 ? (
                    <ul className="space-y-1">
                      {l.campaigns.map((r) => (
                        <li key={r.id}>
                          <Link href={campaignHref(r.id)} className="flex items-start gap-1.5 text-link underline-offset-4 hover:underline">
                            <ArrowUpRight className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                            <span className="line-clamp-1">
                              <CampaignTitle text={r.label} />
                            </span>
                          </Link>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <span className="text-muted-foreground">Brak innych kampanii tego sprawcy w bazie.</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </>
  );
}


function groupByFamily(rows: TraitRow[]) {
  const map = new Map<string, { family: string; label: string; rows: TraitRow[] }>();
  for (const row of rows) {
    const key = row.family || "other";
    if (!map.has(key)) map.set(key, { family: key, label: row.family_label || "inne", rows: [] });
    map.get(key)!.rows.push(row);
  }
  const rank = (f: string) => (FAMILY_ORDER.includes(f) ? FAMILY_ORDER.indexOf(f) : FAMILY_ORDER.length);
  return [...map.values()].sort((a, b) => rank(a.family) - rank(b.family));
}

function MemberCard({ member: m, className }: { member: Member; className?: string }) {
  return (
    <Link href={caseHref(m.id)} className={`group block min-w-0 ${className ?? ""}`}>
      <ThumbImage thumb={m.thumb} width={360} className="aspect-[4/5] w-full rounded-lg border" />
      <div className="mt-1.5 truncate text-sm font-medium underline-offset-4 group-hover:underline">{m.title}</div>
      <div className="truncate font-mono text-[11px] text-muted-foreground">{m.domain ?? "bez domeny"}</div>
      {m.duplicate_of && <div className="text-xs text-warning-foreground">duplikat</div>}
    </Link>
  );
}

function MemberGrid({ members, className }: { members: Member[]; className?: string }) {
  return (
    <ul className={`grid grid-cols-[repeat(auto-fill,minmax(150px,1fr))] gap-x-3 gap-y-2 ${className ?? ""}`}>
      {members.map((m) => (
        <li key={m.id} className="min-w-0">
          <Link href={caseHref(m.id)} className="group flex min-w-0 items-center gap-2">
            <ThumbImage thumb={m.thumb} width={96} alt="" className="size-9 shrink-0 rounded-md border" />
            <span className="min-w-0 text-xs leading-tight">
              <span className="block truncate text-[13px] font-medium underline-offset-4 group-hover:underline">{shortTitle(m.title)}</span>
              <span className="block truncate font-mono text-[11px] text-muted-foreground">{m.domain ?? "bez domeny"}</span>
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

/** The page's answer for a first-time reader: one sentence, the ad versions, what is shared, what varies. */
function Story({ c }: { c: CampaignDetail }) {
  const pair = c.size === 2 ? c.pairs[0] : undefined;
  const withImage = c.comparison.variants.filter((v) => v.thumb);
  return (
    <section aria-labelledby="story-title" className="mb-12 rounded-xl border bg-card shadow-card">
      <div className="p-5 sm:p-6">
        <p className="flex items-center gap-2 text-[13px] font-medium text-muted-foreground">
          <Link2 className="size-4" strokeWidth={1.75} aria-hidden />
          Dlaczego to jedna kampania
        </p>
        <h2 id="story-title" className="mt-2 max-w-3xl text-[21px] leading-snug font-semibold text-pretty sm:text-[26px]">
          {c.verdict}
        </h2>
        <div className="mt-3 max-w-3xl space-y-1.5 text-sm leading-relaxed text-pretty text-foreground/85">
          {c.summary.slice(0, 2).map((s, i) => (
            <p key={i}>{s}</p>
          ))}
        </div>
        {pair && (
          <p className="mt-3 text-[13px] text-muted-foreground">
            <Term k="score">Siła powiązania</Term>: <span className="font-semibold text-foreground tnum">{strength(pair.score)}</span>
          </p>
        )}
      </div>

      <div className="border-t px-5 py-5 sm:px-6">
        <div className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
          <h3 className="text-[15px] font-semibold">
            {withImage.length > 0
              ? `${plural(withImage.length, ["wersja reklamy", "wersje reklamy", "wersji reklamy"])} w ${plural(c.size, ["zgłoszeniu", "zgłoszeniach", "zgłoszeniach"])}`
              : "Reklamy"}
          </h3>
          <p className="text-[13px] text-muted-foreground">Prawie identyczne obrazy liczymy jako jedną wersję.</p>
        </div>
        <VariantGrid variants={c.comparison.variants.slice(0, VARIANTS_SHOWN)} members={c.members} offset={0} />
        {c.comparison.variants.length > VARIANTS_SHOWN && (
          <details className="group mt-3">
            <summary className="cursor-pointer list-none text-xs text-muted-foreground underline decoration-border underline-offset-4 hover:text-foreground [&::-webkit-details-marker]:hidden">
              <span className="group-open:hidden">pokaż wszystkie wersje ({c.comparison.variants.length})</span>
              <span className="hidden group-open:inline">pokaż mniej</span>
            </summary>
            <VariantGrid variants={c.comparison.variants.slice(VARIANTS_SHOWN)} members={c.members} offset={VARIANTS_SHOWN} className="mt-3" />
          </details>
        )}
      </div>

      <StoryBlock title="Co jest takie samo" tone="same" icon={<Check className="size-4" strokeWidth={2.25} aria-hidden />}>
        {c.comparison.same.length === 0 && (
          <p className="py-3 text-sm text-muted-foreground">
            Żaden ślad nie występuje we wszystkich zgłoszeniach – kampanię łączą wspólne ślady par zgłoszeń (poniżej).
          </p>
        )}
        {c.comparison.same.map((row) => (
          <SameRow key={row.key} row={row} members={c.members} />
        ))}
      </StoryBlock>

      <StoryBlock title="Co się różni" tone="different" icon={<EqualNot className="size-4" strokeWidth={2.25} aria-hidden />}>
        {withImage.length > 1 && (
          <StoryRow label="Obraz reklamy" hint="Oszuści wymieniają obraz, żeby reklama wyglądała na nową.">
            <span className="text-sm">
              <span className="font-medium tnum">{plural(withImage.length, ["wersja", "wersje", "wersji"])}</span>
              <span className="text-muted-foreground"> (pokazane wyżej)</span>
            </span>
          </StoryRow>
        )}
        {c.comparison.different.map((row) => (
          <DiffRowView key={row.key} row={row} />
        ))}
        {withImage.length <= 1 && c.comparison.different.length === 0 && (
          <p className="py-3 text-sm text-muted-foreground">Nie znaleźliśmy istotnych różnic między tymi reklamami.</p>
        )}
      </StoryBlock>
    </section>
  );
}

function VariantGrid({ variants, members, offset, className }: { variants: Variant[]; members: Member[]; offset: number; className?: string }) {
  return (
    <ul className={`grid grid-cols-2 gap-3 sm:grid-cols-[repeat(auto-fill,minmax(150px,1fr))] ${className ?? ""}`}>
      {variants.map((v, i) => {
        const first = members[v.members[0]];
        return (
          <li key={i} className="min-w-0 sm:max-w-[220px]">
            <Link href={caseHref(first.id)} className="group relative block">
              {v.thumb ? (
                <ThumbImage thumb={v.thumb} width={480} className="aspect-[4/5] w-full rounded-lg border" />
              ) : (
                <div className="flex aspect-[4/5] w-full flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-3 text-center text-xs text-muted-foreground">
                  <ImageOff className="size-5" strokeWidth={1.5} aria-hidden />
                  brak obrazu reklamy w zgłoszeniu
                </div>
              )}
              {v.members.length > 1 && (
                <span className="absolute top-2 right-2 rounded-full bg-foreground px-2 py-0.5 text-xs font-semibold text-background tnum">
                  ×{v.members.length}
                </span>
              )}
            </Link>
            <div className="mt-1.5 break-words text-sm font-medium">{v.thumb ? `Wersja ${offset + i + 1}` : "Bez obrazu"}</div>
            <Coverage
              members={members}
              indices={v.members}
              label={v.members.length === 1 ? shortTitle(first.title) : plural(v.members.length, "report")}
              className="mt-0.5 [&_summary>span:first-child]:font-normal [&_summary>span:first-child]:text-muted-foreground"
            />
          </li>
        );
      })}
    </ul>
  );
}

function StoryBlock({ title, icon, tone, children }: { title: string; icon: React.ReactNode; tone: "same" | "different"; children: React.ReactNode }) {
  const marker = tone === "same" ? "bg-success/15 text-success-foreground" : "bg-warning/20 text-warning-foreground";
  return (
    <div className="border-t px-5 pt-4 pb-2 sm:px-6">
      <h3 className="flex items-center gap-2 text-[15px] font-semibold">
        <span className={`grid size-6 place-items-center rounded-full ${marker}`}>{icon}</span>
        {title}
      </h3>
      <div className="mt-1 divide-y">{children}</div>
    </div>
  );
}

function StoryRow({ label, hint, children, aside }: { label: string; hint?: string; children: React.ReactNode; aside?: React.ReactNode }) {
  return (
    <div className="grid gap-x-6 gap-y-2 py-3.5 lg:grid-cols-[230px_minmax(0,1fr)_250px]">
      <div className="min-w-0">
        <div className="text-sm font-medium">{label}</div>
        {hint && <div className="mt-0.5 text-[13px] leading-snug text-muted-foreground">{hint}</div>}
      </div>
      <div className="min-w-0">{children}</div>
      {aside && <div className="min-w-0">{aside}</div>}
    </div>
  );
}

/** One shared thing, shown once, with the reports it occurs in. */
function SameRow({ row, members }: { row: SharedRow; members: Member[] }) {
  let evidence: React.ReactNode;
  if (row.style === "images" && row.images.length > 0) {
    evidence = (
      <div className="flex flex-wrap gap-2">
        {row.images.map((t) => (
          <ThumbImage key={t.artifact_id} thumb={t} width={200} alt={t.name} className="size-16 rounded-md border sm:size-20" />
        ))}
      </div>
    );
  } else if (row.style === "snippet") {
    evidence = (
      <p className="max-w-2xl text-[13px] leading-relaxed text-muted-foreground">
        {row.before} <mark className="rounded-[3px] bg-warning/25 px-0.5 text-foreground">{row.text}</mark> {row.after}
      </p>
    );
  } else if (row.style === "badge") {
    evidence = <span className="inline-block max-w-full truncate rounded-md border bg-subtle px-2 py-1 font-mono text-xs">{row.text}</span>;
  } else {
    evidence = <div className={`text-sm break-words ${row.mono ? "font-mono text-[13px]" : ""}`}>{row.text}</div>;
  }
  return (
    <StoryRow label={row.label} hint={row.hint} aside={<Coverage members={members} indices={row.members} />}>
      {evidence}
    </StoryRow>
  );
}

/** Something that varies: only the distinct values, most common first. */
function DiffRowView({ row }: { row: DiffRow }) {
  const chip = (v: DiffRow["values"][number]) => (
    <li key={v.text} className={`inline-flex max-w-full items-baseline gap-1.5 rounded-md border px-2 py-1 text-[13px] ${v.mono ? "font-mono text-xs" : ""}`}>
      <span className="min-w-0 break-words">{v.text}</span>
      {v.members.length > 1 && <span className="shrink-0 font-sans text-[11px] text-muted-foreground tnum">×{v.members.length}</span>}
    </li>
  );
  const rest = row.values.slice(VALUES_SHOWN);
  return (
    <StoryRow label={row.label} hint={row.hint}>
      <div className="mb-1.5 text-sm font-medium tnum">{plural(row.values.length, ["wartość", "różne wartości", "różnych wartości"])}</div>
      <ul className="flex flex-wrap gap-1.5">{row.values.slice(0, VALUES_SHOWN).map(chip)}</ul>
      {rest.length > 0 && (
        <details className="group mt-1.5">
          <summary className="cursor-pointer list-none text-xs text-muted-foreground underline decoration-border underline-offset-4 hover:text-foreground [&::-webkit-details-marker]:hidden">
            <span className="group-open:hidden">+{rest.length} więcej</span>
            <span className="hidden group-open:inline">pokaż mniej</span>
          </summary>
          <ul className="mt-1.5 flex flex-wrap gap-1.5">{rest.map(chip)}</ul>
        </details>
      )}
    </StoryRow>
  );
}

/** Recognised public figures and brands: each once, the detected face next to the reference photo. */
function People({ c }: { c: CampaignDetail }) {
  const n = c.members.length;
  return (
    <section className="mb-12">
      <SectionTitle
        title="Rozpoznane osoby i marki"
        icon={<ScanFace className="size-4 text-muted-foreground" strokeWidth={1.75} aria-hidden />}
        hint="Twarze wykrywamy na reklamach i zdjęciach ze strony, porównujemy z bazą osób publicznych; twarze spoza bazy są od razu odrzucane. Osoba to wskazówka: sama nie łączy kampanii."
      />
      <ul className="border-t">
        {c.recognised.map((r) => (
          <PersonRow key={r.key} r={r} members={c.members} single={n === 1} />
        ))}
      </ul>
    </section>
  );
}

export function PersonRow({ r, members, single }: { r: Recognised; members: Member[]; single: boolean }) {
  const face = "size-14 rounded-lg border bg-subtle object-cover";
  return (
    <li className="grid gap-x-6 gap-y-3 border-b py-3.5 sm:grid-cols-[minmax(0,1fr)_auto] lg:grid-cols-[230px_minmax(0,1fr)_250px]">
      <div className="min-w-0">
        <div className="text-[11px] text-muted-foreground">{r.kind === "person" ? "Osoba publiczna" : "Marka, pod którą podszywa się strona"}</div>
        <div className="text-sm font-semibold">{r.name}</div>
        {r.method === "text" && (
          <div className="mt-0.5 text-xs text-muted-foreground">
            wymieniona w tekście{r.matched ? <>: „{r.matched}”</> : null}
          </div>
        )}
        {r.similarity !== null && r.method !== "text" && (
          <div className="mt-0.5 text-xs text-muted-foreground tnum">
            <Term k={r.kind === "person" ? "faceSimilarity" : "logoSimilarity"}>
              {r.kind === "person" ? "podobieństwo twarzy" : "podobieństwo logo"} {num(r.similarity, 2)}
            </Term>
            {r.threshold !== null && <span> · próg rozpoznania {num(r.threshold, 2)}</span>}
          </div>
        )}
      </div>
      {/* eslint-disable @next/next/no-img-element */}
      <div className="flex items-start gap-3">
        {r.thumb && (
          <figure className="text-center">
            <img src={`${r.thumb}${r.thumb.includes("?") ? "&" : "?"}w=128`} alt={`Twarz wykryta w materiale: ${r.name}`} loading="lazy" className={face} />
            <figcaption className="mt-1 text-[11px] text-muted-foreground">na materiale</figcaption>
          </figure>
        )}
        {r.thumb && r.reference && <EqualLike />}
        {r.reference && (
          <figure className="text-center" title={`Zdjęcie z Wikimedia Commons. Autor: ${r.reference.author}. Licencja: ${r.reference.license}.`}>
            <img src={`${r.reference.url}?w=128`} alt={`Zdjęcie wzorcowe: ${r.name}`} loading="lazy" className={face} />
            <figcaption className="mt-1 text-[11px] text-muted-foreground">w bazie</figcaption>
          </figure>
        )}
        {r.reference && (
          <p className="max-w-[220px] self-center text-[11px] leading-snug text-muted-foreground">
            Wzorzec: Wikimedia Commons, {r.reference.author}, {r.reference.license}
          </p>
        )}
      </div>
      {/* eslint-enable @next/next/no-img-element */}
      <div className="min-w-0 space-y-1.5 text-[13px] sm:col-span-2 lg:col-span-1">
        {single ? (
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {r.ad.length > 0 && <Where icon="ad">w reklamie</Where>}
            {r.page.length > 0 && <Where icon="page">na stronie docelowej</Where>}
          </div>
        ) : (
          <>
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              <Where icon="ad" muted={r.ad.length === 0}>
                w reklamie: {r.ad.length === 0 ? "brak" : plural(r.ad.length, "report")}
              </Where>
              <Where icon="page" muted={r.page.length === 0}>
                na stronie: {r.page.length === 0 ? "brak" : plural(r.page.length, "report")}
              </Where>
            </div>
            <Coverage members={members} indices={r.members} />
          </>
        )}
      </div>
    </li>
  );
}

function EqualLike() {
  return (
    <span aria-hidden className="mt-5 text-lg leading-none text-muted-foreground">
      ≈
    </span>
  );
}

function Where({ icon, muted, children }: { icon: "ad" | "page"; muted?: boolean; children: React.ReactNode }) {
  const Icon = icon === "ad" ? Megaphone : PanelTop;
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap tnum ${muted ? "text-muted-foreground" : ""}`}>
      <Icon className="size-3.5 shrink-0" strokeWidth={1.75} aria-hidden />
      {children}
    </span>
  );
}

const CREATIVE_LABEL = { different: "różne obrazy reklam", same: "ten sam obraz reklamy", unknown: "" } as const;

function PairRow({ pair: p, byId }: { pair: PairLink; byId: Map<string, Member> }) {
  const creative = { label: CREATIVE_LABEL[p.creatives] };
  return (
    <li className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-3 border-b py-2">
      <span className="flex -space-x-1.5">
        <ThumbImage thumb={byId.get(p.a.id)?.thumb ?? null} width={96} alt="" className="size-8 rounded-md border bg-card" />
        <ThumbImage thumb={byId.get(p.b.id)?.thumb ?? null} width={96} alt="" className="size-8 rounded-md border bg-card" />
      </span>
      <span className="min-w-0">
        <span className="block truncate font-medium">
          <Link href={caseHref(p.a.id)} className="underline-offset-4 hover:underline">
            {shortTitle(p.a.label)}
          </Link>
          <span className="mx-1.5 text-muted-foreground">i</span>
          <Link href={caseHref(p.b.id)} className="underline-offset-4 hover:underline">
            {shortTitle(p.b.label)}
          </Link>
          {creative.label && <span className="ml-2 text-xs font-normal text-muted-foreground">{creative.label}</span>}
        </span>
        <span className="block truncate text-xs text-muted-foreground">{p.reasons.slice(0, 3).join(" · ")}</span>
      </span>
      <span className="font-semibold tnum">{strength(p.score)}</span>
    </li>
  );
}

/** Fused pair score; never rounds a near-certain link up to a flat "100%". */
function strength(score: number) {
  if (score >= 0.9995) return "ponad 99,9%";
  return score >= 0.95 ? pct1(score) : pct(score);
}
