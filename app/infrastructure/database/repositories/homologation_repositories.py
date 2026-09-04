"""Repositories SQLAlchemy pour le bounded context Homologation."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.homologation.entities import (
    DecisionCouverture,
    Homologation,
    SilhouetteCouverte,
)
from app.domain.homologation.repositories import (
    DecisionCouvertureRepository,
    HomologationRepository,
    SilhouetteCouverteRepository,
)
from app.infrastructure.database import models


def _to_domain_homologation(row: models.Homologation) -> Homologation:
    return Homologation(
        id=row.id,
        maquette_id=row.maquette_id,
        statut=row.statut,
        date_livraison_cdc=row.date_livraison_cdc,
        date_cmde=row.date_cmde,
        date_montage=row.date_montage,
        date_validation_fonctionnelle=row.date_validation_fonctionnelle,
        date_deadline_buffer=row.date_deadline_buffer,
        date_deadline=row.date_deadline,
        date_retour_reel=row.date_retour_reel,
    )


def _to_domain_decision(row: models.DecisionCouverture) -> DecisionCouverture:
    return DecisionCouverture(
        id=row.id,
        homologation_id=row.homologation_id,
        est_couverte=row.est_couverte,
        projet_couvrant_id=row.projet_couvrant_id,
        justification=row.justification,
        date_decision=row.date_decision,
    )


def _to_domain_silhouette(row: models.SilhouetteCouverte) -> SilhouetteCouverte:
    return SilhouetteCouverte(
        id=row.id,
        homologation_id=row.homologation_id,
        silhouette_id=row.silhouette_id,
        origine=row.origine,
    )


class SQLAlchemyHomologationRepository(HomologationRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def ajouter(self, homologation: Homologation) -> Homologation:
        row = models.Homologation(
            maquette_id=homologation.maquette_id,
            statut=homologation.statut,
            date_livraison_cdc=homologation.date_livraison_cdc,
            date_cmde=homologation.date_cmde,
            date_montage=homologation.date_montage,
            date_validation_fonctionnelle=homologation.date_validation_fonctionnelle,
            date_deadline_buffer=homologation.date_deadline_buffer,
            date_deadline=homologation.date_deadline,
            date_retour_reel=homologation.date_retour_reel,
        )
        self.session.add(row)
        self.session.flush()
        return _to_domain_homologation(row)

    def obtenir_par_id(self, homologation_id: int) -> Optional[Homologation]:
        row = self.session.get(models.Homologation, homologation_id)
        return _to_domain_homologation(row) if row else None

    def lister(self, maquette_id: Optional[int] = None) -> list[Homologation]:
        statement = select(models.Homologation).order_by(models.Homologation.id.desc())
        if maquette_id is not None:
            statement = statement.where(models.Homologation.maquette_id == maquette_id)
        return [_to_domain_homologation(row) for row in self.session.scalars(statement)]

    def sauvegarder(self, homologation: Homologation) -> Homologation:
        row = self.session.get(models.Homologation, homologation.id)
        if row is None:
            raise ValueError(f"Homologation introuvable: {homologation.id}")
        row.statut = homologation.statut
        row.date_livraison_cdc = homologation.date_livraison_cdc
        row.date_cmde = homologation.date_cmde
        row.date_montage = homologation.date_montage
        row.date_validation_fonctionnelle = homologation.date_validation_fonctionnelle
        row.date_deadline_buffer = homologation.date_deadline_buffer
        row.date_deadline = homologation.date_deadline
        row.date_retour_reel = homologation.date_retour_reel
        self.session.flush()
        return _to_domain_homologation(row)


class SQLAlchemyDecisionCouvertureRepository(DecisionCouvertureRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def ajouter(self, decision: DecisionCouverture) -> DecisionCouverture:
        row = models.DecisionCouverture(
            homologation_id=decision.homologation_id,
            est_couverte=decision.est_couverte,
            projet_couvrant_id=decision.projet_couvrant_id,
            justification=decision.justification,
        )
        self.session.add(row)
        self.session.flush()
        return _to_domain_decision(row)

    def lister_par_homologation(self, homologation_id: int) -> list[DecisionCouverture]:
        statement = (
            select(models.DecisionCouverture)
            .where(models.DecisionCouverture.homologation_id == homologation_id)
            .order_by(models.DecisionCouverture.id.desc())
        )
        return [_to_domain_decision(row) for row in self.session.scalars(statement)]


class SQLAlchemySilhouetteCouverteRepository(SilhouetteCouverteRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def ajouter(self, silhouette: SilhouetteCouverte) -> SilhouetteCouverte:
        row = models.SilhouetteCouverte(
            homologation_id=silhouette.homologation_id,
            silhouette_id=silhouette.silhouette_id,
            origine=silhouette.origine,
        )
        self.session.add(row)
        self.session.flush()
        return _to_domain_silhouette(row)

    def lister_par_homologation(self, homologation_id: int) -> list[SilhouetteCouverte]:
        statement = (
            select(models.SilhouetteCouverte)
            .where(models.SilhouetteCouverte.homologation_id == homologation_id)
            .order_by(models.SilhouetteCouverte.id.desc())
        )
        return [_to_domain_silhouette(row) for row in self.session.scalars(statement)]

    def retirer(self, silhouette_couverte_id: int) -> None:
        row = self.session.get(models.SilhouetteCouverte, silhouette_couverte_id)
        if row is None:
            raise ValueError(f"Silhouette couverte introuvable: {silhouette_couverte_id}")
        self.session.delete(row)
        self.session.flush()
