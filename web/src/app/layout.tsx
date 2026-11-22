import type { Metadata, Viewport } from "next";
import Link from "next/link";
import { Geist, Geist_Mono } from "next/font/google";
import { ThemeProvider } from "@/components/theme-provider";
import { ThemeToggle } from "@/components/theme-toggle";
import { SiteNav } from "@/components/site-nav";
import { LogoMark, Wordmark } from "@/components/brand/logo";
import { MotionProvider } from "@/components/motion";
import { TooltipProvider } from "@/components/ui/tooltip";
import "./globals.css";

const sans = Geist({ variable: "--font-sans", subsets: ["latin", "latin-ext"] });
const mono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin", "latin-ext"] });

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000"),
  title: { default: "Kolekcjoner Fejków", template: "%s · Kolekcjoner Fejków" },
  description: "Łączenie reklam-oszustw w kampanie na podstawie wspólnych, sprawdzalnych śladów.",
  applicationName: "Kolekcjoner Fejków",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fbfbfd" },
    { media: "(prefers-color-scheme: dark)", color: "#16181d" },
  ],
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="pl" suppressHydrationWarning>
      <body className={`${sans.variable} ${mono.variable} font-sans antialiased`}>
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
          <MotionProvider>
            <TooltipProvider delayDuration={150}>
              <div className="flex min-h-dvh flex-col">
                <header className="sticky top-0 z-40 border-b bg-background/85 backdrop-blur-md supports-[backdrop-filter]:bg-background/75">
                  <div className="mx-auto flex h-14 max-w-7xl items-stretch gap-2 px-4 sm:gap-8 sm:px-6">
                    <Link href="/" className="flex shrink-0 items-center gap-2" aria-label="Kolekcjoner Fejków, przegląd">
                      <LogoMark />
                      <Wordmark className="hidden sm:inline" />
                    </Link>
                    <div className="min-w-0 flex-1">
                      <SiteNav />
                    </div>
                    <div className="flex items-center">
                      <ThemeToggle />
                    </div>
                  </div>
                </header>
                <main className="mx-auto w-full max-w-7xl flex-1 px-4 pt-6 pb-12 sm:px-6 sm:pt-8">{children}</main>
                <footer className="border-t">
                  <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-x-6 gap-y-2 px-4 py-4 text-xs text-muted-foreground sm:px-6">
                    <span className="inline-flex items-center gap-2">
                      <LogoMark className="size-3.5 text-muted-foreground" />
                      Kolekcjoner Fejków · HackNation 2026 · zadanie NASK
                    </span>
                    <span>Analiza lokalna, tylko do odczytu. Materiały organizatora nie są udostępniane publicznie.</span>
                  </div>
                </footer>
              </div>
            </TooltipProvider>
          </MotionProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
