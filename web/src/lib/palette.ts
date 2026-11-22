// Colours are CSS variables (see globals.css), so they follow the theme without JS.
export const OPERATOR_SLOTS = 6;

export function operatorColor(index: number | null | undefined) {
  if (index === null || index === undefined) return "var(--op-none)";
  return `var(--op-${index % OPERATOR_SLOTS})`;
}

export const TIERS = ["campaign", "operator", "toolkit", "context"] as const;
export type Tier = (typeof TIERS)[number];

export const TIER_META: Record<Tier, { label: string; short: string; color: string; hint: string }> = {
  campaign: {
    label: "Ta sama kampania",
    short: "Kampania",
    color: "var(--tier-campaign)",
    hint: "Mocny ślad: jeden taki wystarcza, by uznać reklamy za tę samą kampanię.",
  },
  operator: {
    label: "Ten sam sprawca",
    short: "Sprawca",
    color: "var(--tier-operator)",
    hint: "Wskazuje na tę samą osobę lub grupę (to samo konto, ten sam piksel), także w innych kampaniach.",
  },
  toolkit: {
    label: "Ten sam program do stron",
    short: "Program",
    color: "var(--tier-toolkit)",
    hint: "Strony zrobiono tym samym programem do tworzenia stron. Używa go wielu oszustów, więc to tylko wskazówka.",
  },
  context: {
    label: "Kontekst",
    short: "Kontekst",
    color: "var(--tier-context)",
    hint: "Osoba, marka albo temat reklamy. Pomaga się zorientować, ale niczego nie dowodzi.",
  },
};

export function tierMeta(tier: string | null | undefined) {
  return TIER_META[(tier as Tier) ?? "context"] ?? TIER_META.context;
}
