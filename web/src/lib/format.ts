const PL = "pl-PL";

const percent0 = new Intl.NumberFormat(PL, { style: "percent", maximumFractionDigits: 0 });
const percent1 = new Intl.NumberFormat(PL, {
  style: "percent",
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});
const integer = new Intl.NumberFormat(PL, { maximumFractionDigits: 0 });

/** Share 0..1 as a whole percent, e.g. 0.832 -> "83%". */
export const pct = (v: number) => percent0.format(v).replace(/ /g, " ");
/** Share 0..1 with one decimal, e.g. 0.973 -> "97,3%". */
export const pct1 = (v: number) => percent1.format(v).replace(/ /g, " ");
/** Fixed decimals with a Polish comma, e.g. 0.6 -> "0,60". */
export const num = (v: number, digits = 2) =>
  new Intl.NumberFormat(PL, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(v);
export const int = (v: number) => integer.format(v);
/** Percentage points between two shares, e.g. 0.44 -> "44 p.p.". */
export const pp = (v: number) => `${integer.format(Math.round(v * 100))} p.p.`;
/** Seconds as "1,5 s" or "2 min 43 s". */
export function seconds(v: number) {
  if (v < 10) return `${num(v, 1)} s`;
  if (v < 60) return `${integer.format(Math.round(v))} s`;
  const m = Math.floor(v / 60);
  const s = Math.round(v - m * 60);
  return `${m} min ${s} s`;
}

export const caseHref = (id: string) => `/cases/${encodeURIComponent(id)}`;
export const campaignHref = (id: string) => `/campaigns/${encodeURIComponent(id)}`;

export { plural, pluralWord } from "./plural";

/** Shorten at a word boundary; never mid-word unless a single word is too long. */
export function smartTruncate(text: string, max: number) {
  if (text.length <= max) return text;
  const cut = text.slice(0, max - 1);
  const space = cut.lastIndexOf(" ");
  const base = space > max * 0.55 ? cut.slice(0, space) : cut;
  return `${base.replace(/[\s,.:;–-]+$/, "")}…`;
}
