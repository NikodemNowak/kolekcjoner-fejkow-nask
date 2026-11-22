import { NextResponse, type NextRequest } from "next/server";

/**
 * Access gate for the public demo. When KF_DEMO_PASSWORD is set, every route (pages, /api/*,
 * images, static files) asks for HTTP Basic credentials; only /healthz stays open for
 * monitoring. Without the variable the site behaves as before (local and tailnet use).
 * Credentials come from the environment only and are never part of the repository.
 */
const REALM = 'Basic realm="Kolekcjoner Fejkow", charset="UTF-8"';
const encoder = new TextEncoder();

async function digest(value: string): Promise<Uint8Array> {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", encoder.encode(value)));
}

/** Compares two strings without leaking where they differ: fixed-length digests, no early exit. */
async function safeEqual(a: string, b: string): Promise<boolean> {
  const [x, y] = await Promise.all([digest(a), digest(b)]);
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}

function decodeBasic(header: string | null): { user: string; password: string } | null {
  if (!header || !header.toLowerCase().startsWith("basic ")) return null;
  try {
    const bytes = Uint8Array.from(atob(header.slice(6).trim()), (c) => c.charCodeAt(0));
    const text = new TextDecoder().decode(bytes);
    const at = text.indexOf(":");
    if (at < 0) return null;
    return { user: text.slice(0, at), password: text.slice(at + 1) };
  } catch {
    return null;
  }
}

export async function middleware(request: NextRequest) {
  const password = process.env.KF_DEMO_PASSWORD;
  if (!password) return NextResponse.next();
  if (request.nextUrl.pathname === "/healthz") return NextResponse.next();

  const user = process.env.KF_DEMO_USER || "jury";
  const given = decodeBasic(request.headers.get("authorization"));
  // Evaluate both comparisons always, so timing does not reveal which part was wrong.
  const [userOk, passwordOk] = await Promise.all([safeEqual(given?.user ?? "", user), safeEqual(given?.password ?? "", password)]);
  if (given && userOk && passwordOk) return NextResponse.next();

  return new NextResponse("Wymagane logowanie.", {
    status: 401,
    headers: { "WWW-Authenticate": REALM, "Cache-Control": "no-store", "Content-Type": "text/plain; charset=utf-8" },
  });
}

// Everything, including /api/*, thumbnails and Next's own static files.
export const config = { matcher: "/:path*" };
