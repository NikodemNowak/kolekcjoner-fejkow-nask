import {
  Files,
  Fingerprint,
  ImageIcon,
  LayoutTemplate,
  Server,
  Type,
  UserRound,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

export const FAMILY_ICONS: Record<string, LucideIcon> = {
  ids: Fingerprint,
  infra: Server,
  asset: Files,
  template: LayoutTemplate,
  image: ImageIcon,
  text: Type,
  person: UserRound,
};

export const FAMILIES: { id: string; short: string; label: string; hint: string }[] = [
  { id: "ids", short: "Numery kont i stron, liczniki wejść.", label: "identyfikatory", hint: "Identyfikatory landingu i reklam, konta kreatora stron, piksele, reklamodawcy (z HAR i HTML)." },
  { id: "asset", short: "Identyczne pliki na stronach.", label: "wspólne pliki", hint: "Identyczne bajtowo pliki stron (SHA-256): obrazy, skrypty, czcionki." },
  { id: "infra", short: "Serwery i punkty zbierania danych.", label: "infrastruktura", hint: "Hosty zewnętrzne, punkty zbierania danych, przekierowania, adresy IP, certyfikaty." },
  { id: "template", short: "Układ i kod strony.", label: "szablon strony", hint: "Struktura HTML i klasy CSS (MinHash), sygnatury ścieżek i SDK kreatora stron." },
  { id: "image", short: "Te same lub podobne obrazy.", label: "wygląd (obraz)", hint: "Skróty percepcyjne pHash i PDQ oraz podobieństwo treści obrazu (SigLIP2)." },
  { id: "text", short: "Nagłówki i treść, także z obrazu.", label: "tekst i język", hint: "Nagłówki, tekst strony, OCR i transkrypcja nagrań; MinHash i BGE-M3." },
  { id: "person", short: "Kto i jaka marka. Tylko kontekst.", label: "postać i marka", hint: "Wizerunki osób publicznych i podszywane marki; wyłącznie kontekst." },
];

export function FamilyIcon({ family, className }: { family: string; className?: string }) {
  const Icon = FAMILY_ICONS[family] ?? Fingerprint;
  return <Icon className={cn("size-4 shrink-0 text-muted-foreground", className)} strokeWidth={1.75} aria-hidden />;
}
