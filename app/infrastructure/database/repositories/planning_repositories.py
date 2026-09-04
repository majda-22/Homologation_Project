"""Repositories SQLAlchemy pour le bounded context Planning."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.planning.entities import EtapeConstruction, PlanningConstruction
from app.domain.planning.repositories import EtapeConstructionRepository, PlanningRepository
from app.infrastructure.database import models


def _to_domain_planning(row: models.PlanningConstruction) -> PlanningConstruction:
    return PlanningConstruction(
        id=row.id,
        maquette_id=row.maquette_id,
        statut_avancement=row.statut_avancement,
        priorite_score=row.priorite_score,
    )


def _to_domain_etape(row: models.EtapeConstruction) -> EtapeConstruction:
    return EtapeConstruction(
        id=row.id,
        planning_id=row.planning_id,
        ordre=row.ordre,
        libelle=row.libelle,
        date_debut=row.date_debut,
        date_fin=row.date_fin,
        statut=row.statut,
    )


class SQLAlchemyPlanningRepository(PlanningRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def ajouter(self, planning: PlanningConstruction) -> PlanningConstruction:
        row = models.PlanningConstruction(
            maquette_id=planning.maquette_id,
            statut_avancement=planning.statut_avancement,
            priorite_score=planning.priorite_score,
        )
        self.session.add(row)
        self.session.flush()
        return _to_domain_planning(row)

    def obtenir_par_id(self, planning_id: int) -> Optional[PlanningConstruction]:
        row = self.session.get(models.PlanningConstruction, planning_id)
        return _to_domain_planning(row) if row else None

    def obtenir_par_maquette(self, maquette_id: int) -> Optional[PlanningConstruction]:
        row = self.session.scalar(
            select(models.PlanningConstruction).where(
                models.PlanningConstruction.maquette_id == maquette_id
            )
        )
        return _to_domain_planning(row) if row else None

    def lister(self) -> list[PlanningConstruction]:
        statement = select(models.PlanningConstruction).order_by(
            models.PlanningConstruction.priorite_score.desc().nullslast(),
            models.PlanningConstruction.id.desc(),
        )
        return [_to_domain_planning(row) for row in self.session.scalars(statement)]

    def sauvegarder(self, planning: PlanningConstruction) -> PlanningConstruction:
        row = self.session.get(models.PlanningConstruction, planning.id)
        if row is None:
            raise ValueError(f"Planning introuvable: {planning.id}")
        row.statut_avancement = planning.statut_avancement
        row.priorite_score = planning.priorite_score
        self.session.flush()
        return _to_domain_planning(row)


class SQLAlchemyEtapeConstructionRepository(EtapeConstructionRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def ajouter(self, etape: EtapeConstruction) -> EtapeConstruction:
        row = models.EtapeConstruction(
            planning_id=etape.planning_id,
            ordre=etape.ordre,
            libelle=etape.libelle,
            date_debut=etape.date_debut,
            date_fin=etape.date_fin,
            statut=etape.statut,
        )
        self.session.add(row)
        self.session.flush()
        return _to_domain_etape(row)

    def lister_par_planning(self, planning_id: int) -> list[EtapeConstruction]:
        statement = (
            select(models.EtapeConstruction)
            .where(models.EtapeConstruction.planning_id == planning_id)
            .order_by(models.EtapeConstruction.ordre)
        )
        return [_to_domain_etape(row) for row in self.session.scalars(statement)]

    def sauvegarder(self, etape: EtapeConstruction) -> EtapeConstruction:
        row = self.session.get(models.EtapeConstruction, etape.id)
        if row is None:
            raise ValueError(f"Etape introuvable: {etape.id}")
        row.ordre = etape.ordre
        row.libelle = etape.libelle
        row.date_debut = etape.date_debut
        row.date_fin = etape.date_fin
        row.statut = etape.statut
        self.session.flush()
        return _to_domain_etape(row)
