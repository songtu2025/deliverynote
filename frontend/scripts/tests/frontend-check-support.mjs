import { execFileSync, spawnSync } from "node:child_process";
import { copyFileSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const frontend = fileURLToPath(new URL("../../", import.meta.url));

export function createCheckRepository(scriptName, legacy) {
  const root = mkdtempSync(join(tmpdir(), "deliverynote checks "));
  const git = (...args) =>
    execFileSync("git", args, { cwd: root, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();
  const write = (relativePath, content) => {
    const path = join(root, relativePath);
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, content);
  };
  git("init", "--quiet");
  git("config", "user.name", "Frontend Check");
  git("config", "user.email", "frontend-check@example.invalid");
  git("config", "core.autocrlf", "false");
  write("frontend/src/legacy.ts", legacy);
  copyFileSync(join(frontend, ".prettierrc.json"), join(root, "frontend/.prettierrc.json"));
  git("add", ".");
  git("commit", "--quiet", "-m", "fixture");
  return {
    root,
    git,
    write,
    check: (...args) =>
      spawnSync(process.execPath, [join(frontend, "scripts", scriptName), ...args], {
        cwd: join(root, "frontend"),
        encoding: "utf8"
      }),
    // 仅删除 mkdtemp 创建的独立合成仓库。
    dispose: () => rmSync(root, { recursive: true, force: true })
  };
}
