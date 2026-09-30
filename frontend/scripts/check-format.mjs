import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { extname, join } from "node:path";
import * as prettier from "prettier";

const extensions = new Set([".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".css", ".json", ".html"]);

async function main() {
  const args = process.argv.slice(2);
  const all = args.length === 1 && args[0] === "--all";
  const base = args.length === 2 && args[0] === "--base" ? args[1] : null;
  if (args.length && !all && !base) throw new Error("用法：check-format.mjs [--all | --base <Git引用>]");

  const root = execFileSync("git", ["rev-parse", "--show-toplevel"], { encoding: "utf8" }).trim();
  const git = (...parameters) => execFileSync("git", parameters, { cwd: root, encoding: "utf8" });
  const list = (output) => output.split("\0").filter(Boolean);
  let files;
  if (all) {
    files = list(git("ls-files", "-z", "--", "frontend"));
  } else {
    const reference = git("rev-parse", "--verify", "--end-of-options", `${base ?? "HEAD"}^{commit}`).trim();
    files = list(
      git("diff", "--name-only", "--diff-filter=ACMR", "-z", reference, ...(base ? ["HEAD"] : []), "--", "frontend")
    );
  }
  if (!base) files.push(...list(git("ls-files", "--others", "--exclude-standard", "-z", "--", "frontend")));

  // 增量模式检查当前工作区；提交范围模式检查 CI 检出的版本。
  files = [...new Set(files)].filter(
    (file) => extensions.has(extname(file)) && file !== "frontend/package-lock.json" && existsSync(join(root, file))
  );
  let failed = 0;
  for (const file of files) {
    const path = join(root, file);
    const config = await prettier.resolveConfig(path);
    if (!(await prettier.check(readFileSync(path, "utf8"), { ...config, filepath: path }))) {
      console.error(`格式不符合要求：${file}`);
      failed += 1;
    }
  }
  console.log(`格式检查：${files.length} 个文件，${failed} 个失败（${all ? "全量" : "增量"}）。`);
  if (failed) process.exitCode = 1;
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
