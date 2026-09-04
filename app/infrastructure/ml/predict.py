"""Prediction DLL et persistance des resultats."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import joblib
import numpy as np
from sqlalchemy import select

from app.infrastructure.database import models
from app.infrastructure.database.database import SessionLocal
from app.domain.planning.gabarit_service import DUREE_CDC_CMDE
from app.infrastructure.ml.eda import duree_moyenne_historique
from app.infrastructure.ml.explain import expliquer_prediction_locale
from app.infrastructure.ml.similarity import construire_feature_row, construire_features
from app.infrastructure.ml.training import PIPELINE_PATH, entrainer_pipeline
from app.shared.enums import ConfidenceLevel
from app.shared.exceptions import RessourceIntrouvable


@dataclass(frozen=True)
class PredictionResult:
    id: int
    maquette_id: int
    predicted_duration: float
    predicted_dll: object
    confidence_level: ConfidenceLevel
    model_name: str
    model_version: str
    voisins: list[dict]
    explanation: dict


@dataclass(frozen=True)
class ResidualPredictionResult:
    maquette_id: int
    predicted_residual: float
    model_name: str
    model_version: str


def predire_dll(
    maquette,
    model_path: Path = PIPELINE_PATH,
    session_factory=SessionLocal,
) -> PredictionResult:
    if not model_path.exists():
        entrainer_pipeline(output_path=model_path, session_factory=session_factory)
    artifact = joblib.load(model_path)
    feature_row = _feature_row_prediction(maquette, artifact)
    raw_prediction = float(artifact["pipeline"].predict([feature_row])[0])
    prediction = _duration_from_model_output(raw_prediction, artifact)
    voisins = _voisins(feature_row, artifact["training_rows"])
    confidence = _confidence(voisins)
    explanation = expliquer_prediction_locale(feature_row, artifact, raw_prediction)
    feature_snapshot = construire_features(maquette)
    if artifact.get("use_history_feature"):
        feature_snapshot["duree_moyenne_historique"] = feature_row[4]

    with session_factory() as session:
        row = session.get(models.Maquette, maquette.id)
        if row is None:
            raise RessourceIntrouvable(f"Maquette introuvable: {maquette.id}")
        predicted_dll = row.date_creation + timedelta(
            days=DUREE_CDC_CMDE + round(prediction)
        )
        db_prediction = models.Prediction(
            maquette_id=row.id,
            predicted_duration=max(prediction, 1.0),
            predicted_dll=predicted_dll,
            confidence_level=confidence,
            model_name=artifact["model_name"],
            model_version=artifact["model_version"],
            input_snapshot={
                "features": feature_snapshot,
                "date_livraison_cdc_estimee": str(row.date_creation),
                "duree_cdc_cmde": DUREE_CDC_CMDE,
                "voisins": voisins,
                "mae": artifact.get("mae", {}),
                "explanation": explanation,
            },
        )
        session.add(db_prediction)
        session.commit()
        return PredictionResult(
            id=db_prediction.id,
            maquette_id=db_prediction.maquette_id,
            predicted_duration=db_prediction.predicted_duration,
            predicted_dll=db_prediction.predicted_dll,
            confidence_level=db_prediction.confidence_level,
            model_name=db_prediction.model_name,
            model_version=db_prediction.model_version,
            voisins=voisins,
            explanation=explanation,
        )


def predire_dll_par_maquette_id(
    maquette_id: int,
    model_path: Path = PIPELINE_PATH,
    session_factory=SessionLocal,
) -> PredictionResult:
    with session_factory() as session:
        maquette = session.get(models.Maquette, maquette_id)
        if maquette is None:
            raise RessourceIntrouvable(f"Maquette introuvable: {maquette_id}")
        detached = _DetachedMaquette(
            id=maquette.id,
            date_creation=maquette.date_creation,
            silhouette_id=maquette.silhouette_id,
            architecture_ee_id=maquette.architecture_ee_id,
            fournisseur_id=maquette.fournisseur_id,
            type_homologation=maquette.type_homologation,
        )
    return predire_dll(detached, model_path=model_path, session_factory=session_factory)


def predire_residu_dll_par_maquette_id(
    maquette_id: int,
    model_path: Path = PIPELINE_PATH,
    session_factory=SessionLocal,
) -> ResidualPredictionResult:
    with session_factory() as session:
        maquette = session.get(models.Maquette, maquette_id)
        if maquette is None:
            raise RessourceIntrouvable(f"Maquette introuvable: {maquette_id}")
        detached = _DetachedMaquette(
            id=maquette.id,
            date_creation=maquette.date_creation,
            silhouette_id=maquette.silhouette_id,
            architecture_ee_id=maquette.architecture_ee_id,
            fournisseur_id=maquette.fournisseur_id,
            type_homologation=maquette.type_homologation,
        )
    if not model_path.exists():
        entrainer_pipeline(output_path=model_path, session_factory=session_factory)
    artifact = joblib.load(model_path)
    feature_row = _feature_row_prediction(detached, artifact)
    raw_prediction = float(artifact["pipeline"].predict([feature_row])[0])
    if artifact.get("target_mode") in {"ecart_gabarit", "residu_buffer_deadline"}:
        residual = raw_prediction
    else:
        residual = raw_prediction - float(artifact.get("gabarit_duration_days", 231))
    return ResidualPredictionResult(
        maquette_id=maquette_id,
        predicted_residual=residual,
        model_name=artifact["model_name"],
        model_version=artifact["model_version"],
    )


@dataclass(frozen=True)
class _DetachedMaquette:
    id: int
    date_creation: object
    silhouette_id: int
    architecture_ee_id: int
    fournisseur_id: int
    type_homologation: object


def _voisins(feature_row: list, training_rows: list[dict], k: int = 3) -> list[dict]:
    distances = []
    for row in training_rows:
        distance = sum(
            0 if str(left) == str(right) else 1
            for left, right in zip(feature_row, row["features"])
        )
        distances.append((distance, row))
    return [
        {
            "reference": row["reference"],
            "modele": row["modele"],
            "silhouette": row["silhouette"],
            "duree_reelle": row["duree_reelle"],
            "residu_buffer_deadline": row.get("residu_buffer_deadline"),
            "distance": distance,
        }
        for distance, row in sorted(distances, key=lambda item: item[0])[:k]
    ]


def _feature_row_prediction(maquette, artifact: dict) -> list:
    feature_row = construire_feature_row(maquette)
    if not artifact.get("use_history_feature"):
        return feature_row
    moyenne = duree_moyenne_historique(
        maquette.silhouette_id,
        maquette.architecture_ee_id,
        [row["homologation"] for row in artifact["training_rows"]],
    )
    return [*feature_row, moyenne]


def _duration_from_model_output(raw_prediction: float, artifact: dict) -> float:
    if artifact.get("target_mode") in {"ecart_gabarit", "residu_buffer_deadline"}:
        return float(artifact.get("gabarit_duration_days", 231)) + raw_prediction
    return raw_prediction


def _confidence(voisins: list[dict]) -> ConfidenceLevel:
    if not voisins:
        return ConfidenceLevel.LOW
    targets = [
        item.get("residu_buffer_deadline")
        if item.get("residu_buffer_deadline") is not None
        else item["duree_reelle"]
        for item in voisins
    ]
    dispersion = float(np.std(targets))
    if dispersion <= 15:
        return ConfidenceLevel.HIGH
    if dispersion <= 45:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW
