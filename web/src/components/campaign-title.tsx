import { Fragment } from "react";

const TOKEN = /(\[osoba\]|(?<![\p{L}\p{N}])N(?![\p{L}\p{N}]))/u;

/**
 * A campaign headline. Placeholders of the headline template (a masked person, a number that
 * changes between variants) are drawn as quiet tokens instead of raw "[osoba]" / "N".
 */
export function CampaignTitle({ text }: { text: string }) {
  const parts = text.split(TOKEN);
  return (
    <>
      {parts.map((part, i) =>
        part === "[osoba]" || part === "N" ? (
          <span
            key={i}
            title={part === "N" ? "Liczba, która zmienia się między wariantami" : "Osoba, która zmienia się między wariantami"}
            className="mx-px inline-block translate-y-[-0.08em] rounded-[5px] border border-dashed border-foreground/25 px-1.5 align-middle text-[0.72em] leading-[1.5] font-normal tracking-normal text-muted-foreground"
          >
            {part === "N" ? "liczba" : "osoba"}
          </span>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      )}
    </>
  );
}

/** Plain-text variant for places that cannot render tokens (select options, SVG labels). */
export function plainTitle(text: string) {
  return text.replace(/\[osoba\]/g, "…").replace(/(?<![\p{L}\p{N}])N(?![\p{L}\p{N}])/gu, "…").replace(/\s+/g, " ").trim();
}
