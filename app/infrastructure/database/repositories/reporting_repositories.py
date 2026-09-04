"""Read models SQLAlchemy pour le bounded context Reporting."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.reporting.repositories import ReportingReadRepository
from app.infrastructure.database import models


class SQLAlchemyReportingReadRepository(ReportingReadRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def resume_projet(self, projet_id: int) -> dict:
        projet = self.session.get(models.Projet, projet_id)
        if projet is None:
            return {}

        maquettes = list(
            self.session.scalars(
                select(models.Maquette).where(models.Maquette.projet_id == projet_id)
            )
        )
        maquette_ids = [maquette.id for maquette in maquettes]
        homologations = []
        if maquette_ids:
            homologations = list(
                self.session.scalars(
                    select(models.Homologation).where(
                        models.Homologation.maquette_id.in_(maquette_ids)
                    )
                )
            )

        return {
            "id": projet.id,
            "reference": projet.reference,
            "statut": projet.statut.value,
            "date_creation": str(projet.date_creation),
            "maquettes": len(maquettes),
            "homologations": len(homologations),
        }

    def tableau_bord(self) -> dict:
        return {
            "projets": self.session.scalar(select(func.count(models.Projet.id))) or 0,
            "maquettes": self.session.scalar(select(func.count(models.Maquette.id))) or 0,
            "homologations": self.session.scalar(select(func.count(models.Homologation.id))) or 0,
            "plannings": self.session.scalar(select(func.count(models.PlanningConstruction.id))) or 0,
            "notifications_non_lues": self.session.scalar(
                select(func.count(models.Notification.id)).where(models.Notification.lu == False)
            )
            or 0,
        }

    def lignes_cdc(self, maquette_id: Optional[int] = None) -> list[dict]:
        statement = (
            select(models.LigneCDC, models.TypeComposant)
            .join(models.TypeComposant)
            .order_by(models.LigneCDC.maquette_id, models.TypeComposant.code)
        )
        if maquette_id is not None:
            statement = statement.where(models.LigneCDC.maquette_id == maquette_id)

        return [
            {
                "maquette_id": ligne.maquette_id,
                "type_composant": type_composant.code,
                "quantite_hw": ligne.quantite_hw,
                "origine": ligne.origine.value,
            }
            for ligne, type_composant in self.session.execute(statement)
        ]
