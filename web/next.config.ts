import type { NextConfig } from "next";

const api = process.env.KF_API_URL ?? "http://127.0.0.1:8600";

const nextConfig: NextConfig = {
  // A second build directory lets a test server run next to the live one.
  distDir: process.env.KF_DIST_DIR || ".next",
  // No next/image: keeps the optional sharp/libvips dependency unused.
  images: { unoptimized: true },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${api}/api/:path*` }];
  },
  // Uploads go straight to the API through the rewrite; allow screenshots and HAR files.
  experimental: { middlewareClientMaxBodySize: "200mb" },
};

export default nextConfig;
