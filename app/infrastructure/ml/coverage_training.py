"""Entrainement/diagnostic ML pour la couverture homologation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, precision_score, recall_score
from sklearn.model_selection import LeaveOneOut
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.tree import DecisionTreeClassifier

from app.config.settings import settings
from app.infrastructure.ml.coverage_dataset import charger_dataset_couverture

COVERAGE_PIPELINE_PATH = settings.ml_models_dir / "coverage_pipeline.joblib"
FEATURE_COLUMNS = [
    "silhouette_id",
    "architecture_ee_id",
    "fournisseur_id",
    "type_homologation",
]


@dataclass(frozen=True)
class CoverageTrainingReport:
    lignes_utilisables: int
    circularite_detectee: bool
    metrics: dict[str, dict[str, float]]
    meilleur_modele: str
    conclusion: str


class RuleCoverageBaseline:
    """Baseline metier : couverture si ArchitectureEE deja couverte."""

    def fit(self, X, y):
        frame = _as_frame(X)
        self.covered_architectures_ = {
            row["architecture_ee_id"]
            for row, label in zip(frame.to_dict("records"), y)
            if int(label) == 1
        }
        self.majority_label_ = int(round(sum(int(v) for v in y) / len(y))) if y else 0
        return self

    def predict(self, X):
        frame = _as_frame(X)
        return [
            int(row["architecture_ee_id"] in self.covered_architectures_)
            for row in frame.to_dict("records")
        ]


def entrainer_couverture(
    output_path: Path = COVERAGE_PIPELINE_PATH,
    session_factory=None,
    circularity_threshold: float = 0.99,
) -> CoverageTrainingReport:
    settings.ensure_directories()
    dataset = charger_dataset_couverture(session_factory=session_factory) if session_factory else charger_dataset_couverture()
    if dataset.empty:
        artifact = _artifact(
            model_name="rule_baseline",
            pipeline=RuleCoverageBaseline().fit([], []),
            dataset=dataset,
            metrics={},
            circularite_detectee=False,
            conclusion="Aucune decision de couverture disponible.",
        )
        joblib.dump(artifact, output_path)
        return CoverageTrainingReport(0, False, {}, "rule_baseline", artifact["conclusion"])

    X = dataset[FEATURE_COLUMNS]
    y = dataset["label_couverture"].astype(int).tolist()
    baseline_predictions = predire_regle_pure_loocv(dataset)
    metrics = {
        "rule_baseline": _metrics(y, baseline_predictions),
    }
    circularite = metrics["rule_baseline"]["accuracy"] >= circularity_threshold

    if circularite:
        pipeline: Any = RuleCoverageBaseline().fit(X, y)
        best_name = "rule_baseline"
        conclusion = (
            "La regle pure reproduit les decisions existantes : le label est "
            "determine par construction, aucun classifieur n'est entraine."
        )
    else:
        candidates = _candidate_metrics(X, y)
        metrics.update(candidates)
        best_name = _best_model(metrics)
        if best_name == "rule_baseline":
            pipeline = RuleCoverageBaseline().fit(X, y)
            conclusion = "Aucun classifieur ne bat la baseline regle ; baseline conservee."
        else:
            pipeline = _make_classifier(best_name)
            pipeline.fit(X, y)
            conclusion = f"Classifieur retenu car il bat la baseline regle : {best_name}."

    artifact = _artifact(
        model_name=best_name,
        pipeline=pipeline,
        dataset=dataset,
        metrics=metrics,
        circularite_detectee=circularite,
        conclusion=conclusion,
    )
    joblib.dump(artifact, output_path)
    return CoverageTrainingReport(
        lignes_utilisables=len(dataset),
        circularite_detectee=circularite,
        metrics=metrics,
        meilleur_modele=best_name,
        conclusion=conclusion,
    )


def predire_regle_pure_loocv(dataset: pd.DataFrame) -> list[int]:
    """Predictions LOOCV : archi couverte dans une autre ligne deja couverte."""

    predictions = []
    records = dataset.to_dict("records")
    for index, row in enumerate(records):
        covered_architectures = {
            other["architecture_ee_id"]
            for other_index, other in enumerate(records)
            if other_index != index and int(other["label_couverture"]) == 1
        }
        predictions.append(int(row["architecture_ee_id"] in covered_architectures))
    return predictions


def _candidate_metrics(X: pd.DataFrame, y: list[int]) -> dict[str, dict[str, float]]:
    if len(set(y)) < 2 or len(y) < 3:
        return {}
    return {
        "logistic_regression": _loocv_classifier(X, y, _make_classifier("logistic_regression")),
        "decision_tree_depth_3": _loocv_classifier(X, y, _make_classifier("decision_tree_depth_3")),
    }


def _loocv_classifier(X: pd.DataFrame, y: list[int], pipeline: Pipeline) -> dict[str, float]:
    predictions = []
    actual = []
    loo = LeaveOneOut()
    for train_index, test_index in loo.split(X):
        y_train = [y[i] for i in train_index]
        if len(set(y_train)) < 2:
            fallback = RuleCoverageBaseline().fit(X.iloc[train_index], y_train)
            predictions.extend(fallback.predict(X.iloc[test_index]))
        else:
            pipeline.fit(X.iloc[train_index], y_train)
            predictions.extend(list(pipeline.predict(X.iloc[test_index])))
        actual.extend([y[i] for i in test_index])
    return _metrics(actual, predictions)


def _make_classifier(name: str) -> Pipeline:
    model: Any
    if name == "logistic_regression":
        model = LogisticRegression(max_iter=1000)
    elif name == "decision_tree_depth_3":
        model = DecisionTreeClassifier(max_depth=3, random_state=42)
    else:
        raise RuntimeError(f"Classifieur inconnu: {name}")
    return Pipeline(
        [
            (
                "encoder",
                ColumnTransformer(
                    [("categorical", OneHotEncoder(handle_unknown="ignore"), FEATURE_COLUMNS)]
                ),
            ),
            ("model", model),
        ]
    )


def _best_model(metrics: dict[str, dict[str, float]]) -> str:
    return max(
        metrics,
        key=lambda name: (
            metrics[name]["accuracy"],
            metrics[name]["recall"],
            metrics[name]["precision"],
        ),
    )


def _metrics(actual: list[int], predictions: list[int]) -> dict[str, float]:
    if not actual:
        return {"accuracy": 0.0, "precision": 0.0, "recall": 0.0}
    return {
        "accuracy": float(accuracy_score(actual, predictions)),
        "precision": float(precision_score(actual, predictions, zero_division=0)),
        "recall": float(recall_score(actual, predictions, zero_division=0)),
    }


def _artifact(
    model_name: str,
    pipeline,
    dataset: pd.DataFrame,
    metrics: dict[str, dict[str, float]],
    circularite_detectee: bool,
    conclusion: str,
) -> dict:
    return {
        "model_name": model_name,
        "model_version": "1.0",
        "pipeline": pipeline,
        "feature_names": FEATURE_COLUMNS,
        "target": "label_couverture",
        "training_rows": dataset.to_dict("records"),
        "metrics": metrics,
        "circularite_detectee": circularite_detectee,
        "conclusion": conclusion,
    }


def _as_frame(X) -> pd.DataFrame:
    if isinstance(X, pd.DataFrame):
        return X[FEATURE_COLUMNS] if set(FEATURE_COLUMNS).issubset(X.columns) else X
    return pd.DataFrame(X, columns=FEATURE_COLUMNS)


if __name__ == "__main__":
    report = entrainer_couverture()
    print(report)
