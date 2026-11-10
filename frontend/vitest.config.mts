import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: { alias: { "@": fileURLToPath(new URL(".", import.meta.url)) } },
  test: {
    exclude: ["node_modules/**", ".next/**"],
    // Pure modules run in node; components (.test.tsx) get a DOM and the shared Next mocks.
    projects: [
      { extends: true, test: { name: "unit", include: ["**/*.test.ts"], environment: "node" } },
      {
        extends: true,
        test: { name: "dom", include: ["**/*.test.tsx"], environment: "jsdom", setupFiles: ["./tests/setup.ts"] },
      },
    ],
    coverage: {
      provider: "v8",
      reporter: ["text-summary", "lcov"],
      // Every source file counts, tested or not, so the figure is honest.
      include: ["lib/**/*.{ts,tsx}", "features/**/*.{ts,tsx}", "components/**/*.{ts,tsx}"],
      exclude: ["**/*.test.{ts,tsx}", "**/__tests__/**", "**/*.d.ts"],
    },
  },
});
