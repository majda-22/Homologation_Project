"""Dataset ML pour la classification de couverture."""

from __future__ import annotations

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.infrastructure.database import models
from app.infrastructure.database.database import SessionLocal


def construire_dataset_couverture(decisions: list[models.DecisionCouverture]) -> pd.DataFrame:
    """Construit une ligne supervisee par DecisionCouverture."""

    lignes = []
    for decision in decisions:
        maquette = decision.homologation.maquette
        lignes.append(
            {
                "silhouette_id": maquette.silhouette_id,
                "architecture_ee_id": maquette.architecture_ee_id,
                "fournisseur_id": maquette.fournisseur_id,
                "type_homologation": maquette.type_homologation.value,
                "label_couverture": int(decision.est_couverte),
            }
        )
    return pd.DataFrame(lignes)


def charger_dataset_couverture(session_factory=SessionLocal) -> pd.DataFrame:
    """Charge les decisions de la base et construit le dataset supervise."""

    with session_factory() as session:
        decisions = list(
            session.scalars(
                select(models.DecisionCouverture)
                .options(
                    joinedload(models.DecisionCouverture.homologation).joinedload(
                        models.Homologation.maquette
                    )
                )
                .order_by(models.DecisionCouverture.id)
            )
        )
        return construire_dataset_couverture(decisions)
