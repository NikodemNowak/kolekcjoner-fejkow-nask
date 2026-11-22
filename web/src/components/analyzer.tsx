"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { AnimatePresence, motion } from "motion/react";
import { ArrowRight, Check, DatabaseZap, Plus, Undo2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CampaignTitle } from "@/components/campaign-title";
import { FAMILIES } from "@/components/family-icon";
import { OperatorDot } from "@/components/operator-badge";
import { ThumbImage } from "@/components/thumb";
import { ValueText } from "@/components/value-text";
import { FoundSection, SimilarSection } from "@/components/analyze-found";
import { EASE_OUT } from "@/components/motion";
import { campaignHref, caseHref, num, pct, plural, pp } from "@/lib/format";
import { tierMeta } from "@/lib/palette";
import { cn } from "@/lib/utils";
import type { CampaignSummary, Ref, Verdict } from "@/lib/types";

type Committed = { case: Ref; campaign: Ref | null };
type CommitResponse = { verdicts: Verdict[]; committed: Committed[]; already: Committed[]; skipped: string[] };
type Outcome = { kind: "saved" | "already" | "checked" | "skipped" | "undone"; items: Committed[] };

/** What happened to the analysed report in the database, right under the verdict. */
function OutcomeNote({ outcome, onUndo, undoing, error }: { outcome: Outcome; onUndo: () => void; undoing: boolean; error: string | null }) {
  const first = outcome.items[0];
  const links = first && outcome.kind !== "undone" && (
    <span className="flex flex-wrap gap-x-4 gap-y-1 text-[13px] font-medium">
      <Link href={caseHref(first.case.id)} className="text-link underline-offset-4 hover:underline">
        Zobacz zgłoszenie
      </Link>
      {first.campaign && (
        <Link href={campaignHref(first.campaign.id)} className="text-link underline-offset-4 hover:underline">
          Zobacz kampanię
        </Link>
      )}
      <Link href={`/graph?focus=${encodeURIComponent(first.case.id)}`} className="text-link underline-offset-4 hover:underline">
        Pokaż na grafie
      </Link>
    </span>
  );
  const text = {
    saved: { title: "Zapisano w bazie jako nowe zgłoszenie", note: "Jest już widoczne w Kampaniach i na Grafie powiązań." },
    already: { title: "To samo zgłoszenie jest już w bazie", note: "Nie dodaliśmy go drugi raz." },
    checked: { title: "Tylko sprawdzono, nic nie zapisano", note: "Wyłącz „Tylko sprawdź, nie zapisuj”, żeby dodać zgłoszenie do bazy." },
    skipped: { title: "Nie zapisano w bazie", note: "Sam adres nie daje nic do porównania. Wgraj zrzut ekranu albo zapisaną stronę." },
    undone: { title: "Cofnięto dodanie zgłoszenia", note: "Zgłoszenie usunięto z bazy, kampanii i grafu." },
  }[outcome.kind];
  const good = outcome.kind === "saved" || outcome.kind === "already";
  return (
    <section role="status" aria-label="Zapis w bazie" className="rounded-xl border bg-card p-4 shadow-card sm:p-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="flex min-w-0 gap-3">
          <span className={cn("mt-0.5 grid size-6 shrink-0 place-items-center rounded-full", good ? "bg-success/15 text-success-foreground" : "bg-subtle text-muted-foreground")}>
            {good ? <Check className="size-4" strokeWidth={2.25} aria-hidden /> : <DatabaseZap className="size-3.5" strokeWidth={1.75} aria-hidden />}
          </span>
          <div className="min-w-0">
            <h3 className="text-[15px] font-semibold break-words">{text.title}</h3>
            <p className="mt-0.5 text-[13px] leading-relaxed text-muted-foreground">{text.note}</p>
            {links && <div className="mt-2">{links}</div>}
          </div>
        </div>
        {outcome.kind === "saved" && (
          <Button variant="outline" size="sm" className="shrink-0" onClick={onUndo} disabled={undoing}>
            <Undo2 className="size-3.5" strokeWidth={1.75} aria-hidden />
            {undoing ? "Cofanie…" : "Cofnij dodanie"}
          </Button>
        )}
      </div>
      {error && <p className="mt-2 text-[13px] text-destructive">{error}</p>}
    </section>
  );
}

const ACCEPT = ".png,.jpg,.jpeg,.webp,.har,.html,.htm,.mhtml,.mht,.pdf,.mp4,.webm,.mov";

const STEPS = [
  { title: "Wczytanie", text: "Odczyt plików, scalenie duplikatów" },
  { title: "Cechy", text: "OCR, obraz, twarze, identyfikatory" },
  { title: "Porównanie", text: "Zestawienie z kampaniami w bazie" },
  { title: "Werdykt", text: "Decyzja i jej powody" },
];

function fileSize(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${num(bytes / 1024 / 1024, 1)} MB`;
}

export function Analyzer() {
  const [files, setFiles] = useState<File[]>([]);
  const [text, setText] = useState("");
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<Verdict[] | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [campaigns, setCampaigns] = useState<Map<string, CampaignSummary>>(new Map());
  const [checkOnly, setCheckOnly] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const [undoing, setUndoing] = useState(false);
  const [undoError, setUndoError] = useState<string | null>(null);
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);
  const resultRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // On narrow screens the verdict renders below the form: bring it into view.
    if (results && window.matchMedia("(max-width: 1023px)").matches)
      resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [results]);

  const loadCampaigns = useCallback(() => {
    fetch("/api/campaigns", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : []))
      .then((list: CampaignSummary[]) => setCampaigns(new Map(list.map((c) => [c.id, c]))))
      .catch(() => undefined);
  }, []);
  useEffect(loadCampaigns, [loadCampaigns]);

  useEffect(() => {
    const image = files.find((f) => f.type.startsWith("image/"));
    if (!image) {
      setPreview(null);
      return;
    }
    const url = URL.createObjectURL(image);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [files]);

  useEffect(() => {
    if (!busy) return;
    const start = Date.now();
    const t = setInterval(() => setElapsed((Date.now() - start) / 1000), 100);
    return () => clearInterval(t);
  }, [busy]);

  const ready = files.length > 0 || text.trim().length > 0;

  const payload = () => {
    const body = new FormData();
    if (files.length) files.forEach((f) => body.append("files", f, f.name));
    else body.append("text", text.trim());
    return body;
  };

  /** Removes the report saved by the last analysis (uploads only). */
  const undo = async () => {
    if (!outcome || outcome.kind !== "saved" || undoing) return;
    setUndoing(true);
    setUndoError(null);
    try {
      const res = await fetch(`/api/uploads/${encodeURIComponent(outcome.items[0].case.id)}`, { method: "DELETE" });
      if (!res.ok) {
        const detail = await res.json().catch(() => null);
        throw new Error(typeof detail?.detail === "string" ? detail.detail : `Serwer analizy zwrócił błąd ${res.status}.`);
      }
      setOutcome({ kind: "undone", items: outcome.items });
      loadCampaigns();
      router.refresh();
    } catch (e) {
      setUndoError(e instanceof TypeError ? "Brak połączenia z serwerem analizy." : e instanceof Error ? e.message : "Nie udało się cofnąć dodania.");
    } finally {
      setUndoing(false);
    }
  };

  const submit = async () => {
    if (!ready || busy) return;
    setBusy(true);
    setDone(false);
    setError(null);
    setResults(null);
    setOutcome(null);
    setUndoError(null);
    setElapsed(0);
    const body = payload();
    try {
      // By default every analysed report is saved; "check only" compares without saving.
      const res = await fetch(checkOnly ? "/api/assign" : "/api/assign/commit", { method: "POST", body });
      if (!res.ok) {
        const detail = await res.json().catch(() => null);
        throw new Error(
          typeof detail?.detail === "string"
            ? detail.detail
            : res.status === 413
              ? "Pliki są zbyt duże."
              : `Serwer analizy zwrócił błąd ${res.status}.`,
        );
      }
      const raw: Verdict[] | CommitResponse = await res.json();
      const data = Array.isArray(raw) ? raw : raw.verdicts;
      // Show the final step briefly so the progress reads as complete before the verdict.
      setDone(true);
      await new Promise((r) => setTimeout(r, 280));
      setResults(data);
      if (Array.isArray(raw)) setOutcome({ kind: "checked", items: [] });
      else if (raw.committed.length) {
        setOutcome({ kind: "saved", items: raw.committed });
        // Overview and graph are rendered on the server: refresh them so they show the new report.
        loadCampaigns();
        router.refresh();
      } else if (raw.already.length) setOutcome({ kind: "already", items: raw.already });
      else setOutcome({ kind: "skipped", items: [] });
    } catch (e) {
      setError(
        e instanceof TypeError
          ? "Brak połączenia z serwerem analizy. Sprawdź, czy API działa."
          : e instanceof Error
            ? e.message
            : "Nie udało się przeanalizować materiału.",
      );
    } finally {
      setBusy(false);
    }
  };

  const reset = () => {
    setFiles([]);
    setText("");
    setResults(null);
    setError(null);
    setDone(false);
    setOutcome(null);
    setUndoError(null);
  };

  const pickFiles = (list: File[]) => {
    setFiles(list);
    setText("");
    setResults(null);
    setError(null);
  };

  return (
    <div className="grid gap-10 lg:grid-cols-[340px_minmax(0,1fr)] lg:gap-14">
      <div>
        <div
          role="button"
          tabIndex={0}
          aria-label="Wybierz plik do analizy lub upuść go tutaj"
          onClick={() => input.current?.click()}
          onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), input.current?.click())}
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDrag(false);
            pickFiles(Array.from(e.dataTransfer.files));
          }}
          className={cn(
            "group relative cursor-pointer rounded-xl border bg-card text-center transition-colors duration-150 outline-none focus-visible:ring-3 focus-visible:ring-ring/30",
            drag ? "border-foreground bg-surface" : "hover:border-foreground/30",
            files.length === 0 && "border-dashed",
          )}
        >
          {files.length === 0 ? (
            <div className="flex min-h-64 flex-col items-center justify-center gap-4 px-6 py-8">
              <span
                className={cn(
                  "grid size-10 place-items-center rounded-full border transition-colors",
                  drag ? "border-foreground bg-foreground text-background" : "text-muted-foreground group-hover:border-foreground/40 group-hover:text-foreground",
                )}
              >
                <Plus className="size-5" strokeWidth={1.5} />
              </span>
              <div>
                <div className="text-[15px] font-medium">{drag ? "Upuść, aby dodać" : "Przeciągnij plik reklamy"}</div>
                <div className="mt-1 text-[13px] text-muted-foreground">
                  albo <span className="text-foreground underline decoration-border underline-offset-4 group-hover:decoration-foreground/50">wybierz z dysku</span>
                </div>
              </div>
              <p className="max-w-[26ch] text-xs leading-relaxed text-muted-foreground">
                Zrzut ekranu, ruch sieciowy HAR, zapisana strona, PDF lub wideo
              </p>
            </div>
          ) : (
            <div className="p-3 text-left">
              {preview && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={preview} alt="Podgląd wybranego obrazu" className="mx-auto mb-3 max-h-72 max-w-full rounded-lg border object-contain" />
              )}
              <ul className="divide-y text-[13px]">
                {files.map((f) => (
                  <li key={f.name} className="flex items-center gap-3 px-1 py-2 first:pt-1 last:pb-1">
                    <span className="min-w-0 flex-1 truncate font-medium">{f.name}</span>
                    <span className="shrink-0 text-xs text-muted-foreground tnum">{fileSize(f.size)}</span>
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        pickFiles(files.filter((x) => x !== f));
                      }}
                      aria-label={`Usuń ${f.name}`}
                      className="-m-1 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
                    >
                      <X className="size-3.5" />
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <input
            ref={input}
            type="file"
            multiple
            accept={ACCEPT}
            className="hidden"
            onChange={(e) => pickFiles(Array.from(e.target.files ?? []))}
          />
        </div>

        <label className="mt-6 block">
          <span className="mb-1.5 block text-[13px] font-medium">Albo adres strony lub nazwa produktu</span>
          <input
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              if (e.target.value) setFiles([]);
            }}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            placeholder="np. example.com/oferta"
            className="h-10 w-full rounded-lg border bg-card px-3 text-sm outline-none placeholder:text-muted-foreground/70 focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/25"
          />
        </label>

        <label className="mt-5 flex cursor-pointer items-start gap-2.5 text-[13px] leading-snug">
          <input
            type="checkbox"
            checked={checkOnly}
            onChange={(e) => setCheckOnly(e.target.checked)}
            className="mt-0.5 size-4 shrink-0 rounded border-input accent-[var(--primary)]"
          />
          <span>
            <span className="font-medium">Tylko sprawdź, nie zapisuj</span>
            <span className="block text-xs text-muted-foreground">Do testów i materiałów, które nie są oszustwem.</span>
          </span>
        </label>
        <div className="mt-4 flex items-center gap-4">
          <Button className="h-10 flex-1 text-sm" disabled={busy || !ready} onClick={submit}>
            {busy ? "Analizuję…" : "Analizuj"}
          </Button>
          {(results || ready || error) && !busy && (
            <button type="button" onClick={reset} className="text-[13px] text-muted-foreground underline decoration-border underline-offset-4 hover:text-foreground">
              Wyczyść
            </button>
          )}
        </div>
        <p className="mt-5 text-xs leading-relaxed text-muted-foreground">
          {checkOnly
            ? "Tryb sprawdzania: nic nie zostanie zapisane w bazie. Adresy nigdy nie są otwierane."
            : "Zgłoszenie zostanie zapisane w bazie. Adresy nigdy nie są otwierane."}
        </p>
      </div>

      <div className="min-w-0" aria-live="polite">
        <AnimatePresence mode="wait" initial={false}>
          {busy || (done && !results) ? (
            <motion.div key="progress" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <StepIndicator elapsed={elapsed} done={done} />
            </motion.div>
          ) : error ? (
            <motion.div key="error" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="border-y py-6">
              <p className="text-[13px] font-medium text-destructive">Błąd</p>
              <h2 className="mt-1 text-xl font-semibold">Nie udało się przeanalizować materiału</h2>
              <p className="mt-2 text-sm text-muted-foreground">{error}</p>
              <Button size="sm" variant="outline" className="mt-4" onClick={submit} disabled={!ready}>
                Spróbuj ponownie
              </Button>
            </motion.div>
          ) : results ? (
            <motion.div key="results" ref={resultRef} className="scroll-mt-20 space-y-8">
              {outcome && <OutcomeNote outcome={outcome} onUndo={undo} undoing={undoing} error={undoError} />}
              {results.map((r) => (
                <VerdictCard key={r.case_id} verdict={r} campaigns={campaigns} />
              ))}
            </motion.div>
          ) : (
            <motion.div key="idle" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
              <StepIndicator idle />
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

/** Four steps on one line (a column on phones). Idle: a preview of what will happen. */
function StepIndicator({ elapsed = 0, done = false, idle = false }: { elapsed?: number; done?: boolean; idle?: boolean }) {
  // The API answers in one request; steps advance on typical timings and complete on response.
  const active = idle ? -1 : done ? 4 : elapsed < 0.6 ? 0 : elapsed < 4 ? 1 : 2;
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <h2 className="text-[15px] font-semibold">{idle ? "Przebieg analizy" : done ? "Gotowe" : "Trwa analiza"}</h2>
        {!idle && <span className="font-mono text-xs text-muted-foreground tnum">{num(elapsed, 1)} s</span>}
      </div>
      <ol className="mt-5 grid gap-y-0 sm:grid-cols-4">
        {STEPS.map((s, i) => {
          const state = idle ? "todo" : i < active ? "done" : i === active ? "active" : "todo";
          return (
            <li key={s.title} className="relative grid grid-cols-[1.5rem_minmax(0,1fr)] gap-x-3 pb-5 last:pb-0 sm:block sm:pr-5 sm:pb-0">
              {/* Connector to the next step: vertical on phones, horizontal on wider screens. */}
              {i < STEPS.length - 1 && (
                <span aria-hidden className="absolute top-6 bottom-0 left-[11.5px] w-px bg-border sm:top-[11.5px] sm:right-0 sm:bottom-auto sm:left-6 sm:h-px sm:w-auto">
                  <span
                    className={cn(
                      "absolute inset-0 origin-top bg-foreground transition-transform duration-500 ease-out sm:origin-left",
                      state === "done" ? "scale-100" : "scale-y-0 sm:scale-x-0 sm:scale-y-100",
                    )}
                  />
                </span>
              )}
              <span
                className={cn(
                  "relative z-10 grid size-6 place-items-center rounded-full border bg-background text-[11px] transition-colors duration-200 tnum",
                  state === "done" && "border-foreground bg-foreground text-background",
                  state === "active" && "border-foreground text-foreground",
                  state === "todo" && "text-muted-foreground",
                )}
              >
                {state === "done" ? (
                  <Check className="size-3.5" strokeWidth={2.5} />
                ) : state === "active" ? (
                  <span className="size-2 animate-pulse rounded-full bg-foreground" />
                ) : (
                  i + 1
                )}
              </span>
              <div className={cn("sm:mt-3", state === "todo" && !idle && "opacity-50")}>
                <div className="text-sm font-medium">{s.title}</div>
                <div className="mt-0.5 text-[13px] leading-snug text-muted-foreground">{s.text}</div>
              </div>
            </li>
          );
        })}
      </ol>
      <p className="mt-8 max-w-prose border-t pt-4 text-[13px] leading-relaxed text-muted-foreground">
        {idle
          ? "Otrzymasz jedną z trzech odpowiedzi: wariant znanej kampanii, nowy wzorzec albo do weryfikacji. Razem z wynikiem na tle progu i śladami, które o nim zdecydowały."
          : "Pierwsza analiza po starcie serwera wczytuje modele i może potrwać kilkanaście sekund."}
      </p>
    </div>
  );
}

const TONE = {
  existing: "var(--success)",
  new: "var(--link)",
  review: "var(--warning)",
  insufficient: "var(--muted-foreground)",
} as const;

function scoreSentence(v: Verdict) {
  const parts: string[] = [];
  if (v.score <= 0) parts.push("Brak wspólnych śladów z kampaniami w bazie.");
  else if (v.score === v.threshold || pp(v.score - v.threshold) === pp(0)) parts.push(`Wynik osiąga próg ${pct(v.threshold)}.`);
  else if (v.score >= v.threshold) parts.push(`Wynik przekracza próg ${pct(v.threshold)} o ${pp(v.score - v.threshold)}.`);
  else parts.push(`Do progu ${pct(v.threshold)} brakuje ${pp(v.threshold - v.score)}.`);
  if (v.decision === "existing" || v.decision === "review") {
    if (v.margin >= v.min_margin) parts.push(`Przewaga nad kolejną kampanią: ${pp(v.margin)} (wymagane ${pp(v.min_margin)}).`);
    else parts.push(`Przewaga nad kolejną kampanią to tylko ${pp(v.margin)} (wymagane ${pp(v.min_margin)}).`);
  }
  return parts.join(" ").replace(/p\.p\.\./g, "p.p.");
}

function VerdictCard({ verdict: v, campaigns }: { verdict: Verdict; campaigns: Map<string, CampaignSummary> }) {
  const tone = TONE[v.decision];
  const target = v.campaign ?? v.closest;
  const summary = target ? campaigns.get(target.id) : undefined;
  const linked = Boolean(v.campaign);
  const reasons = v.reasons.slice(0, 6);
  const comparable = new Set(v.comparable.map((f) => f.id));
  const contributing = new Set(v.reasons.map((r) => r.family));

  return (
    <motion.article initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.25, ease: EASE_OUT }}>
      <header className="flex items-end justify-between gap-6">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-[13px] font-medium text-muted-foreground">
            <span className="size-2 rounded-full" style={{ background: tone }} aria-hidden />
            Werdykt
          </p>
          <h2 className="mt-1.5 text-[28px] leading-[1.1] font-semibold tracking-tight text-balance sm:text-4xl">{v.title}</h2>
        </div>
        <div className="shrink-0 text-right">
          <div className="text-[28px] leading-[1.1] font-semibold tracking-tight tnum sm:text-4xl">{pct(v.score)}</div>
          <div className="mt-1 text-xs text-muted-foreground">wynik dopasowania</div>
        </div>
      </header>

      {v.plain && <p className="mt-4 max-w-prose text-[17px] leading-snug font-medium text-pretty">{v.plain}</p>}

      <ScoreBar verdict={v} color={tone} />
      <p className="mt-4 max-w-prose text-sm leading-relaxed text-pretty">
        {v.explanation} <span className="text-muted-foreground">{scoreSentence(v)}</span>
      </p>

      {target && (
        <section className="mt-8 grid grid-cols-[56px_minmax(0,1fr)] items-center gap-x-4 gap-y-3 border-y py-4 sm:grid-cols-[56px_minmax(0,1fr)_auto]">
          <ThumbImage thumb={summary?.thumbs[0] ?? null} width={160} alt="" fit="contain" className="aspect-[4/5] w-full rounded-md border" />
          <div className="min-w-0">
            <div className="text-xs text-muted-foreground">{linked ? "Przypisano do kampanii" : "Najbliższa kampania, bez przypisania"}</div>
            <div className="mt-0.5 line-clamp-2 text-[15px] leading-snug font-semibold">
              <CampaignTitle text={target.label} />
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 text-[13px] text-muted-foreground">
              {summary && (
                <span className="tnum">
                  {plural(summary.size, "report")}
                </span>
              )}
              {summary?.operator && (
                <span className="inline-flex items-center gap-1.5">
                  <OperatorDot index={summary.operator_index} />
                  {summary.operator.label}
                </span>
              )}
              {!linked && <span className="tnum">wynik {pct(v.closest_score)}</span>}
            </div>
          </div>
          <Button asChild size="sm" variant={linked ? "default" : "outline"} className="col-span-2 sm:col-span-1">
            <Link href={campaignHref(target.id)}>
              Otwórz kampanię <ArrowRight className="size-3.5" />
            </Link>
          </Button>
        </section>
      )}

      {(v.duplicate_of || v.operator || v.toolkits.length > 0) && (
        <dl className="mt-4 space-y-1 text-[13px]">
          {v.duplicate_of && (
            <div className="flex gap-2">
              <dt className="text-muted-foreground">Identyczna kopia jest już w bazie:</dt>
              <dd className="font-medium">
                <Link href={caseHref(v.duplicate_of)} className="text-link underline-offset-4 hover:underline">
                  otwórz zgłoszenie
                </Link>
              </dd>
            </div>
          )}
          {(v.operator || v.toolkits.length > 0) && (
            <div className="flex flex-wrap gap-x-2">
              <dt className="text-muted-foreground">Znane powiązania:</dt>
              <dd>{[v.operator?.label, ...v.toolkits.slice(0, 3).map((t) => t.label)].filter(Boolean).join(", ")}</dd>
            </div>
          )}
        </dl>
      )}

      <FoundSection verdict={v} campaigns={campaigns} />
      <SimilarSection verdict={v} campaigns={campaigns} />

      <section className="mt-10">
        <h3 className="text-[15px] font-semibold">Dlaczego</h3>
        {reasons.length === 0 ? (
          <p className="mt-2 text-sm text-muted-foreground">Materiał nie ma wspólnych śladów z żadną kampanią w bazie.</p>
        ) : (
          <ol className="mt-3 border-t">
            {reasons.map((r, i) => {
              const tier = tierMeta(r.tier);
              return (
                <li key={i} className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-6 border-b py-3 text-sm">
                  <div className="min-w-0">
                    <div className="font-medium">{r.label}</div>
                    <div className="mt-0.5 text-[13px] break-words text-muted-foreground">
                      <ValueText value={r.text} />
                      {r.matched.length > 0 && <> · {r.matched.join(", ")}</>}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="font-medium tnum">{pct(r.weight)}</div>
                    <div className="mt-0.5 inline-flex items-center gap-1.5 text-xs text-muted-foreground" title={tier.hint}>
                      <span className="size-1.5 rounded-full" style={{ background: tier.color }} aria-hidden />
                      {r.tier_label.toLowerCase()}
                    </div>
                  </div>
                </li>
              );
            })}
          </ol>
        )}
        {reasons.length > 0 && (
          <p className="mt-2 text-xs text-muted-foreground">Liczba po prawej to siła śladu, czyli jego wkład w wynik.</p>
        )}
      </section>

      {v.hints.length > 0 && (
        <section className="mt-8">
          <h3 className="text-[15px] font-semibold">Do sprawdzenia</h3>
          <ul className="mt-2 space-y-1 text-[13px] text-muted-foreground">
            {v.hints.map((h) => (
              <li key={h} className="grid grid-cols-[1rem_minmax(0,1fr)]">
                <span>–</span>
                <span>{h}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="mt-10">
        <h3 className="text-[15px] font-semibold">Co udało się porównać</h3>
        <ul className="mt-3 flex flex-wrap gap-1.5 text-[13px]">
          {FAMILIES.map((f) => {
            const on = comparable.has(f.id);
            const hit = contributing.has(f.id);
            return (
              <li
                key={f.id}
                title={`${f.hint} ${hit ? "Są wspólne ślady." : on ? "Porównano, brak wspólnych śladów." : "Brak danych w materiale."}`}
                className={cn(
                  "inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5",
                  hit && "border-foreground/70 font-medium",
                  on && !hit && "text-foreground",
                  !on && "border-dashed text-muted-foreground/70",
                )}
              >
                {hit && <Check className="size-3.5" strokeWidth={2.25} aria-hidden />}
                {f.label}
              </li>
            );
          })}
        </ul>
        <p className="mt-2.5 text-xs leading-relaxed text-muted-foreground">
          Zaznaczone dały wspólne ślady. Przerywana ramka oznacza brak danych w materiale, co nie obniża wyniku.
        </p>
      </section>
    </motion.article>
  );
}

function ScoreBar({ verdict: v, color }: { verdict: Verdict; color: string }) {
  const runner = Math.max(0, v.score - v.margin);
  const showRunner = v.margin > 0 && runner > 0.005 && (v.decision === "existing" || v.decision === "review");
  const nearThreshold = Math.abs(runner - v.threshold) < 0.12;
  return (
    <div className="relative mt-9 mb-7" role="img" aria-label={`Wynik ${pct(v.score)}, próg ${pct(v.threshold)}`}>
      <div className="h-1.5 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full" style={{ background: color, width: `${Math.max(1, v.score * 100)}%` }} />
      </div>
      <div className="absolute -top-1.5 -bottom-1.5 w-px bg-foreground" style={{ left: `${v.threshold * 100}%` }} />
      <div className="absolute -top-6 -translate-x-1/2 text-xs font-medium whitespace-nowrap tnum" style={{ left: `${v.threshold * 100}%` }}>
        próg {pct(v.threshold)}
      </div>
      {showRunner && (
        <>
          <div className="absolute top-1/2 size-2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-foreground ring-2 ring-background" style={{ left: `${runner * 100}%` }} />
          <div
            className={cn("absolute top-3.5 text-xs whitespace-nowrap text-muted-foreground tnum", runner < 0.12 ? "" : "-translate-x-1/2", nearThreshold && "top-3.5")}
            style={{ left: `${runner * 100}%` }}
          >
            kolejna kampania {pct(runner)}
          </div>
        </>
      )}
    </div>
  );
}
