"""
Python AST Walker — Static code analysis using stdlib ast module.
No external dependencies.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import List, Optional

from utils.logger import get_logger

logger = get_logger("code_intel.ast_walker")


@dataclass
class WalkResult:
    """Result of AST analysis."""
    functions: List[str] = field(default_factory=list)
    classes: List[str] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    complexity: int = 0
    max_depth: int = 0
    success: bool = True
    error: Optional[str] = None


class PythonASTWalker(ast.NodeVisitor):
    """Walk Python AST and extract code structure."""

    def __init__(self):
        self.functions = []
        self.classes = []
        self.imports = []
        self.complexity = 0
        self.current_depth = 0
        self.max_depth = 0

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Optional[ast.FunctionDef]:
        """Visit function definition."""
        self.functions.append(node.name)
        self.generic_visit(node)
        return node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Optional[ast.AsyncFunctionDef]:
        """Visit async function definition."""
        self.functions.append(node.name)
        self.generic_visit(node)
        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> Optional[ast.ClassDef]:
        """Visit class definition."""
        self.classes.append(node.name)
        self.generic_visit(node)
        return node

    def visit_Import(self, node: ast.Import) -> Optional[ast.Import]:
        """Visit import statement."""
        for alias in node.names:
            self.imports.append(alias.name)
        return node

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Optional[ast.ImportFrom]:
        """Visit from...import statement."""
        module = node.module or ""
        for alias in node.names:
            self.imports.append(f"{module}.{alias.name}" if module else alias.name)
        return node

    def visit_If(self, node: ast.If) -> Optional[ast.If]:
        """Count if statements (complexity)."""
        self.complexity += 1
        self.generic_visit(node)
        return node

    def visit_For(self, node: ast.For) -> Optional[ast.For]:
        """Count for loops (complexity)."""
        self.complexity += 1
        self.generic_visit(node)
        return node

    def visit_While(self, node: ast.While) -> Optional[ast.While]:
        """Count while loops (complexity)."""
        self.complexity += 1
        self.generic_visit(node)
        return node

    def visit_Try(self, node: ast.Try) -> Optional[ast.Try]:
        """Count try blocks (complexity)."""
        self.complexity += 1
        self.generic_visit(node)
        return node

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> Optional[ast.ExceptHandler]:
        """Count except clauses (complexity)."""
        self.complexity += 1
        self.generic_visit(node)
        return node

    def visit_With(self, node: ast.With) -> Optional[ast.With]:
        """Count with statements (complexity)."""
        self.complexity += 1
        self.generic_visit(node)
        return node

    def visit(self, node: ast.AST) -> ast.AST:
        """Override visit to track depth."""
        self.current_depth += 1
        self.max_depth = max(self.max_depth, self.current_depth)
        result = super().visit(node)
        self.current_depth -= 1
        return result

    def walk(self, source: str) -> WalkResult:
        """
        Walk Python source code and extract structure.

        Args:
            source: Python source code string

        Returns:
            WalkResult with functions, classes, imports, complexity
        """
        self.functions = []
        self.classes = []
        self.imports = []
        self.complexity = 0
        self.max_depth = 0
        self.current_depth = 0

        try:
            tree = ast.parse(source)
            self.visit(tree)

            return WalkResult(
                functions=self.functions,
                classes=self.classes,
                imports=self.imports,
                complexity=self.complexity,
                max_depth=self.max_depth,
                success=True,
            )
        except SyntaxError as e:
            logger.error(f"Syntax error: {e}")
            return WalkResult(
                success=False,
                error=f"Syntax error: {e}",
            )
        except Exception as e:
            logger.error(f"AST walk failed: {e}")
            return WalkResult(
                success=False,
                error=f"Walk failed: {e}",
            )


def walk_python(source: str) -> WalkResult:
    """Convenience function to walk Python code."""
    walker = PythonASTWalker()
    return walker.walk(source)


__all__ = [
    "PythonASTWalker",
    "WalkResult",
    "walk_python",
]
