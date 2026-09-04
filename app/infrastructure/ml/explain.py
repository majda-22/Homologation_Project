"""Explications locales des predictions DLL.

L'approche est volontairement model-agnostic, proche de l'esprit LIME :
on mesure localement l'effet d'une variable en la remplaçant par une valeur
historique de reference, puis en comparant la prediction obtenue.
"""

from __future__ import annotations

from collections import Counter
from statistics import median
from typing import Any


def expliquer_prediction_locale(feature_row: list, artifact: dict, raw_prediction: float) -> dict:
    """Retourne une explication locale exploitable dans l'UI et l'audit."""

    pipeline = artifact["pipeline"]
    feature_names = artifact.get("feature_names") or [f"feature_{index}" for index in range(len(feature_row))]
    training_rows = artifact.get("training_rows", [])
    references = _valeurs_reference(training_rows, len(feature_row))
    contributions = []

    for index, feature_name in enumerate(feature_names):
        reference_value = references[index] if index < len(references) else None
        perturbed = list(feature_row)
        perturbed[index] = reference_value
        perturbed_prediction = float(pipeline.predict([perturbed])[0])
        impact = raw_prediction - perturbed_prediction
        contributions.append(
            {
                "feature": feature_name,
                "valeur": feature_row[index] if index < len(feature_row) else None,
                "reference": reference_value,
                "impact_jours": round(impact, 2),
                "sens": _sens_impact(impact),
            }
        )

    contributions.sort(key=lambda item: abs(item["impact_jours"]), reverse=True)
    return {
        "method": "LIME-like local perturbation",
        "model_name": artifact.get("model_name", ""),
        "target": artifact.get("target_mode", "duree_reelle"),
        "base_prediction_modele": round(raw_prediction, 2),
        "contributions": contributions,
        "note": (
            "Chaque impact compare la prediction actuelle a une prediction ou une seule "
            "variable est remplacee par sa valeur historique de reference."
        ),
    }


def _valeurs_reference(training_rows: list[dict], feature_count: int) -> list[Any]:
    references = []
    for index in range(feature_count):
        values = [
            row["features"][index]
            for row in training_rows
            if len(row.get("features", [])) > index and row["features"][index] is not None
        ]
        references.append(_reference_value(values))
    return references


def _reference_value(values: list[Any]) -> Any:
    if not values:
        return None
    if all(isinstance(value, (int, float)) for value in values):
        return median(values)
    return Counter(str(value) for value in values).most_common(1)[0][0]


def _sens_impact(impact: float) -> str:
    if impact > 0:
        return "augmente la DLL"
    if impact < 0:
        return "reduit la DLL"
    return "impact neutre"
