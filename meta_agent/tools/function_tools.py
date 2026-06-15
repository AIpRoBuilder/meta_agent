from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Any, Callable


def _run_stage(stage_name: str, target_path: Path, writer: Callable[..., Any], **kwargs: Any) -> Any:
	"""Run a named write stage and print detailed failure context before re-raising."""
	print(f"start writing {stage_name} to: {target_path}")
	try:
		return writer(**kwargs)
	except Exception as exc:
		print(
			f"failed writing {stage_name} to {target_path}: "
			f"{exc.__class__.__name__}: {exc}",
			file=sys.stderr,
		)
		traceback.print_exc()
		raise
