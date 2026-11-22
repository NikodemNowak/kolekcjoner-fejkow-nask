import { ImageOff } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Thumb } from "@/lib/types";

/* eslint-disable @next/next/no-img-element */
export function ThumbImage({
  thumb,
  className,
  width = 480,
  alt,
  fit = "cover",
}: {
  /** "contain" keeps the whole image visible (wide screenshots in a portrait frame). */
  fit?: "cover" | "contain";
  thumb: Thumb | null;
  className?: string;
  width?: number;
  alt?: string;
}) {
  if (!thumb) {
    return (
      <div
        className={cn("flex items-center justify-center bg-subtle text-muted-foreground/70", className)}
        role="img"
        aria-label="Brak obrazu"
      >
        <ImageOff className="size-4" strokeWidth={1.5} />
      </div>
    );
  }
  return (
    <img
      src={`${thumb.url}?w=${width}`}
      alt={alt ?? thumb.name}
      loading="lazy"
      decoding="async"
      className={cn("bg-subtle", fit === "contain" ? "object-contain" : "object-cover object-top", className)}
    />
  );
}
