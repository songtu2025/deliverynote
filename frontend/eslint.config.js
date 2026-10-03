import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";

export default [
  { ignores: ["dist/**", "node_modules/**"] },
  ...tseslint.configs.recommended.map((config) => ({ ...config, files: ["**/src/**/*.{ts,tsx}"] })),
  {
    files: ["**/src/**/*.{ts,tsx}"],
    languageOptions: { globals: { ...globals.browser, ...globals.es2022 } },
    plugins: { "react-hooks": reactHooks },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "error"
    }
  },
  {
    files: ["**/src/pages/batch-detail/**/*.{ts,tsx}", "**/src/batchDetailApi.ts", "**/src/pages/BatchDetail.tsx"],
    rules: {
      complexity: ["error", 10],
      "max-depth": ["error", 5],
      "max-params": ["error", 5],
      "max-statements": ["error", 50]
    }
  },
  {
    files: ["scripts/**/*.mjs", "eslint.config.js"],
    languageOptions: { globals: globals.node },
    rules: js.configs.recommended.rules
  }
];
