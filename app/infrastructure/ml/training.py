"""Entrainement du modele de prediction DLL."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import LeaveOneOut
from sklearn.neighbors import KNeighborsRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from app.config.settings import BASE_DIR, settings
from app.infrastructure.database import models
from app.infrastructure.database.database import SessionLocal
from app.infrastructure.ml.run_history import RUN_HISTORY_PATH, append_run_history
from app.infrastructure.ml.similarity import construire_feature_row, construire_features
from app.shared.enums import TypeHomologation

RAW_PROJECTS_PATH = BASE_DIR / "data" / "raw" / "projects" / "Suivi_Homologation_R116.xlsx"
PIPELINE_PATH = settings.ml_models_dir / "deadline_pipeline.joblib"
GABARIT_DURATION_DAYS = 231


@dataclass(frozen=True)
class TrainingReport:
    lignes_raw: int
    lignes_utilisables: int
    valeurs_manquantes: dict[str, int]
    doublons: int
    distribution_durees: dict[str, float]
    mae: dict[str, float]
    meilleur_modele: str
    feature_historique_gardee: bool = False
    couverture_feature_historique: str = "non utilisee"


def entrainer_pipeline(
    raw_path: Path = RAW_PROJECTS_PATH,
    output_path: Path = PIPELINE_PATH,
    session_factory=SessionLocal,
    simulated: bool = False,
    run_history_path: Path = RUN_HISTORY_PATH,
) -> TrainingReport:
    settings.ensure_directories()
    dataset, quality = charger_dataset(raw_path)
    if len(dataset) < 2:
        raise RuntimeError("Pas assez de donnees historiques pour entrainer le modele DLL")

    with session_factory() as session:
        rows = [_to_training_row(session, item) for item in dataset]
        session.commit()

    X = [row["features_base"] for row in rows]
    y = [row["duree_reelle"] for row in rows]
    y_residu = [row["residu_buffer_deadline"] for row in rows]

    mae = {
        "baseline_residu_median": _loocv_baseline_residu(X, y_residu),
        "ridge": _loocv_pipeline(
            X,
            y_residu,
            _ridge_pipeline(use_history_feature=False),
        ),
        "kneighbors": _loocv_pipeline(
            X,
            y_residu,
            _knn_pipeline(len(rows), use_history_feature=False),
        ),
    }
    best_name = min(mae, key=mae.get)
    use_history_feature = False

    if best_name == "baseline_residu_median":
        estimator: Any = DummyRegressor(strategy="median")
    elif best_name == "ridge":
        estimator: Any = _ridge_pipeline(use_history_feature=use_history_feature)
    elif best_name == "kneighbors":
        estimator = _knn_pipeline(len(rows), use_history_feature=use_history_feature)
    else:
        raise RuntimeError(f"Modele inconnu: {best_name}")

    X_final = X
    y_final = y_residu
    estimator.fit(X_final, y_final)
    feature_names = list(construire_features(SimpleNamespace(
        silhouette_id=0,
        architecture_ee_id=0,
        fournisseur_id=0,
        type_homologation=TypeHomologation.MAQUETTE,
    )).keys())
    if use_history_feature:
        feature_names.append("duree_moyenne_historique")

    artifact = {
        "model_name": best_name,
        "model_version": "1.0",
        "pipeline": estimator,
        "training_rows": rows,
        "feature_names": feature_names,
        "use_history_feature": use_history_feature,
        "feature_history_coverage": "non utilisee",
        "target_mode": "residu_buffer_deadline",
        "gabarit_duration_days": GABARIT_DURATION_DAYS,
        "mae": mae,
    }
    joblib.dump(artifact, output_path)
    append_run_history(
        model_name=best_name,
        mae=mae,
        n_rows=len(rows),
        feature_set=feature_names,
        pipeline="dll",
        path=run_history_path,
        extra={"target_mode": "residu_buffer_deadline", "simulated": simulated},
    )
    return TrainingReport(
        lignes_raw=quality["lignes_raw"],
        lignes_utilisables=len(rows),
        valeurs_manquantes=quality["valeurs_manquantes"],
        doublons=quality["doublons"],
        distribution_durees=_distribution(y),
        mae=mae,
        meilleur_modele=best_name,
        feature_historique_gardee=use_history_feature,
        couverture_feature_historique="non utilisee",
    )


def charger_dataset(raw_path: Path = RAW_PROJECTS_PATH) -> tuple[list[dict], dict]:
    df = pd.read_excel(raw_path, sheet_name=0)
    valeurs_manquantes = {str(k): int(v) for k, v in df.isna().sum().to_dict().items()}
    doublons = int(df.duplicated().sum())
    records = []
    for _, row in df.iterrows():
        cmde = _parse_date(row.get("CMDE"))
        retour = _parse_date(row.get("DLL de retour"))
        deadline_buffer = _parse_date(row.get("Dead Line avec BUFFER"))
        deadline = _parse_date(row.get("Dead Line"))
        if cmde is None or retour is None:
            continue
        duree = (retour - cmde).days
        if duree <= 0:
            continue
        if deadline_buffer is not None and deadline is not None:
            residu = (deadline - deadline_buffer).days
        else:
            residu = duree - GABARIT_DURATION_DAYS
        records.append(
            {
                "pro": _clean_token(row.get("Pro")) or "UNKNOWN",
                "mot": _clean_token(row.get("Mot")) or "M0",
                "silhouette": _clean_token(row.get("Silh hom.")) or "UNKNOWN",
                "sujet": str(row.get("Sujet") or ""),
                "date_cmde": cmde,
                "date_deadline_buffer": deadline_buffer,
                "date_deadline": deadline,
                "date_retour_reel": retour,
                "duree_reelle": duree,
                "residu_buffer_deadline": residu,
            }
        )
    return records, {
        "lignes_raw": int(len(df)),
        "valeurs_manquantes": valeurs_manquantes,
        "doublons": doublons,
    }


def _to_training_row(session, item: dict) -> dict:
    silhouette = _get_or_create(session, models.Silhouette, "libelle", item["silhouette"])
    architecture = _get_or_create(
        session,
        models.ArchitectureEE,
        "reference",
        item["pro"],
        {"version": "RAW"},
    )
    fournisseur = _get_or_create(session, models.Fournisseur, "nom", "FOURNISSEUR_A")
    maquette_like = SimpleNamespace(
        silhouette_id=silhouette.id,
        architecture_ee_id=architecture.id,
        fournisseur_id=fournisseur.id,
        type_homologation=TypeHomologation.MAQUETTE,
    )
    features = construire_feature_row(maquette_like)
    homologation_like = SimpleNamespace(
        maquette=maquette_like,
        date_cmde=item["date_cmde"],
        date_deadline_buffer=item["date_deadline_buffer"],
        date_deadline=item["date_deadline"],
        date_retour_reel=item["date_retour_reel"],
    )
    return {
        "reference": item["pro"],
        "modele": item["mot"],
        "silhouette": item["silhouette"],
        "sujet": item["sujet"],
        "features": features,
        "features_base": features,
        "feature_dict": construire_features(maquette_like),
        "maquette": maquette_like,
        "homologation": homologation_like,
        "date_cmde": item["date_cmde"],
        "date_deadline_buffer": item["date_deadline_buffer"],
        "date_deadline": item["date_deadline"],
        "date_retour_reel": item["date_retour_reel"],
        "duree_reelle": item["duree_reelle"],
        "residu_buffer_deadline": item["residu_buffer_deadline"],
    }


def _get_or_create(session, model, attr: str, value: str, extra: dict | None = None):
    row = session.query(model).filter(getattr(model, attr) == value).one_or_none()
    if row is not None:
        return row
    kwargs = {attr: value}
    if extra:
        kwargs.update(extra)
    row = model(**kwargs)
    session.add(row)
    session.flush()
    return row


def _ridge_pipeline(use_history_feature: bool = False) -> Pipeline:
    return Pipeline(
        [
            ("encoder", _encoder(use_history_feature=use_history_feature)),
            ("model", Ridge(alpha=1.0)),
        ]
    )


def _knn_pipeline(n_rows: int, use_history_feature: bool = False) -> Pipeline:
    return Pipeline(
        [
            ("encoder", _encoder(use_history_feature=use_history_feature)),
            ("model", KNeighborsRegressor(n_neighbors=max(1, min(3, n_rows - 1)))),
        ]
    )


def _encoder(use_history_feature: bool = False) -> ColumnTransformer:
    transformers: list[tuple[str, object, list[int]]] = [
        ("categorical", OneHotEncoder(handle_unknown="ignore"), [0, 1, 2, 3])
    ]
    if use_history_feature:
        transformers.append(("history", SimpleImputer(strategy="median"), [4]))
    return ColumnTransformer(transformers)


def _loocv_pipeline(
    X: list[list],
    y: list[float],
    pipeline: Pipeline,
) -> float:
    predictions = []
    actual = []
    loo = LeaveOneOut()
    for train_index, test_index in loo.split(X):
        X_train = [X[i] for i in train_index]
        y_train = [y[i] for i in train_index]
        X_test = [X[i] for i in test_index]
        pipeline.fit(X_train, y_train)
        predictions.extend(list(pipeline.predict(X_test)))
        actual.extend([y[i] for i in test_index])
    return float(mean_absolute_error(actual, predictions))


def _loocv_baseline_residu(X: list[list], y: list[float]) -> float:
    return _loocv_pipeline(X, y, DummyRegressor(strategy="median"))


def _distribution(values: list[float]) -> dict[str, float]:
    series = pd.Series(values)
    return {
        "count": float(series.count()),
        "min": float(series.min()),
        "median": float(series.median()),
        "mean": float(series.mean()),
        "max": float(series.max()),
        "std": float(0.0 if math.isnan(series.std()) else series.std()),
    }


def _parse_date(value) -> date | None:
    if pd.isna(value):
        return None
    parsed = pd.to_datetime(value, dayfirst=True, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def _clean_token(value) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip().upper()
    match = re.search(r"[A-Z]+\d+", text)
    return match.group(0) if match else text or None


if __name__ == "__main__":
    report = entrainer_pipeline()
    print(report)
