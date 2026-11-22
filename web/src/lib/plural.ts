/**
 * Polish plurals in one place. Noun forms are (1, 2–4, 5+):
 * 1 zgłoszenie, 2 zgłoszenia, 5 zgłoszeń, 22 zgłoszenia, 112 zgłoszeń.
 */
export type Forms = readonly [one: string, few: string, many: string];

export const NOUNS = {
  report: ["zgłoszenie", "zgłoszenia", "zgłoszeń"],
  campaign: ["kampania", "kampanie", "kampanii"],
  operator: ["sprawca", "sprawcy", "sprawców"],
  pair: ["para", "pary", "par"],
  file: ["plik", "pliki", "plików"],
  feature: ["cecha", "cechy", "cech"],
  trace: ["ślad", "ślady", "śladów"],
  domain: ["domena", "domeny", "domen"],
  person: ["osoba", "osoby", "osób"],
  image: ["obraz", "obrazy", "obrazów"],
  value: ["wartość", "wartości", "wartości"],
  fragment: ["fragment", "fragmenty", "fragmentów"],
  unique: ["unikatowe", "unikatowe", "unikatowych"],
  duplicate: ["duplikat", "duplikaty", "duplikatów"],
  variant: ["wariant", "warianty", "wariantów"],
  screenshot: ["zrzut", "zrzuty", "zrzutów"],
  more: ["kolejny", "kolejne", "kolejnych"],
  commonSkipped: ["pospolity pominięto", "pospolite pominięto", "pospolitych pominięto"],
} as const satisfies Record<string, Forms>;

export type Noun = keyof typeof NOUNS;

/** The noun form that goes with a count. */
export function pluralWord(n: number, forms: Forms | Noun): string {
  const [one, few, many] = typeof forms === "string" ? NOUNS[forms] : forms;
  const abs = Math.abs(Math.trunc(n));
  if (abs === 1) return one;
  const d = abs % 10;
  const h = abs % 100;
  if (d >= 2 && d <= 4 && (h < 12 || h > 14)) return few;
  return many;
}

const integer = new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 0 });

/** Count with its noun, e.g. plural(2, "report") -> "2 zgłoszenia". */
export function plural(n: number, forms: Forms | Noun): string {
  return `${integer.format(n)} ${pluralWord(n, forms)}`;
}
