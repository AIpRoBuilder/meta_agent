"""Utilities for working with node graphs defined in JSON."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, MutableMapping


def _load_graph_json(source: Any) -> MutableMapping[str, Any]:
    """Load a graph JSON object from a mapping, JSON string, or file path."""

    if isinstance(source, Mapping):
        return dict(source)

    if isinstance(source, (str, Path)):
        path = Path(str(source))
        if path.exists():
            return json.loads(path.read_text())
        try:
            return json.loads(str(source))
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise ValueError("Invalid JSON string provided") from exc

    raise TypeError("source must be a mapping, JSON string, or path-like object")


def graph_to_nodes(graph_json: Any) -> Dict[str, Dict[str, Any]]:
    """
    Convert a graph JSON structure into a node lookup map.

    The input can be a Python mapping, a JSON string, or a file path pointing to
    a JSON document with a top-level ``nodes`` list. Each entry in the returned
    dict uses the node name as the key and stores its ``type``, ``desc``, and
    ``depends`` fields.
    """

    graph_obj = _load_graph_json(graph_json)
    nodes = graph_obj.get("nodes", [])

    result: Dict[str, Dict[str, Any]] = {}
    for node in nodes:
        if not isinstance(node, Mapping):
            continue

        name = node.get("name")
        if not name:
            continue

        depends = node.get("depends", [])
        if isinstance(depends, (str, bytes)):
            depends = [depends]
        elif not isinstance(depends, list):
            depends = list(depends) if depends is not None else []

        result[name] = {
            "type": node.get("type", ""),
            "desc": node.get("desc", ""),
            "depends": depends,
        }

    return result


__all__ = ["graph_to_nodes"]
