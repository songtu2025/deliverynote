import assert from "node:assert/strict";
import { afterEach, beforeEach, test } from "node:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { createCheckRepository } from "./frontend-check-support.mjs";

let repository;
const complexFunction =
  "export function example(value: number) { " +
  Array.from({ length: 10 }, (_, index) => `if (value === ${index}) return ${index};`).join(" ") +
  " return -1; }";
beforeEach(() => {
  repository = createCheckRepository("check-lint.mjs", "export const legacy: any = 1;\n");
});
afterEach(() => repository.dispose());

test("unchanged legacy errors are visible only in the requested full scan", () => {
  assert.equal(repository.check().status, 0);
  const result = repository.check("--all");
  assert.equal(result.status, 1, result.stdout + result.stderr);
  assert.match(result.stderr, /no-explicit-any/);
});

for (const [name, source, rule] of [
  ["类型", "export const quantity: any = 1;", "no-explicit-any"],
  [
    "Hook",
    'import { useState } from "react"; export function Example({ enabled }: { enabled: boolean }) { if (enabled) useState(0); return null; }',
    "rules-of-hooks"
  ],
  [
    "依赖",
    'import { useEffect } from "react"; export function Example({ value }: { value: number }) { useEffect(() => { console.log(value); }, []); return null; }',
    "exhaustive-deps"
  ],
  ["未使用变量", "const unused = 1; export const quantity = 1;", "no-unused-vars"],
  [
    "参数",
    "export function example(a: number, b: number, c: number, d: number, e: number, f: number) { return a+b+c+d+e+f; }",
    "max-params"
  ],
  ["复杂度", complexFunction, "complexity"]
]) {
  test(`incremental checks reject ${name} errors without rewriting Chinese paths`, () => {
    const file = `frontend/src/pages/batch-detail/新增 ${name}.tsx`;
    repository.write(file, source);
    const result = repository.check();
    assert.equal(result.status, 1, result.stdout + result.stderr);
    assert.match(result.stderr, new RegExp(rule));
    assert.equal(readFileSync(join(repository.root, file), "utf8"), source);
    repository.write(file, "export const quantity: number = 1;\n");
    const valid = repository.check();
    assert.equal(valid.status, 0, valid.stdout + valid.stderr);
  });
  if (["Hook", "依赖", "未使用变量"].includes(name)) {
    test(`full checks reject unchanged ${name} errors and accept their fix`, () => {
      repository.write("frontend/src/legacy.ts", source);
      repository.git("add", ".");
      repository.git("commit", "--quiet", "-m", "unchanged lint error");
      assert.equal(repository.check().status, 0);
      const result = repository.check("--all");
      assert.equal(result.status, 1, result.stdout + result.stderr);
      assert.match(result.stderr, new RegExp(rule));
      assert.equal(readFileSync(join(repository.root, "frontend/src/legacy.ts"), "utf8"), source);
      repository.write("frontend/src/legacy.ts", "export const quantity: number = 1;\n");
      const valid = repository.check("--all");
      assert.equal(valid.status, 0, valid.stdout + valid.stderr);
    });
  }
}

for (const path of [
  "App.tsx",
  "app/Workspace.tsx",
  "pages/AdminPage.tsx",
  "pages/admin/useAdminData.ts",
  "pages/admin/AdminInputWorkspace.tsx",
  "pages/admin/AdminPanelFallback.tsx"
]) {
  test(`entry complexity gate rejects ${path}`, () => {
    repository.write(`frontend/src/${path}`, complexFunction);
    const result = repository.check();
    assert.equal(result.status, 1, result.stdout + result.stderr);
    assert.match(result.stderr, /complexity/);
  });
}

for (const path of ["app/appTestSupport.ts", "pages/admin/adminPageTestSupport.tsx"]) {
  test(`${path} stays outside production complexity rules`, () => {
    repository.write(`frontend/src/${path}`, complexFunction);
    const result = repository.check();
    assert.equal(result.status, 0, result.stdout + result.stderr);
  });
}

test("CI ranges check all commits and reject invalid references", () => {
  const base = repository.git("rev-parse", "HEAD");
  repository.write("frontend/src/first.ts", "export const quantity: any = 1;\n");
  repository.git("add", ".");
  repository.git("commit", "--quiet", "-m", "first");
  repository.write("frontend/src/second.ts", "export const quantity: number = 2;\n");
  repository.git("add", ".");
  repository.git("commit", "--quiet", "-m", "second");
  const result = repository.check("--base", base);
  assert.equal(result.status, 1);
  assert.match(result.stderr, /first\.ts/);
  assert.notEqual(repository.check("--base", "missing-ref").status, 0);
});
