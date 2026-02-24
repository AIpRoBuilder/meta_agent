from __future__ import annotations

import ast
from pathlib import Path
from typing import List

from auditor.data import RuleViolation


class MainEntryPointAuditor:
	"""Audit main entrypoint files for required imports."""

	def audit_main_entrypoint_file(self, file_path: str) -> tuple[bool, List[RuleViolation]]:
		"""Check required imports and forbid certain globals/functions."""

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

		if not self._has_import(tree, "fastapi"):
			violations.append(
				RuleViolation(
					class_name="(file)",
					rule="fastapi_import_missing",
					detail="Missing import for fastapi (e.g., 'from fastapi import FastAPI').",
					lineno=1,
				)
			)

		if not self._has_import(tree, "uvicorn"):
			violations.append(
				RuleViolation(
					class_name="(file)",
					rule="uvicorn_import_missing",
					detail="Missing import for uvicorn (e.g., 'import uvicorn').",
					lineno=1,
				)
			)

		file_stem = path.stem
		target_value, target_lineno = self._find_uvicorn_run_target(tree)
		if target_value is not None and file_stem not in target_value:
			violations.append(
				RuleViolation(
					class_name="(file)",
					rule="uvicorn_run_target_mismatch",
					detail=(
						"uvicorn.run should reference the file's module name "
						f"(expected to include '{file_stem}', e.g., '{file_stem}:app'). "
						f"Found '{target_value}'."
					),
					lineno=target_lineno or 1,
				)
			)

		nodes_root = self._find_global(tree, "NODES_ROOT")
		if nodes_root is not None:
			violations.append(
				RuleViolation(
					class_name="(file)",
					rule="nodes_root_forbidden",
					detail="NODES_ROOT global should not be defined in main entrypoint.",
					lineno=nodes_root,
				)
			)

		import_node_modules_lineno = self._find_function(tree, "import_node_modules")
		if import_node_modules_lineno is not None:
			violations.append(
				RuleViolation(
					class_name="(file)",
					rule="import_node_modules_forbidden",
					detail="import_node_modules function should not exist in main entrypoint.",
					lineno=import_node_modules_lineno,
				)
			)

		return len(violations) == 0, violations

	def _has_import(self, tree: ast.AST, module_name: str) -> bool:
		"""Return True if the module is imported via ``import`` or ``from``."""

		for node in tree.body:
			if isinstance(node, ast.Import):
				for alias in node.names:
					if alias.name.split(".")[0] == module_name:
						return True
			if isinstance(node, ast.ImportFrom):
				if node.module and node.module.split(".")[0] == module_name:
					return True
		return False

	def _find_global(self, tree: ast.AST, name: str) -> int | None:
		"""Return the line number if a global name is defined, otherwise None."""

		for node in tree.body:
			if isinstance(node, ast.Assign):
				for target in node.targets:
					if isinstance(target, ast.Name) and target.id == name:
						return node.lineno
			if isinstance(node, ast.AnnAssign):
				target = node.target
				if isinstance(target, ast.Name) and target.id == name:
					return node.lineno
		return None

	def _find_function(self, tree: ast.AST, name: str) -> int | None:
		"""Return the line number of a top-level function name if present."""

		for node in tree.body:
			if isinstance(node, ast.FunctionDef) and node.name == name:
				return node.lineno
		return None

	def _find_uvicorn_run_target(self, tree: ast.AST) -> tuple[str | None, int | None]:
		"""Return the uvicorn.run target literal and its line number if present."""

		for node in ast.walk(tree):
			if not isinstance(node, ast.Call):
				continue

			func = node.func
			if not (isinstance(func, ast.Attribute) and func.attr == "run"):
				continue

			if not (isinstance(func.value, ast.Name) and func.value.id == "uvicorn"):
				continue

			if node.args:
				first_arg = node.args[0]
				if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
					return first_arg.value, first_arg.lineno

			for keyword in node.keywords:
				if keyword.arg == "app" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
					return keyword.value.value, keyword.value.lineno

		return None, None

