import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // A stray package-lock.json at the repo root makes Next infer that as the
  // workspace, so Turbopack resolves and watches from there. Pin it here.
  turbopack: { root: __dirname },
  // Only the self-hosted image (Dockerfile) builds standalone; Vercel and `next start` keep the default.
  ...(process.env.NEXT_OUTPUT === "standalone" && { output: "standalone", outputFileTracingRoot: __dirname }),
};

export default nextConfig;
