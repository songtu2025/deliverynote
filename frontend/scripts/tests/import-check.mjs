import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, test } from "node:test";

import { findCycles, importGraph } from "../check-imports.mjs";

let root;
beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), "deliverynote imports "));
});
afterEach(() => {
  // 只清理本测试创建的临时模块。
  rmSync(root, { recursive: true, force: true });
});

function cycles(first, second) {
  const files = [join(root, "first.ts"), join(root, "second.ts")];
  writeFileSync(files[0], first);
  writeFileSync(files[1], second);
  return findCycles(importGraph(files));
}

test("runtime imports and re-exports expose the cycle", () => {
  const result = cycles('export { value } from "./second";', 'import "./first"; export const value = 1;');
  assert.equal(result.length, 1);
  assert.equal(result[0][0], result[0].at(-1));
});

for (const statement of [
  'import type { Value } from "./first";',
  'import { type Value } from "./first";',
  'export type { Value } from "./first";'
]) {
  test(`type-only references do not form runtime cycles: ${statement}`, () => {
    assert.deepEqual(cycles('import "./second"; export type Value = string;', statement), []);
  });
}

test("a mixed type and value import remains a runtime dependency", () => {
  assert.equal(
    cycles(
      'import "./second"; export type Value = string; export const value = 1;',
      'import { type Value, value } from "./first";'
    ).length,
    1
  );
});

test("configured path aliases participate in cycle checks", () => {
  const files = [join(root, "first.ts"), join(root, "second.ts")];
  writeFileSync(files[0], 'import "@local/second";');
  writeFileSync(files[1], 'import "./first";');
  const config = join(root, "tsconfig.json");
  writeFileSync(config, JSON.stringify({ compilerOptions: { paths: { "@local/*": [`${root}/*`] } } }));
  const graph = importGraph(files, config);
  assert.equal(findCycles(graph).length, 1);
});
