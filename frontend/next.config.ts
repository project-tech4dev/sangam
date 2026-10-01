import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // A stray package-lock.json at the repo root makes Next infer that as the
  // workspace, so Turbopack resolves and watches from there. Pin it here.
  turbopack: { root: __dirname },
};

export default nextConfig;
