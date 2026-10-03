import { readFileSync } from "node:fs";
import { extname, join } from "node:path";
import * as prettier from "prettier";
import { frontendFiles } from "./frontend-files.mjs";

const extensions = new Set([".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".css", ".json", ".html"]);

async function main() {
  const { root, all, files: candidates } = frontendFiles(process.argv.slice(2));
  // 增量模式检查当前工作区；提交范围模式检查 CI 检出的版本。
  const files = candidates.filter((file) => extensions.has(extname(file)) && file !== "frontend/package-lock.json");
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
