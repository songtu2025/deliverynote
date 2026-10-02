import js from "@eslint/js";
import globals from "globals";

export default [
  {
    files: ["scripts/**/*.mjs", "eslint.config.js"],
    languageOptions: { globals: globals.node },
    rules: js.configs.recommended.rules
  }
];
