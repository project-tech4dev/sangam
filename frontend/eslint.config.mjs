import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    files: [
      "features/ask/AskWorkspace.tsx",
      "features/ask/views/VaultView.tsx",
      "features/ingest/components/RunStatus.tsx",
    ],
    rules: { "react-hooks/set-state-in-effect": "warn" },
  },
  {
    files: ["features/ask/components/ChatPane.tsx"],
    rules: { "react-hooks/purity": "warn" },
  },
  {
    files: [
      "features/ask/lib/toolLabels.ts",
      "features/ingest/lib/toolLabels.ts",
      "features/ingest/components/RunStatus.tsx",
      "features/ingest/components/SubagentBoard.tsx",
    ],
    rules: { "@typescript-eslint/no-explicit-any": "warn" },
  },
  globalIgnores([".next/**", "out/**", "build/**", "next-env.d.ts"]),
]);
