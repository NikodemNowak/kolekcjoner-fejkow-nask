import type { Metadata } from "next";
import {
  ArrowDown,
  ChevronDown,
  ChevronRight,
  CircleSlash,
  Database,
  EqualNot,
  Files,
  Fingerprint,
  FolderInput,
  GitMerge,
  ImageOff,
  Layers,
  Link2,
  ScanSearch,
  Tag,
  Type,
  UserRound,
  UserRoundCog,
  WifiOff,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { FAMILIES, FamilyIcon } from "@/components/family-icon";
import { api } from "@/lib/api";
import { int, num, pct } from "@/lib/format";
import { plural } from "@/lib/plural";
import { TIER_META, TIERS, type Tier } from "@/lib/palette";
import evaluation from "@/data/evaluation.json";
import type { Summary } from "@/lib/types";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "Metodyka" };

const cfg = evaluation.config;

const TIER_CARD: Record<Tier, { icon: LucideIcon; text: string }> = {
  campaign: { icon: Link2, text: "Wystarcza sam: ta sama strona docelowa, te same pliki albo ten sam obraz reklamy." },
  operator: { icon: UserRoundCog, text: "Ta sama osoba lub grupa prowadząca kampanie: to samo konto albo piksel śledzący." },
  toolkit: { icon: Wrench, text: "Ten sam program do tworzenia stron. Używa go wielu oszustów, więc sam nie łączy." },
  context: { icon: Tag, text: "Osoba, marka, temat. Wskazówka dla analityka, nigdy dowód." },
};

/** Fixed-point score with a Polish comma, the way metrics are quoted in the evaluation. */
const metric = (v: number | null) => (v === null ? "—" : num(v, 3));
const share = (v: number | null) => (v === null ? "—" : pct(v));
/** Headline form of a score: 1 -> "1,0", 0.973 -> "0,973". */
const headline = (v: number) => (v === 1 ? "1,0" : num(v, 3));

export default async function MethodologyPage() {
  const summary = await api<Summary>("/api/summary").catch(() => null);
  const kampanie = evaluation.clustering[0];
  const worstError = Math.max(...evaluation.openSet.map((r) => r.error));

  const stages: { icon: LucideIcon; title: string; text: string; stat: string | null }[] = [
    {
      icon: FolderInput,
      title: "Wczytanie",
      text: "Zrzuty, ruch sieciowy, zapisane strony, wideo.",
      stat: summary ? `${plural(summary.reports, "report")}, ${plural(summary.artifacts, "file")}` : null,
    },
    {
      icon: ScanSearch,
      title: "Cechy",
      text: "Z plików wyciągamy identyfikatory, tekst, obrazy.",
      stat: summary ? plural(summary.features, "feature") : null,
    },
    {
      icon: Fingerprint,
      title: "Ślady",
      text: "Rzadkie wartości zostają, pospolite odpadają.",
      stat: "4 poziomy dowodu",
    },
    {
      icon: GitMerge,
      title: "Porównanie",
      text: "Wspólne ślady dwóch reklam dają wynik 0–100%.",
      stat: `próg ${pct(cfg.tau_assign)}`,
    },
    {
      icon: Layers,
      title: "Kampanie",
      text: "Reklamy ponad progiem tworzą kampanię.",
      stat: summary ? `${plural(summary.multi_campaigns, "campaign")}, ${plural(summary.operators, "operator")}` : null,
    },
  ];

  const results = [
    { value: headline(kampanie.p ?? 0), label: "Precyzja", text: "Żadne dwie reklamy z różnych kampanii nie zostały połączone." },
    { value: headline(kampanie.f1), label: "Ocena grupowania", text: "Jedna liczba łącząca trafność i kompletność (miara F1). 1,0 to wynik bezbłędny." },
    { value: pct(worstError), label: "Fałszywe przypisania", text: "Żaden nowy materiał nie trafił do niewłaściwej kampanii." },
    { value: pct(evaluation.openSet[0].accuracy), label: "Znane warianty", text: "Każdy odłożony wariant wrócił do swojej kampanii." },
  ];

  const limits: { icon: LucideIcon; text: string }[] = [
    { icon: ImageOff, text: "Sam zrzut ekranu niesie najmniej informacji. Najwięcej dają nagranie ruchu (HAR) i zapisana strona." },
    { icon: Database, text: "Zbiór testowy jest mały, więc wyniki to wskazanie, nie gwarancja." },
    { icon: UserRound, text: "Rozpoznana osoba lub marka to tylko kontekst. Nigdy nie łączy kampanii sama." },
    { icon: WifiOff, text: "Analiza działa lokalnie i nie otwiera adresów. Widzi tylko przesłane pliki." },
  ];

  return (
    <article className="mx-auto max-w-[960px] pt-2 sm:pt-6">
      <header className="mb-12 max-w-[680px]">
        <h1 className="text-[28px] leading-tight font-semibold sm:text-[34px]">Metodyka</h1>
        <p className="mt-4 text-[17px] leading-relaxed text-pretty text-muted-foreground">
          Oszuści zmieniają obraz, nagłówek i domenę, ale rzadko wszystko naraz. Szukamy tego, co zostaje.
        </p>
      </header>

      <Section title="Jak to działa" hint="Pięć kroków od przesłanych plików do kampanii.">
        <ol className="grid gap-y-5 md:grid-cols-5 md:gap-x-2">
          {stages.map((s, i) => (
            <li key={s.title} className="relative grid grid-cols-[2.75rem_minmax(0,1fr)] gap-x-4 md:block md:pr-4">
              {i < stages.length - 1 && (
                <>
                  <span aria-hidden className="absolute top-[1.375rem] right-0 left-[3.25rem] hidden h-px bg-border md:block" />
                  <ChevronRight aria-hidden className="absolute top-[0.875rem] -right-1 hidden size-4 text-muted-foreground/60 md:block" />
                  <span aria-hidden className="absolute top-12 bottom-[-1.25rem] left-[1.375rem] w-px bg-border md:hidden" />
                </>
              )}
              <span className="relative grid size-11 place-items-center rounded-full border bg-card shadow-card">
                <s.icon className="size-5" strokeWidth={1.75} aria-hidden />
              </span>
              <div className="md:mt-3">
                <h3 className="text-[15px] font-semibold">
                  <span className="mr-1.5 font-mono text-xs font-normal text-muted-foreground tnum">{i + 1}</span>
                  {s.title}
                </h3>
                <p className="mt-0.5 text-[13px] leading-snug text-muted-foreground">{s.text}</p>
                {s.stat && <p className="mt-1.5 text-xs font-medium tnum">{s.stat}</p>}
              </div>
            </li>
          ))}
        </ol>
      </Section>

      <Section
        title="Jak dwie reklamy trafiają do jednej kampanii"
        hint="Przykład poglądowy. Reklamy wyglądają inaczej, ale prowadzą na tę samą stronę."
      >
        <LinkExample />
      </Section>

      <Section title="Na co patrzymy" hint="Siedem niezależnych grup cech. Gdy oszust wymieni jedną, zostają pozostałe.">
        <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
          {FAMILIES.map((f) => (
            <li key={f.id} className="rounded-xl border bg-card p-4 shadow-card">
              <span className="grid size-9 place-items-center rounded-lg bg-subtle">
                <FamilyIcon family={f.id} className="size-[18px] text-foreground" />
              </span>
              <h3 className="mt-3 text-sm font-semibold first-letter:uppercase">{f.label}</h3>
              <p className="mt-0.5 text-[13px] leading-snug text-muted-foreground">{f.short}</p>
            </li>
          ))}
          <li className="col-span-2 rounded-xl border border-dashed p-4 sm:col-span-1">
            <span className="grid size-9 place-items-center rounded-lg bg-subtle">
              <CircleSlash className="size-[18px]" strokeWidth={1.75} aria-hidden />
            </span>
            <h3 className="mt-3 text-sm font-semibold">Brak danych to nie różnica</h3>
            <p className="mt-0.5 text-[13px] leading-snug text-muted-foreground">Gdy czegoś nie ma w jednej z reklam, nie obniża to wyniku.</p>
          </li>
        </ul>
      </Section>

      <Section title="Ile waży ślad" hint="Nie każdy wspólny ślad znaczy to samo. Dzielimy je na cztery poziomy, od dowodu po samą wskazówkę.">
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {TIERS.map((t) => {
            const Icon = TIER_CARD[t].icon;
            return (
              <li key={t} className="rounded-xl border bg-card p-4 shadow-card">
                <div className="flex items-center justify-between">
                  <Icon className="size-5" strokeWidth={1.75} aria-hidden />
                  <span className="text-[11px] text-muted-foreground tnum">do {pct(cfg.tierCaps[t])} wyniku</span>
                </div>
                <h3 className="mt-3 flex items-center gap-2 text-sm font-semibold">
                  <span aria-hidden className="size-2.5 rounded-full" style={{ background: TIER_META[t].color }} />
                  {TIER_META[t].label}
                </h3>
                <p className="mt-1 text-[13px] leading-snug text-muted-foreground">{TIER_CARD[t].text}</p>
              </li>
            );
          })}
        </ul>
      </Section>

      <Section title="Decyzja dla nowej reklamy" hint="Nową reklamę porównujemy z każdą kampanią w bazie. Wynik wpada do jednej z trzech stref.">
        <DecisionScale />
      </Section>

      <Section title="Wyniki" hint={`Sprawdzone na danych konkursowych: ${evaluation.corpus}`}>
        <dl className="grid grid-cols-2 gap-x-6 gap-y-8 border-y py-7 lg:grid-cols-4">
          {results.map((r) => (
            <div key={r.label}>
              <dd className="text-[40px] leading-none font-semibold tracking-tight tnum sm:text-[48px]">{r.value}</dd>
              <dt className="mt-3 text-sm font-semibold">{r.label}</dt>
              <dd className="mt-0.5 text-[13px] leading-snug text-muted-foreground">{r.text}</dd>
            </div>
          ))}
        </dl>

        <details className="group mt-4">
          <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 rounded-lg border bg-card px-3 py-2 text-sm font-medium shadow-card transition-colors hover:bg-surface [&::-webkit-details-marker]:hidden">
            <ChevronDown className="size-4 transition-transform group-open:rotate-180" aria-hidden />
            Szczegóły wyników
          </summary>

          <TableTitle title="Grupowanie" note="Czy reklamy jednej kampanii trafiają razem, a różnych osobno. 1,000 oznacza wynik bezbłędny. Precyzja: ile połączeń było słusznych. Czułość: ile prawdziwych połączeń znaleziono. B-cubed i ARI to inne miary tej samej zgodności." />
          <Table
            head={["", "Precyzja", "Czułość", "Ocena łączna (F1)", "B-cubed F1", "ARI"]}
            widths={["25%", "15%", "15%", "15%", "15%", "15%"]}
            align={["left", "right", "right", "right", "right", "right"]}
            numeric
            rows={evaluation.clustering.map((r) => [
              <span key="l" className="font-sans font-medium">{r.level}</span>,
              metric(r.p),
              metric(r.r),
              <strong key="f">{metric(r.f1)}</strong>,
              metric(r.bcubed),
              metric(r.ari),
            ])}
          />
          <Note>Czułość {metric(kampanie.r)}: jedna prawdziwa para pozostała niepołączona.</Note>

          <TableTitle title="Nowy materiał" note="Część danych odkładamy, budujemy bazę z reszty i przypisujemy odłożone zgłoszenia." />
          <Table
            head={["Test", "Trafne decyzje", "Błędne przypisania", "Do weryfikacji"]}
            widths={["46%", "18%", "18%", "18%"]}
            align={["left", "right", "right", "right"]}
            rows={evaluation.openSet.map((r) => [
              <div key="l">
                <div className="font-medium">{r.split}</div>
                <div className="text-[13px] text-muted-foreground">{r.question}</div>
              </div>,
              <strong key="a" className="tnum">{share(r.accuracy)}</strong>,
              <span key="e" className="tnum">{share(r.error)}</span>,
              <span key="r" className="tnum">{share(r.review)}</span>,
            ])}
          />
          <Note>
            Błędne przypisanie to nowa reklama dopisana do niewłaściwej kampanii albo znany wariant uznany za coś nowego.
            Gdy system nie był pewny, oddał decyzję analitykowi.
          </Note>

          <TableTitle title="Niepełne dane" note="Z każdego wariantu zostawiamy tylko jeden rodzaj pliku." />
          <Table
            head={["Co dostaje system", "Przypisane poprawnie"]}
            widths={["64%", "36%"]}
            align={["left", "right"]}
            rows={evaluation.sparse.map((r) => [
              r.input,
              <span key="v" className="tnum">
                <strong>
                  {r.correct} z {r.total}
                </strong>{" "}
                <span className="text-muted-foreground">{r.unit}</span>
              </span>,
            ])}
          />
          <Note>
            Na świeżych zrzutach reklam z sieci, spoza obu korpusów, liczba fałszywych powiązań wyniosła{" "}
            {evaluation.wild.falseLinks}.
          </Note>
          <p className="mt-6 text-xs text-muted-foreground">
            Źródło: ewaluacja zespołu (etykiety ścisłe, profil pełny), stan na{" "}
            {new Date(evaluation.updated).toLocaleDateString("pl-PL")}. Pełny protokół: docs/METHODOLOGY.md.
          </p>
        </details>
      </Section>

      <Section title="Ograniczenia">
        <ul className="grid gap-x-10 gap-y-4 sm:grid-cols-2">
          {limits.map((l) => (
            <li key={l.text} className="grid grid-cols-[1.75rem_minmax(0,1fr)] text-sm leading-relaxed">
              <l.icon className="mt-0.5 size-[18px] text-muted-foreground" strokeWidth={1.75} aria-hidden />
              <span>{l.text}</span>
            </li>
          ))}
        </ul>
      </Section>
    </article>
  );
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="mb-16">
      <h2 className="text-xl font-semibold sm:text-[22px]">{title}</h2>
      {hint && <p className="mt-1 max-w-[680px] text-sm leading-relaxed text-pretty text-muted-foreground">{hint}</p>}
      <div className="mt-6">{children}</div>
    </section>
  );
}

function TableTitle({ title, note }: { title: string; note: string }) {
  return (
    <div className="mt-8 mb-3">
      <h3 className="text-[15px] font-semibold">{title}</h3>
      <p className="text-[13px] text-muted-foreground">{note}</p>
    </div>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return <p className="mt-3 max-w-[680px] text-[13px] leading-relaxed text-pretty text-muted-foreground">{children}</p>;
}

/* ------------------------------------------------------------------ linking example */

/** A made-up ad card. Content is illustrative only; nothing here comes from real reports. */
function AdCard({ name, headline, domain, art }: { name: string; headline: string; domain: string; art: "person" | "chart" }) {
  return (
    <div className="min-w-0 overflow-hidden rounded-xl border bg-card shadow-card">
      <div className="relative aspect-[5/3] bg-subtle">
        <svg viewBox="0 0 200 120" className="absolute inset-0 size-full" aria-hidden>
          {art === "person" ? (
            <g className="fill-muted-foreground/45">
              <circle cx="100" cy="46" r="22" />
              <path d="M52 120c4-28 22-42 48-42s44 14 48 42z" />
            </g>
          ) : (
            <g className="fill-muted-foreground/45">
              <rect x="42" y="70" width="22" height="34" rx="3" />
              <rect x="74" y="52" width="22" height="52" rx="3" />
              <rect x="106" y="62" width="22" height="42" rx="3" />
              <rect x="138" y="28" width="22" height="76" rx="3" />
            </g>
          )}
        </svg>
        <span className="absolute top-2 left-2 rounded-md bg-card/90 px-1.5 py-0.5 text-[11px] font-medium">{name}</span>
      </div>
      <div className="p-3">
        <p className="text-[13px] leading-snug font-medium">{headline}</p>
        <p className="mt-1 truncate font-mono text-[11px] text-muted-foreground">{domain}</p>
      </div>
    </div>
  );
}

function LinkExample() {
  const traces: { icon: LucideIcon; title: string; text: string }[] = [
    { icon: Files, title: "12 tych samych plików", text: "na obu stronach docelowych" },
    { icon: Fingerprint, title: "Ten sam identyfikator strony", text: "w kreatorze stron" },
    { icon: Type, title: "Tekst zgodny w 91%", text: "na obu stronach docelowych" },
  ];
  return (
    <figure className="mx-auto max-w-[720px]">
      <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-3 sm:gap-5">
        <AdCard name="Reklama A" headline="Znany prezenter ujawnił, jak zarabia" domain="oferta-a[.]example" art="person" />
        <div className="flex w-14 flex-col items-center gap-1 text-center text-[11px] leading-tight text-muted-foreground sm:w-20">
          <EqualNot className="size-5 text-foreground" strokeWidth={1.75} aria-hidden />
          inny obraz, nagłówek i domena
        </div>
        <AdCard name="Reklama B" headline="Nowy sposób na domowe oszczędności" domain="promo-b[.]example" art="chart" />
      </div>

      <div aria-hidden className="mx-[18%] h-5 rounded-b-xl border-x border-b" />
      <div aria-hidden className="flex justify-center">
        <span className="h-4 w-px bg-border" />
      </div>

      <div className="rounded-xl border bg-card p-4 shadow-card">
        <p className="mb-3 text-center text-xs font-medium text-muted-foreground">Wspólne ślady</p>
        <ul className="grid gap-3 sm:grid-cols-3">
          {traces.map((t) => (
            <li key={t.title} className="flex items-start gap-3 sm:flex-col sm:items-center sm:gap-2 sm:text-center">
              <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-subtle">
                <t.icon className="size-[18px]" strokeWidth={1.75} aria-hidden />
              </span>
              <span>
                <span className="block text-sm font-semibold">{t.title}</span>
                <span className="block text-[13px] leading-snug text-muted-foreground">{t.text}</span>
              </span>
            </li>
          ))}
        </ul>
      </div>

      <div aria-hidden className="flex flex-col items-center py-1 text-muted-foreground/70">
        <span className="h-3 w-px bg-border" />
        <ArrowDown className="size-4" />
      </div>

      <figcaption className="mx-auto flex w-fit items-center gap-2.5 rounded-full border bg-card py-2 pr-5 pl-4 shadow-card">
        <span aria-hidden className="size-2.5 rounded-full" style={{ background: "var(--success)" }} />
        <span className="text-[15px] font-semibold">Ta sama kampania</span>
      </figcaption>
    </figure>
  );
}

/* ------------------------------------------------------------------ decision scale */

/** The 0–100% score scale split into the three answers the system can give. */
function DecisionScale() {
  const review = cfg.review_min_score;
  const tau = cfg.tau_assign;
  const zones = [
    {
      from: 0,
      to: review,
      color: "var(--link)",
      label: "Nowy wzorzec",
      range: `poniżej ${pct(review)}`,
      text: "Żadna kampania nie jest wystarczająco blisko.",
    },
    {
      from: review,
      to: tau,
      color: "var(--warning)",
      label: "Do weryfikacji",
      range: `${int(review * 100)}–${pct(tau)}`,
      text: "Ślady są, ale za słabe albo dwie kampanie pasują podobnie. Decyduje analityk.",
    },
    {
      from: tau,
      to: 1,
      color: "var(--success)",
      label: "Wariant znanej kampanii",
      range: `od ${pct(tau)}`,
      text: `Wynik ponad progiem i przewaga co najmniej ${int(cfg.assign_margin * 100)} p.p. nad kolejną kampanią.`,
    },
  ];
  return (
    <figure>
      <div className="relative pt-7 pb-5">
        <div className="flex h-3 gap-0.5">
          {zones.map((z) => (
            <div
              key={z.label}
              className="h-full first:rounded-l-full last:rounded-r-full"
              style={{ width: `${(z.to - z.from) * 100}%`, background: z.color }}
            />
          ))}
        </div>
        <span className="absolute top-0 -translate-x-1/2 text-xs font-semibold whitespace-nowrap tnum" style={{ left: `${tau * 100}%` }}>
          próg {pct(tau)}
        </span>
        <span aria-hidden className="absolute top-5 h-7 w-px bg-foreground" style={{ left: `${tau * 100}%` }} />
        <div className="absolute inset-x-0 bottom-0 flex justify-between text-[11px] text-muted-foreground tnum">
          <span>0%</span>
          <span>100%</span>
        </div>
      </div>
      <figcaption className="mt-4 grid gap-3 sm:grid-cols-3">
        {zones.map((z) => (
          <div key={z.label} className="rounded-xl border bg-card p-4 shadow-card">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <span aria-hidden className="size-2.5 rounded-full" style={{ background: z.color }} />
              {z.label}
            </div>
            <div className="mt-1 text-xs text-muted-foreground tnum">{z.range}</div>
            <p className="mt-2 text-[13px] leading-snug text-muted-foreground">{z.text}</p>
          </div>
        ))}
      </figcaption>
    </figure>
  );
}

function Table({
  head,
  rows,
  widths,
  align,
  numeric,
  className,
}: {
  head: string[];
  rows: React.ReactNode[][];
  widths: string[];
  align?: ("left" | "right")[];
  numeric?: boolean;
  className?: string;
}) {
  return (
    <div className={`-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0 ${className ?? ""}`}>
      <table className={`w-full table-fixed border-collapse text-sm ${head.length > 2 ? "min-w-[560px]" : ""}`}>
        <colgroup>
          {widths.map((w, i) => (
            <col key={i} style={{ width: w }} />
          ))}
        </colgroup>
        <thead>
          <tr className="border-y border-foreground/80">
            {head.map((h, i) => (
              <th
                key={i}
                scope="col"
                className={`py-2 pr-4 text-xs font-medium text-muted-foreground last:pr-0 ${align?.[i] === "right" ? "text-right" : "text-left"}`}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r} className="border-b align-top">
              {row.map((cell, i) => (
                <td
                  key={i}
                  className={`py-2.5 pr-4 leading-relaxed last:pr-0 ${align?.[i] === "right" ? "text-right" : "text-left"} ${numeric && i > 0 ? "tnum" : ""} ${i > 0 && !numeric && align?.[i] !== "right" ? "text-muted-foreground" : ""}`}
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

