import { readFileSync, readdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { parseSync } from "oxc-parser";
import { ResolverFactory } from "oxc-resolver";

export function importGraph(files, configPath) {
  const graph = new Map(files.map((file) => [resolve(file), new Set()]));
  const resolver = new ResolverFactory({
    extensions: [".ts", ".tsx", ".js", ".jsx"],
    ...(configPath ? { tsconfig: { configFile: configPath } } : {})
  });
  for (const file of graph.keys()) {
    const source = parseSync(file, readFileSync(file, "utf8"));
    if (source.errors.length) throw new Error(`无法解析 ${file}：${source.errors[0].message}`);
    for (const statement of source.program.body) {
      if (!statement.source || typeof statement.source.value !== "string") continue;
      if (statement.importKind === "type" || statement.exportKind === "type") continue;
      if (
        statement.specifiers?.length &&
        statement.specifiers.every((item) => item.importKind === "type" || item.exportKind === "type")
      )
        continue;
      const target = resolver.sync(dirname(file), statement.source.value).path;
      if (target && graph.has(resolve(target))) graph.get(file).add(resolve(target));
    }
  }
  return graph;
}

export function findCycles(graph) {
  const active = [];
  const visited = new Set();
  const cycles = [];
  function visit(file) {
    const index = active.indexOf(file);
    if (index >= 0) {
      cycles.push([...active.slice(index), file]);
      return;
    }
    if (visited.has(file)) return;
    active.push(file);
    for (const target of graph.get(file)) visit(target);
    active.pop();
    visited.add(file);
  }
  for (const file of graph.keys()) visit(file);
  return cycles;
}

function main() {
  const configPath = resolve("tsconfig.app.json");
  const files = readdirSync("src", { recursive: true })
    .filter((file) => /\.(ts|tsx)$/.test(file))
    .map((file) => resolve("src", file));
  const cycles = findCycles(importGraph(files, configPath));
  for (const cycle of cycles) console.error(`前端导入循环：${cycle.join(" -> ")}`);
  console.log(`前端静态导入检查：${files.length} 个文件，${cycles.length} 个循环。`);
  if (cycles.length) process.exitCode = 1;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main();
}
