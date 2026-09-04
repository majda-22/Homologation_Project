"""Historique leger des runs d'entrainement ML."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config.settings import settings

RUN_HISTORY_PATH = settings.ml_models_dir / "run_history.jsonl"


def append_run_history(
    model_name: str,
    mae: dict[str, float],
    n_rows: int,
    feature_set: list[str],
    pipeline: str = "dll",
    path: Path = RUN_HISTORY_PATH,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings.ensure_directories()
    row: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model_name": model_name,
        "mae": mae,
        "n_rows": int(n_rows),
        "feature_set": feature_set,
        "pipeline": pipeline,
    }
    if extra:
        row.update(extra)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
    return row


def read_run_history(path: Path = RUN_HISTORY_PATH, limit: int | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if text:
                rows.append(_normalize_run(json.loads(text)))
    rows.reverse()
    return rows if limit is None else rows[:limit]


def _normalize_run(row: dict[str, Any]) -> dict[str, Any]:
    row.setdefault("pipeline", "dll")
    row.setdefault("simulated", False)
    row.setdefault("feature_set", [])
    row.setdefault("mae", {})
    row["type"] = "SIMULE" if row.get("simulated") else "REEL"
    row["is_low_volume"] = row.get("type") == "REEL" and int(row.get("n_rows") or 0) < 5
    return row
