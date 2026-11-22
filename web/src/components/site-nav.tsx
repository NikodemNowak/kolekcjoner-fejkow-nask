"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion } from "motion/react";
import { cn } from "@/lib/utils";

const LINKS: { href: string; label: string; short?: string }[] = [
  { href: "/", label: "Kampanie" },
  { href: "/analyze", label: "Analizuj reklamę", short: "Analizuj" },
  { href: "/graph", label: "Graf" },
  { href: "/methodology", label: "Metodyka" },
];

export function SiteNav() {
  const path = usePathname();
  return (
    <nav aria-label="Główna nawigacja" className="-mx-1 flex h-full items-stretch gap-0.5 overflow-x-auto [scrollbar-width:none]">
      {LINKS.map((link) => {
        const active =
          link.href === "/"
            ? path === "/" || path.startsWith("/campaigns") || path.startsWith("/cases")
            : path.startsWith(link.href);
        return (
          <Link
            key={link.href}
            href={link.href}
            aria-current={active ? "page" : undefined}
            className={cn(
              "relative flex items-center px-2 text-sm sm:px-2.5 whitespace-nowrap transition-colors",
              active ? "font-medium text-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            <span className={link.short ? "hidden md:inline" : undefined}>{link.label}</span>
            {link.short && <span className="md:hidden">{link.short}</span>}
            {active && (
              <motion.span
                layoutId="nav-underline"
                className="absolute inset-x-2.5 -bottom-px h-px bg-foreground"
                transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
              />
            )}
          </Link>
        );
      })}
    </nav>
  );
}
