/** Plain-Polish explanations of the few technical words the UI keeps. Shown in tooltips. */
export const GLOSSARY = {
  operator: "Sprawca: ta sama osoba lub grupa prowadząca kampanie. Rozpoznajemy ją po wspólnym koncie, pikselu śledzącym lub reklamodawcy.",
  toolkit: "Ten sam program do tworzenia stron. Korzysta z niego wielu oszustów, więc sam niczego nie dowodzi.",
  landing: "Strona docelowa: strona, na którą trafia się po kliknięciu reklamy.",
  creative: "Kreacja: obraz lub film, który widać w reklamie.",
  tier: "Poziom dowodu mówi, ile znaczy wspólny ślad: od mocnego (ta sama kampania) po samą wskazówkę (kontekst).",
  score: "Wynik 0–100% mówi, jak mocno reklamę łączą ślady z kampanią. Im wyżej, tym pewniej.",
  domain: "Domena to adres strony. Zapisujemy go z nawiasami, np. example[.]com, żeby nie dało się go przypadkiem kliknąć.",
  pixel: "Piksel śledzący to kod, który zlicza wejścia z reklam. Ten sam numer oznacza to samo konto reklamowe.",
  faceSimilarity: "Podobieństwo odcisku twarzy do zdjęć z bazy (0–1). To nie jest prawdopodobieństwo.",
  logoSimilarity: "Podobieństwo logo do wzorca marki (0–1). To nie jest prawdopodobieństwo.",
} as const;

export type GlossaryKey = keyof typeof GLOSSARY;
