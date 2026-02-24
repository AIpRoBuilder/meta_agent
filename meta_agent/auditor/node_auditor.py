from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Set

from auditor.data import RuleViolation
from auditor.base_auditor import BaseAuditor


class NodeAuditor(BaseAuditor):
    """Audit node classes for required methods without calling an LLM."""

    def __post_init__(self) -> None:  # pragma: no cover - deterministic setup
        # Skip the base class client bootstrapping; audits are local and deterministic.
        default_white_list = {"createGParam", "getGParam"}
        self.white_list: Set[str] = set(default_white_list)
        return

    def audit_node_file(self, file_path: str) -> tuple[bool, List[RuleViolation]]:
        """Audit a Python file and return whether it passes plus violations."""

        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"File not found: {path}")

        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:
            violation = RuleViolation(
                class_name="(file)",
                rule="syntax_error",
                detail=str(exc),
                lineno=exc.lineno or 0,
            )
            return False, [violation]

        violations: List[RuleViolation] = []
        class_defs = [node for node in tree.body if isinstance(node, ast.ClassDef)]
        if not class_defs:
            violations.append(
                RuleViolation(
                    class_name="(file)",
                    rule="class_missing",
                    detail="No classes found to audit.",
                    lineno=1,
                )
            )

        for cls in class_defs:
            self._check_clone(cls, violations)
            self._check_run(cls, violations)
            self._check_self_calls(cls, violations)

        return len(violations) == 0, violations

    def _check_clone(self, cls: ast.ClassDef, violations: List[RuleViolation]) -> None:
        if not self._is_registered_class(cls):
            return

        method = self._get_method(cls, "clone")
        if method is None:
            violations.append(
                RuleViolation(
                    class_name=cls.name,
                    rule="clone_missing",
                    detail="Missing def clone(self) that returns self.",
                    lineno=cls.lineno,
                )
            )
            return

        if len(method.args.args) != 1:
            violations.append(
                RuleViolation(
                    class_name=cls.name,
                    rule="clone_signature",
                    detail="clone must accept only self.",
                    lineno=method.lineno,
                )
            )

        returns_self = any(
            isinstance(node, ast.Return) and isinstance(node.value, ast.Name) and node.value.id == "self"
            for node in method.body
        )
        if not returns_self:
            violations.append(
                RuleViolation(
                    class_name=cls.name,
                    rule="clone_return",
                    detail="clone must return self.",
                    lineno=method.lineno,
                )
            )

    def _check_run(self, cls: ast.ClassDef, violations: List[RuleViolation]) -> None:
        if not self._is_registered_class(cls):
            return

        method = self._get_method(cls, "run")
        if method is None:
            violations.append(
                RuleViolation(
                    class_name=cls.name,
                    rule="run_missing",
                    detail="Missing def run(self) -> CStatus.",
                    lineno=cls.lineno,
                )
            )
            return

        if len(method.args.args) != 1:
            violations.append(
                RuleViolation(
                    class_name=cls.name,
                    rule="run_signature",
                    detail="run must accept only self.",
                    lineno=method.lineno,
                )
            )

        if not self._has_cstatus_annotation(method):
            violations.append(
                RuleViolation(
                    class_name=cls.name,
                    rule="run_annotation",
                    detail="run should be annotated to return CStatus.",
                    lineno=method.lineno,
                )
            )

    def _get_method(self, cls: ast.ClassDef, name: str) -> ast.FunctionDef | None:
        for node in cls.body:
            if isinstance(node, ast.FunctionDef) and node.name == name:
                return node
        return None

    def _has_cstatus_annotation(self, method: ast.FunctionDef) -> bool:
        annotation = method.returns
        if annotation is None:
            return False

        if isinstance(annotation, ast.Name) and annotation.id == "CStatus":
            return True
        if isinstance(annotation, ast.Attribute) and annotation.attr == "CStatus":
            return True
        return False

    def _is_registered_class(self, cls: ast.ClassDef) -> bool:
        for decorator in cls.decorator_list:
            target = decorator
            if isinstance(decorator, ast.Call):
                target = decorator.func

            if isinstance(target, ast.Name) and target.id == "register_class":
                return True
            if isinstance(target, ast.Attribute) and target.attr == "register_class":
                return True
        return False
