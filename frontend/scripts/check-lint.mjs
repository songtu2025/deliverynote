import { ESLint } from "eslint";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { frontendFiles } from "./frontend-files.mjs";

async function main() {
  const { root, all, files } = frontendFiles(process.argv.slice(2));
  const sources = files.filter((file) => /^frontend\/src\/.*\.(ts|tsx)$/.test(file));
  const eslint = new ESLint({
    cwd: root,
    overrideConfigFile: fileURLToPath(new URL("../eslint.config.js", import.meta.url))
  });
  // 增量门禁检查完整文件，警告也视为失败，避免漏掉受影响的副作用。
  if (!sources.length) {
    console.log("前端 ESLint：0 个业务文件（工程脚本由 lint:tools 检查）。");
    return;
  }
  const results = await eslint.lintFiles(sources.map((file) => join(root, file)));
  const formatter = await eslint.loadFormatter("stylish");
  const output = formatter.format(results);
  if (output) console.error(output);
  const errors = results.reduce((sum, result) => sum + result.errorCount + result.warningCount, 0);
  console.log(`前端 ESLint：${sources.length} 个文件，${errors} 个问题（${all ? "全量" : "增量"}）。`);
  if (errors) process.exitCode = 1;
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
