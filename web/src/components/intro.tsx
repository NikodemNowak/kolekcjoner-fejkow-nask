"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, X } from "lucide-react";

const KEY = "kf-intro-hidden";

const STEPS = [
  {
    title: "Zbieramy",
    text: "Zrzuty reklam, zapisane strony i nagrania. Odczytujemy tekst, twarze, loga, domeny i ślady techniczne.",
  },
  {
    title: "Łączymy",
    text: "Reklamy ze wspólnymi plikami, kontem, pikselem lub domeną tworzą kampanię. Sama osoba czy marka nie wystarczy.",
  },
  {
    title: "Wyjaśniamy",
    text: "Każde połączenie ma powód, który można sprawdzić: na stronie kampanii, w analizie nowej reklamy i na grafie.",
  },
];

/** First-visit guide on the overview: three steps and where to start. Can be hidden for good. */
export function Intro() {
  const [hidden, setHidden] = useState(false);
  useEffect(() => {
    try {
      setHidden(localStorage.getItem(KEY) === "1");
    } catch {
      /* storage unavailable: keep the guide visible */
    }
  }, []);
  if (hidden) return null;
  return (
    <section aria-label="Jak działa Kolekcjoner Fejków" className="relative mb-8 rounded-xl border bg-card p-4 shadow-card sm:p-5">
      <button
        type="button"
        onClick={() => {
          setHidden(true);
          try {
            localStorage.setItem(KEY, "1");
          } catch {
            /* ignore */
          }
        }}
        className="absolute top-3 right-3 rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
        aria-label="Ukryj wprowadzenie"
      >
        <X className="size-4" />
      </button>
      <h2 className="pr-8 text-[15px] font-semibold">Jak to działa</h2>
      <ol className="mt-3 grid gap-4 sm:grid-cols-3">
        {STEPS.map((s, i) => (
          <li key={s.title} className="grid grid-cols-[1.75rem_minmax(0,1fr)] gap-x-2">
            <span className="grid size-6 place-items-center rounded-full border text-xs font-medium tnum">{i + 1}</span>
            <div>
              <div className="text-sm font-medium">{s.title}</div>
              <p className="mt-0.5 text-[13px] leading-relaxed text-muted-foreground">{s.text}</p>
            </div>
          </li>
        ))}
      </ol>
      <div className="mt-4 flex flex-wrap gap-x-5 gap-y-1 border-t pt-3 text-[13px] font-medium">
        <Link href="/analyze" className="inline-flex items-center gap-1 text-link hover:underline">
          Sprawdź własną reklamę <ArrowRight className="size-3.5" />
        </Link>
        <Link href="/graph" className="inline-flex items-center gap-1 text-link hover:underline">
          Zobacz graf powiązań <ArrowRight className="size-3.5" />
        </Link>
        <Link href="/methodology" className="inline-flex items-center gap-1 text-link hover:underline">
          Jak liczymy podobieństwo <ArrowRight className="size-3.5" />
        </Link>
      </div>
    </section>
  );
}
