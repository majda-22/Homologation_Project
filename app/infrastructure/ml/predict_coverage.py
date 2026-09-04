"""Prediction ML de couverture homologation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import joblib
import pandas as pd

from app.infrastructure.ml.coverage_training import (
    COVERAGE_PIPELINE_PATH,
    FEATURE_COLUMNS,
    entrainer_couverture,
)
from app.infrastructure.ml.similarity import construire_features


@dataclass(frozen=True)
class ResultatCouverture:
    est_couverte: bool
    confiance: str
    model_name: str
    model_version: str
    metrics: dict[str, dict[str, float]]
    circularite_detectee: bool
    conclusion: str


def predire_couverture(
    maquette,
    model_path: Path = COVERAGE_PIPELINE_PATH,
    session_factory=None,
) -> ResultatCouverture:
    if not model_path.exists():
        if session_factory is None:
            entrainer_couverture(output_path=model_path)
        else:
            entrainer_couverture(output_path=model_path, session_factory=session_factory)
    artifact = joblib.load(model_path)
    features = construire_features(maquette)
    row = pd.DataFrame([{column: features[column] for column in FEATURE_COLUMNS}])
    prediction = int(artifact["pipeline"].predict(row)[0])
    accuracy = artifact.get("metrics", {}).get(artifact["model_name"], {}).get("accuracy", 0.0)
    return ResultatCouverture(
        est_couverte=bool(prediction),
        confiance=_confidence_from_accuracy(float(accuracy)),
        model_name=artifact["model_name"],
        model_version=artifact["model_version"],
        metrics=artifact.get("metrics", {}),
        circularite_detectee=bool(artifact.get("circularite_detectee", False)),
        conclusion=artifact.get("conclusion", ""),
    )


def _confidence_from_accuracy(accuracy: float) -> str:
    if accuracy >= 0.85:
        return "Haute"
    if accuracy >= 0.65:
        return "Moyenne"
    return "Basse"
