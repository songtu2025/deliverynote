import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { afterEach, beforeEach, test } from "node:test";
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const frontend = fileURLToPath(new URL("../../", import.meta.url));
const script = join(frontend, "scripts/check-format.mjs");
let root;

function git(...args) {
  return execFileSync("git", args, { cwd: root, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();
}

function write(relativePath, content) {
  const path = join(root, relativePath);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, content);
}

function check(...args) {
  return spawnSync(process.execPath, [script, ...args], { cwd: join(root, "frontend"), encoding: "utf8" });
}

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), "deliverynote format "));
  git("init", "--quiet");
  git("config", "user.name", "Format Check");
  git("config", "user.email", "format-check@example.invalid");
  git("config", "core.autocrlf", "false");
  write("frontend/src/legacy.ts", "export const legacy=1\n");
  copyFileSync(join(frontend, ".prettierrc.json"), join(root, "frontend/.prettierrc.json"));
  git("add", ".");
  git("commit", "--quiet", "-m", "fixture");
});

afterEach(() => {
  // 只清理本测试通过 mkdtemp 创建的独立合成仓库。
  rmSync(root, { recursive: true, force: true });
});

test("unchanged legacy files do not block incremental checks but appear in a full scan", () => {
  assert.equal(check().status, 0);
  const result = check("--all");
  assert.equal(result.status, 1);
  assert.match(result.stderr, /legacy\.ts/);
});

test("untracked files with Chinese names are checked without rewriting them", () => {
  const file = "frontend/src/新增 文件.ts";
  const source = "export const added=1\n";
  write(file, source);
  const result = check();
  assert.equal(result.status, 1);
  assert.match(result.stderr, /新增 文件\.ts/);
  assert.equal(readFileSync(join(root, file), "utf8"), source);
  write(file, "export const added = 1;\n");
  assert.equal(check().status, 0);
});

test("both staged and unstaged edits are checked", () => {
  write("frontend/src/staged.ts", "export const staged=1\n");
  git("add", "frontend/src/staged.ts");
  write("frontend/src/legacy.ts", "export const legacy=2\n");
  const result = check();
  assert.equal(result.status, 1);
  assert.match(result.stderr, /staged\.ts/);
  assert.match(result.stderr, /legacy\.ts/);
});

test("CI ranges include every commit and exclude unrelated untracked files", () => {
  const base = git("rev-parse", "HEAD");
  write("frontend/src/first.ts", "export const first=1\n");
  git("add", ".");
  git("commit", "--quiet", "-m", "first");
  write("frontend/src/second.ts", "export const second = 2;\n");
  git("add", ".");
  git("commit", "--quiet", "-m", "second");
  write("frontend/src/untracked.ts", "export const untracked=3\n");
  const result = check("--base", base);
  assert.equal(result.status, 1);
  assert.match(result.stderr, /first\.ts/);
  assert.doesNotMatch(result.stderr, /untracked\.ts/);
});

test("deleted files, lockfiles and files outside frontend are not checked", () => {
  git("rm", "frontend/src/legacy.ts");
  write("frontend/package-lock.json", '{"lockfileVersion":3}');
  write("scripts/example.js", "const value=1\n");
  assert.equal(check().status, 0);
});

test("invalid Git bases and invalid arguments fail instead of silently skipping checks", () => {
  assert.notEqual(check("--base", "missing-ref").status, 0);
  assert.notEqual(check("--unknown").status, 0);
});
