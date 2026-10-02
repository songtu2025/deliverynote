"""检查 Python 包内静态可解析的运行时导入循环。"""

import ast
from pathlib import Path


def _runtime_imports(node: ast.AST) -> list[ast.Import | ast.ImportFrom]:
    imports: list[ast.Import | ast.ImportFrom] = []
    if isinstance(node, ast.If) and (
        isinstance(node.test, ast.Name)
        and node.test.id == "TYPE_CHECKING"
        or isinstance(node.test, ast.Attribute)
        and node.test.attr == "TYPE_CHECKING"
    ):
        for statement in node.orelse:
            imports.extend(_runtime_imports(statement))
        return imports
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        imports.append(node)
    for child in ast.iter_child_nodes(node):
        imports.extend(_runtime_imports(child))
    return imports


def _dependencies(path: Path, name: str) -> set[str]:
    package = name if path.name == "__init__.py" else name.rpartition(".")[0]
    imports = _runtime_imports(ast.parse(path.read_text(encoding="utf-8-sig")))
    targets: set[str] = set()
    for node in imports:
        if isinstance(node, ast.Import):
            targets.update(item.name for item in node.names)
            continue
        base = node.module or ""
        if node.level:
            parts = package.split(".")
            base = ".".join(
                parts[: len(parts) - node.level + 1] + ([base] if base else [])
            )
        targets.add(base)
        targets.update(f"{base}.{item.name}" for item in node.names)
    return targets


def import_cycles(package_root: Path) -> list[list[str]]:
    modules: dict[str, Path] = {}
    for path in package_root.rglob("*.py"):
        parts = list(path.relative_to(package_root.parent).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        modules[".".join(parts)] = path
    graph = {
        name: _dependencies(path, name).intersection(modules) - {name}
        for name, path in modules.items()
    }
    active: list[str] = []
    visited: set[str] = set()
    cycles: list[list[str]] = []

    def visit(name: str) -> None:
        if name in active:
            cycles.append(active[active.index(name) :] + [name])
            return
        if name in visited:
            return
        active.append(name)
        for target in sorted(graph[name]):
            visit(target)
        active.pop()
        visited.add(name)

    for name in sorted(modules):
        visit(name)
    return cycles
