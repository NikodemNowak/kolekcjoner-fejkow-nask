import "server-only";

const API = process.env.KF_API_URL ?? "http://127.0.0.1:8600";

export async function api<T>(path: string): Promise<T | null> {
  const res = await fetch(`${API}${path}`, { cache: "no-store" });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`API ${path}: ${res.status}`);
  return (await res.json()) as T;
}
