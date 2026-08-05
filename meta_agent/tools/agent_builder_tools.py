from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Dict


def get_reference_frontend_src_dir() -> str:
    return str((Path(__file__).resolve().parent.parent / "library" / "frontend_reference" / "src").resolve())


def get_language_extension(language: str) -> str:
    language_clean = language.strip().lower() if language else "python"
    if language_clean in {"python", "py"}:
        return ".py"
    if language_clean in {"javascript", "js"}:
        return ".js"
    if language_clean in {"typescript", "ts"}:
        return ".ts"
    return f".{language_clean}"


def build_frontend_node_paths(frontend_src_dir: str | Path, node_name: str) -> Dict[str, Path]:
    base_dir = Path(frontend_src_dir).expanduser().resolve()
    return {
        "view": base_dir / "views" / f"{node_name}.vue",
        "style": base_dir / "styles" / f"{node_name}.css",
    }


def build_frontend_src_file_map(frontend_src_dir: str | Path) -> Dict[str, Path]:
    base_dir = Path(frontend_src_dir).expanduser().resolve()
    return {
        "api": base_dir / "api" / "workflow.js",
        "store": base_dir / "store" / "workflow.js",
        "app_shell": base_dir / "components" / "AppShell.vue",
        "app": base_dir / "App.vue",
        "app_css": base_dir / "styles" / "app.css",
    }


def select_python_command() -> str:
    for candidate in ("python3.10", "python3", "python"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return "python"


def create_minimal_vue_frontend_scaffold(frontend_dir: Path) -> None:
    frontend_dir.mkdir(parents=True, exist_ok=True)
    (frontend_dir / "src").mkdir(parents=True, exist_ok=True)

    package_json_path = frontend_dir / "package.json"
    if package_json_path.exists():
        return

    package_json = {
        "name": frontend_dir.name,
        "version": "0.0.0",
        "private": True,
        "scripts": {
            "start": "npm run serve",
            "serve": "vue-cli-service serve",
            "lint": "echo 'lint not configured for minimal scaffold'",
        },
    }
    package_json_path.write_text(
        json.dumps(package_json, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
