/** Liveness probe for monitoring; public even when the demo password is set. */
export const dynamic = "force-static";

export function GET() {
  return new Response("ok\n", { headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" } });
}
