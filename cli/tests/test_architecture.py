import ast
import unittest
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parents[1] / "devsecops_cli"


def package_dependencies(path: Path) -> set[str]:
    """Return package-local modules imported by a source file."""

    dependencies: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level and node.module:
                dependencies.add(node.module.split(".", 1)[0])
            elif node.level:
                dependencies.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif node.module and node.module.startswith("devsecops_cli."):
                dependencies.add(node.module.split(".", 2)[1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("devsecops_cli."):
                    dependencies.add(alias.name.split(".", 2)[1])
    return dependencies


class CliArchitectureTests(unittest.TestCase):
    def test_only_entry_point_imports_main(self) -> None:
        offenders = []
        for path in PACKAGE_DIR.glob("*.py"):
            if path.stem in {"__main__", "main"}:
                continue
            if "main" in package_dependencies(path):
                offenders.append(path.name)

        self.assertEqual(offenders, [], f"Modules must not depend on main.py: {offenders}")

    def test_internal_module_graph_has_no_cycles(self) -> None:
        modules = {path.stem for path in PACKAGE_DIR.glob("*.py") if path.stem != "__main__"}
        graph = {
            path.stem: package_dependencies(path) & modules
            for path in PACKAGE_DIR.glob("*.py")
            if path.stem in modules
        }

        remaining = {module: set(dependencies) for module, dependencies in graph.items()}
        while remaining:
            ready = {module for module, dependencies in remaining.items() if not dependencies}
            self.assertTrue(ready, f"Circular CLI module dependencies: {remaining}")
            remaining = {
                module: dependencies - ready
                for module, dependencies in remaining.items()
                if module not in ready
            }


if __name__ == "__main__":
    unittest.main()
