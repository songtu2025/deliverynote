import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { afterEach, beforeEach, test } from "node:test";
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { delimiter, join } from "node:path";
import { fileURLToPath } from "node:url";

const frontend = fileURLToPath(new URL("../../", import.meta.url));
const command = JSON.parse(readFileSync(join(frontend, "package.json"), "utf8")).scripts.typecheck;
let root;

function check() {
  return spawnSync(command, {
    cwd: root,
    shell: true,
    encoding: "utf8",
    env: { ...process.env, PATH: `${join(frontend, "node_modules/.bin")}${delimiter}${process.env.PATH}` }
  });
}

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), "deliverynote types "));
  mkdirSync(join(root, "src"));
  for (const name of ["app", "node"]) {
    const config = JSON.parse(readFileSync(join(frontend, `tsconfig.${name}.json`), "utf8"));
    config.compilerOptions.types = [];
    writeFileSync(join(root, `tsconfig.${name}.json`), JSON.stringify(config));
  }
  writeFileSync(join(root, "src/example.ts"), "export const quantity: number = 1;\n");
  writeFileSync(join(root, "vite.config.ts"), "export const port: number = 5173;\n");
});

afterEach(() => {
  // 只清理本测试创建的合成 TypeScript 项目。
  rmSync(root, { recursive: true, force: true });
});

test("the package typecheck command succeeds without generating or changing files", () => {
  const before = readdirSync(root, { recursive: true }).sort();
  const result = check();
  assert.equal(result.status, 0, result.stdout + result.stderr);
  assert.deepEqual(readdirSync(root, { recursive: true }).sort(), before);
  assert.equal(readFileSync(join(root, "src/example.ts"), "utf8"), "export const quantity: number = 1;\n");
});

for (const file of ["src/example.ts", "vite.config.ts"]) {
  test(`the package typecheck command rejects a type error in ${file}`, () => {
    writeFileSync(join(root, file), 'export const quantity: number = "invalid";\n');
    const result = check();
    assert.notEqual(result.status, 0);
    assert.match(result.stdout + result.stderr, /TS2322/);
  });
}
