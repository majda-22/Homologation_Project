"""Garde-fous EDA pour les features de prediction DLL.

Ce module documente explicitement ce qui est disponible au moment de la
prediction. Les jalons dates restent interdits comme features brutes : seule
une statistique historique calculee sur des homologations terminees peut etre
utilisee sans fuite de donnees.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class FeatureAvailability:
    feature: str
    disponible_prediction: bool
    justification: str


FEATURE_AVAILABILITY_TABLE: tuple[FeatureAvailability, ...] = (
    FeatureAvailability(
        "silhouette_id",
        True,
        "Renseignee a la creation de la maquette.",
    ),
    FeatureAvailability(
        "architecture_ee_id",
        True,
        "Renseignee a la creation de la maquette.",
    ),
    FeatureAvailability(
        "fournisseur_id",
        True,
        "Renseigne a la creation de la maquette.",
    ),
    FeatureAvailability(
        "type_homologation",
        True,
        "Connu avant le lancement du workflow homologation.",
    ),
    FeatureAvailability(
        "date_livraison_cdc",
        False,
        "Jalon produit pendant le cycle, indisponible avant prediction.",
    ),
    FeatureAvailability(
        "date_cmde",
        False,
        "Jalon futur au moment ou la prediction DLL a de la valeur.",
    ),
    FeatureAvailability(
        "date_montage",
        False,
        "Jalon futur, interdit comme feature brute.",
    ),
    FeatureAvailability(
        "date_validation_fonctionnelle",
        False,
        "Jalon futur, interdit comme feature brute.",
    ),
    FeatureAvailability(
        "date_deadline_buffer",
        False,
        "Deadline calculee/connue apres cadrage, pas une feature initiale sure.",
    ),
    FeatureAvailability(
        "date_deadline",
        False,
        "Deadline operationnelle, non disponible comme signal initial fiable.",
    ),
    FeatureAvailability(
        "date_retour_reel",
        False,
        "Cible terrain finale, fuite directe si utilisee comme feature.",
    ),
    FeatureAvailability(
        "duree_moyenne_historique",
        True,
        "Agregat calcule uniquement sur homologations terminees historiques.",
    ),
)


def disponibilite_features() -> list[dict[str, object]]:
    """Retourne le tableau EDA sous une forme serialisable pour rapport/tests."""
    return [
        {
            "feature": row.feature,
            "disponible_prediction": "OUI" if row.disponible_prediction else "NON",
            "justification": row.justification,
        }
        for row in FEATURE_AVAILABILITY_TABLE
    ]


def duree_moyenne_historique(
    silhouette_id,
    architecture_ee_id,
    homologations_terminees: Iterable[object],
) -> float | None:
    """Moyenne historique sans fuite pour une silhouette/architecture EE.

    La fonction ne lit jamais la ligne en cours toute seule : c'est l'appelant
    qui doit fournir uniquement l'historique admissible, notamment en LOOCV.
    """
    correspondances = [
        homologation
        for homologation in homologations_terminees
        if homologation.maquette.silhouette_id == silhouette_id
        and homologation.maquette.architecture_ee_id == architecture_ee_id
        and homologation.date_retour_reel
        and homologation.date_cmde
    ]
    if not correspondances:
        return None
    durees = [
        (homologation.date_retour_reel - homologation.date_cmde).days
        for homologation in correspondances
    ]
    return sum(durees) / len(durees)
