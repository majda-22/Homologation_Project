"""Services applicatifs Planning."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.planning.gabarit_service import generer_planning_theorique
from app.domain.planning.entities import EtapeConstruction, PlanningConstruction
from app.infrastructure.database.database import SessionLocal
from app.infrastructure.database import models
from app.infrastructure.database.repositories.planning_repositories import (
    SQLAlchemyEtapeConstructionRepository,
    SQLAlchemyPlanningRepository,
)
from app.infrastructure.database.repositories.project_repositories import SQLAlchemyMaquetteRepository
from app.shared.enums import StatutAvancement, StatutEtape
from app.shared.exceptions import RessourceDejaExistante, RessourceIntrouvable


@dataclass(frozen=True)
class PlanningDTO:
    id: int
    maquette_id: int
    statut_avancement: StatutAvancement
    priorite_score: Optional[float]


@dataclass(frozen=True)
class EtapeConstructionDTO:
    id: int
    planning_id: int
    ordre: int
    libelle: str
    date_debut: Optional[date]
    date_fin: Optional[date]
    statut: StatutEtape


def _planning_dto(item: PlanningConstruction) -> PlanningDTO:
    if item.id is None:
        raise ValueError("Un planning persiste doit avoir un id")
    return PlanningDTO(
        id=item.id,
        maquette_id=item.maquette_id,
        statut_avancement=item.statut_avancement,
        priorite_score=item.priorite_score,
    )


def _etape_dto(item: EtapeConstruction) -> EtapeConstructionDTO:
    if item.id is None:
        raise ValueError("Une etape persistee doit avoir un id")
    return EtapeConstructionDTO(
        id=item.id,
        planning_id=item.planning_id,
        ordre=item.ordre,
        libelle=item.libelle,
        date_debut=item.date_debut,
        date_fin=item.date_fin,
        statut=item.statut,
    )


class PlanningService:
    def __init__(self, session_factory: Callable[[], Session] = SessionLocal) -> None:
        self.session_factory = session_factory

    @staticmethod
    def calculer_urgence(
        date_deadline: Optional[date],
        aujourdhui: Optional[date] = None,
    ) -> float:
        if date_deadline is None:
            return 0.0
        today = aujourdhui or date.today()
        jours_restants = (date_deadline - today).days
        if jours_restants < 0:
            return 10_000.0 + abs(jours_restants)
        return max(0.0, 1_000.0 - float(jours_restants))

    @classmethod
    def reordonnancer(
        cls,
        maquettes: list[object],
        aujourdhui: Optional[date] = None,
    ) -> list[object]:
        today = aujourdhui or date.today()
        return sorted(
            maquettes,
            key=lambda maquette: cls.calculer_urgence(
                getattr(maquette, "date_deadline", None),
                today,
            ),
            reverse=True,
        )

    def creer_planning(
        self,
        maquette_id: int,
        priorite_score: Optional[float] = None,
    ) -> PlanningDTO:
        with self.session_factory() as session:
            maquettes = SQLAlchemyMaquetteRepository(session)
            if maquettes.obtenir_par_id(maquette_id) is None:
                raise RessourceIntrouvable(f"Maquette introuvable: {maquette_id}")
            plannings = SQLAlchemyPlanningRepository(session)
            if plannings.obtenir_par_maquette(maquette_id) is not None:
                raise RessourceDejaExistante(
                    f"Un planning existe deja pour la maquette {maquette_id}"
                )
            planning = PlanningConstruction(maquette_id=maquette_id)
            planning.definir_priorite(priorite_score)
            try:
                planning = plannings.ajouter(planning)
                session.commit()
                return _planning_dto(planning)
            except IntegrityError as exc:
                session.rollback()
                raise RessourceDejaExistante(
                    f"Un planning existe deja pour la maquette {maquette_id}"
                ) from exc

    def lister_plannings(self) -> list[PlanningDTO]:
        with self.session_factory() as session:
            plannings = SQLAlchemyPlanningRepository(session)
            return [_planning_dto(item) for item in plannings.lister()]

    def recalculer_priorites(self, aujourdhui: Optional[date] = None) -> list[PlanningDTO]:
        today = aujourdhui or date.today()
        with self.session_factory() as session:
            rows = list(
                session.scalars(
                    select(models.PlanningConstruction)
                )
            )
            for planning in rows:
                deadline = session.scalar(
                    select(models.Homologation.date_deadline)
                    .where(models.Homologation.maquette_id == planning.maquette_id)
                    .where(models.Homologation.date_deadline.is_not(None))
                    .order_by(models.Homologation.date_deadline.asc())
                    .limit(1)
                )
                planning.priorite_score = self.calculer_urgence(deadline, today)
            session.commit()
            return [
                PlanningDTO(
                    id=row.id,
                    maquette_id=row.maquette_id,
                    statut_avancement=row.statut_avancement,
                    priorite_score=row.priorite_score,
                )
                for row in rows
            ]

    def reordonnancer_toutes_les_maquettes_actives(
        self,
        aujourdhui: Optional[date] = None,
    ) -> list[PlanningDTO]:
        """Point de verite du reordonnancement global.

        Utilise par les handlers automatiques et par le bouton manuel de l'UI.
        """
        return self.recalculer_priorites(aujourdhui=aujourdhui)

    def generer_planning_theorique_maquette(
        self,
        maquette_id: int,
        date_livraison_cdc: date,
        residu_predit: int,
    ) -> PlanningDTO:
        with self.session_factory() as session:
            maquette = session.get(models.Maquette, maquette_id)
            if maquette is None:
                raise RessourceIntrouvable(f"Maquette introuvable: {maquette_id}")
            planning = session.scalar(
                select(models.PlanningConstruction).where(
                    models.PlanningConstruction.maquette_id == maquette_id
                )
            )
            if planning is None:
                planning = models.PlanningConstruction(
                    maquette_id=maquette_id,
                    statut_avancement=StatutAvancement.PLANIFIEE,
                    priorite_score=None,
                )
                session.add(planning)
                session.flush()

            has_steps = session.scalar(
                select(models.EtapeConstruction.id)
                .where(models.EtapeConstruction.planning_id == planning.id)
                .limit(1)
            )
            if has_steps is None:
                for ordre, etape in enumerate(
                    generer_planning_theorique(date_livraison_cdc, residu_predit),
                    start=1,
                ):
                    session.add(
                        models.EtapeConstruction(
                            planning_id=planning.id,
                            ordre=ordre,
                            libelle=etape.libelle,
                            date_debut=etape.date_debut_estimee,
                            date_fin=etape.date_fin_estimee,
                            statut=StatutEtape.A_FAIRE,
                        )
                    )

            deadline = session.scalar(
                select(models.Homologation.date_deadline)
                .where(models.Homologation.maquette_id == maquette_id)
                .where(models.Homologation.date_deadline.is_not(None))
                .order_by(models.Homologation.date_deadline.asc())
                .limit(1)
            )
            planning.priorite_score = self.calculer_urgence(deadline)
            session.commit()
            return PlanningDTO(
                id=planning.id,
                maquette_id=planning.maquette_id,
                statut_avancement=planning.statut_avancement,
                priorite_score=planning.priorite_score,
            )

    def changer_statut_planning(
        self,
        planning_id: int,
        statut: StatutAvancement,
    ) -> PlanningDTO:
        with self.session_factory() as session:
            plannings = SQLAlchemyPlanningRepository(session)
            planning = plannings.obtenir_par_id(planning_id)
            if planning is None:
                raise RessourceIntrouvable(f"Planning introuvable: {planning_id}")
            planning.changer_statut(statut)
            planning = plannings.sauvegarder(planning)
            session.commit()
            return _planning_dto(planning)

    def definir_priorite(self, planning_id: int, score: Optional[float]) -> PlanningDTO:
        with self.session_factory() as session:
            plannings = SQLAlchemyPlanningRepository(session)
            planning = plannings.obtenir_par_id(planning_id)
            if planning is None:
                raise RessourceIntrouvable(f"Planning introuvable: {planning_id}")
            planning.definir_priorite(score)
            planning = plannings.sauvegarder(planning)
            session.commit()
            return _planning_dto(planning)

    def ajouter_etape(
        self,
        planning_id: int,
        ordre: int,
        libelle: str,
        date_debut: Optional[date] = None,
        date_fin: Optional[date] = None,
    ) -> EtapeConstructionDTO:
        with self.session_factory() as session:
            plannings = SQLAlchemyPlanningRepository(session)
            if plannings.obtenir_par_id(planning_id) is None:
                raise RessourceIntrouvable(f"Planning introuvable: {planning_id}")
            etapes = SQLAlchemyEtapeConstructionRepository(session)
            etape = etapes.ajouter(
                EtapeConstruction(
                    planning_id=planning_id,
                    ordre=ordre,
                    libelle=libelle,
                    date_debut=date_debut,
                    date_fin=date_fin,
                )
            )
            session.commit()
            return _etape_dto(etape)

    def lister_etapes(self, planning_id: int) -> list[EtapeConstructionDTO]:
        with self.session_factory() as session:
            etapes = SQLAlchemyEtapeConstructionRepository(session)
            return [_etape_dto(item) for item in etapes.lister_par_planning(planning_id)]

    def changer_statut_etape(self, etape_id: int, statut: StatutEtape) -> EtapeConstructionDTO:
        with self.session_factory() as session:
            row = session.get(models.EtapeConstruction, etape_id)
            if row is None:
                raise RessourceIntrouvable(f"Etape introuvable: {etape_id}")
            etape = EtapeConstruction(
                id=row.id,
                planning_id=row.planning_id,
                ordre=row.ordre,
                libelle=row.libelle,
                date_debut=row.date_debut,
                date_fin=row.date_fin,
                statut=row.statut,
            )
            etape.changer_statut(statut)
            etape = SQLAlchemyEtapeConstructionRepository(session).sauvegarder(etape)
            session.commit()
            return _etape_dto(etape)
