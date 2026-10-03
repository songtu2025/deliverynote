import { execFileSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";

export function frontendFiles(args) {
  const all = args.length === 1 && args[0] === "--all";
  const base = args.length === 2 && args[0] === "--base" ? args[1] : null;
  if (args.length && !all && !base) throw new Error("用法：[--all | --base <Git引用>]");
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
  return { root, all, files: [...new Set(files)].filter((file) => existsSync(join(root, file))) };
}
