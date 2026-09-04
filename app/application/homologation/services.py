"""Services applicatifs Homologation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.homologation.events import (
    DateDeadlineChangee,
    DecisionCouvertureCreee,
    HomologationDemarree,
    RetardDetecte,
)
from app.domain.homologation.entities import (
    DecisionCouverture,
    Homologation,
    SilhouetteCouverte,
)
from app.infrastructure.database.database import SessionLocal
from app.infrastructure.database import models
from app.infrastructure.database.repositories.homologation_repositories import (
    SQLAlchemyDecisionCouvertureRepository,
    SQLAlchemyHomologationRepository,
    SQLAlchemySilhouetteCouverteRepository,
)
from app.infrastructure.database.repositories.project_repositories import (
    SQLAlchemyMaquetteRepository,
    SQLAlchemyProjetRepository,
)
from app.shared.enums import OrigineSuggestion, StatutHomologation
from app.shared.events import EventBus
from app.shared.exceptions import RessourceDejaExistante, RessourceIntrouvable


@dataclass(frozen=True)
class HomologationDTO:
    id: int
    maquette_id: int
    statut: StatutHomologation
    date_deadline: Optional[date]
    date_retour_reel: Optional[date]


@dataclass(frozen=True)
class DecisionCouvertureDTO:
    id: int
    homologation_id: int
    est_couverte: bool
    projet_couvrant_id: Optional[int]
    justification: str
    date_decision: Optional[datetime]


@dataclass(frozen=True)
class SilhouetteCouverteDTO:
    id: int
    homologation_id: int
    silhouette_id: int
    origine: OrigineSuggestion


@dataclass(frozen=True)
class SilhouetteSuggestionDTO:
    silhouette_id: int
    libelle: str


@dataclass(frozen=True)
class ProjetCouvrantDTO:
    projet_id: int
    reference: str
    homologation_id: int


@dataclass(frozen=True)
class CouvertureSuggestionDTO:
    homologation_id: int
    est_couverte: bool
    projet_couvrant_id: Optional[int]
    projet_couvrant_reference: Optional[str]
    homologation_couvrante_id: Optional[int]
    architecture_ee_id: int
    architecture_ee_label: str
    silhouettes_suggerees: list[SilhouetteSuggestionDTO]
    projets_couvrants: list[ProjetCouvrantDTO]
    justification: str


@dataclass(frozen=True)
class SilhouetteCouverteDetailDTO:
    id: int
    homologation_id: int
    silhouette_id: int
    silhouette_libelle: str
    origine: OrigineSuggestion


def _homologation_dto(item: Homologation) -> HomologationDTO:
    if item.id is None:
        raise ValueError("Une homologation persistee doit avoir un id")
    return HomologationDTO(
        id=item.id,
        maquette_id=item.maquette_id,
        statut=item.statut,
        date_deadline=item.date_deadline,
        date_retour_reel=item.date_retour_reel,
    )


def _decision_dto(item: DecisionCouverture) -> DecisionCouvertureDTO:
    if item.id is None:
        raise ValueError("Une decision persistee doit avoir un id")
    return DecisionCouvertureDTO(
        id=item.id,
        homologation_id=item.homologation_id,
        est_couverte=item.est_couverte,
        projet_couvrant_id=item.projet_couvrant_id,
        justification=item.justification,
        date_decision=item.date_decision,
    )


def _silhouette_dto(item: SilhouetteCouverte) -> SilhouetteCouverteDTO:
    if item.id is None:
        raise ValueError("Une silhouette couverte persistee doit avoir un id")
    return SilhouetteCouverteDTO(
        id=item.id,
        homologation_id=item.homologation_id,
        silhouette_id=item.silhouette_id,
        origine=item.origine,
    )


class HomologationService:
    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        self.session_factory = session_factory
        self.event_bus = event_bus

    def creer_homologation(self, maquette_id: int) -> HomologationDTO:
        with self.session_factory() as session:
            maquettes = SQLAlchemyMaquetteRepository(session)
            if maquettes.obtenir_par_id(maquette_id) is None:
                raise RessourceIntrouvable(f"Maquette introuvable: {maquette_id}")
            homologations = SQLAlchemyHomologationRepository(session)
            homologation = homologations.ajouter(Homologation(maquette_id=maquette_id))
            session.commit()
            return _homologation_dto(homologation)

    def lister_homologations(self, maquette_id: Optional[int] = None) -> list[HomologationDTO]:
        with self.session_factory() as session:
            homologations = SQLAlchemyHomologationRepository(session)
            return [_homologation_dto(item) for item in homologations.lister(maquette_id)]

    def changer_statut(
        self,
        homologation_id: int,
        statut: StatutHomologation,
    ) -> HomologationDTO:
        with self.session_factory() as session:
            homologations = SQLAlchemyHomologationRepository(session)
            homologation = homologations.obtenir_par_id(homologation_id)
            if homologation is None:
                raise RessourceIntrouvable(f"Homologation introuvable: {homologation_id}")
            homologation.changer_statut(statut)
            homologation = homologations.sauvegarder(homologation)
            session.commit()
            return _homologation_dto(homologation)

    def demarrer(
        self,
        homologation_id: int,
        utilisateur_id: Optional[int] = None,
    ) -> HomologationDTO:
        homologation = self.changer_statut(
            homologation_id,
            StatutHomologation.EN_COURS,
        )
        if self.event_bus is not None:
            self.event_bus.publish(
                HomologationDemarree(
                    homologation_id=homologation.id,
                    maquette_id=homologation.maquette_id,
                    utilisateur_id=utilisateur_id,
                )
            )
        return homologation

    def renseigner_dates(
        self,
        homologation_id: int,
        date_deadline: Optional[date] = None,
        date_retour_reel: Optional[date] = None,
    ) -> HomologationDTO:
        with self.session_factory() as session:
            homologations = SQLAlchemyHomologationRepository(session)
            homologation = homologations.obtenir_par_id(homologation_id)
            if homologation is None:
                raise RessourceIntrouvable(f"Homologation introuvable: {homologation_id}")
            ancienne_deadline = homologation.date_deadline
            homologation.renseigner_dates(
                date_deadline=date_deadline,
                date_retour_reel=date_retour_reel,
            )
            homologation = homologations.sauvegarder(homologation)
            session.commit()
            dto = _homologation_dto(homologation)

        if date_deadline is not None and date_deadline != ancienne_deadline:
            if self.event_bus is not None:
                self.event_bus.publish(
                    DateDeadlineChangee(
                        homologation_id=dto.id,
                        maquette_id=dto.maquette_id,
                        ancienne_deadline=ancienne_deadline,
                        nouvelle_deadline=date_deadline,
                    )
                )
                return dto
            from app.application.planning.services import PlanningService

            PlanningService(self.session_factory).reordonnancer_toutes_les_maquettes_actives()
        return dto

    def supprimer_homologation(self, homologation_id: int) -> None:
        with self.session_factory() as session:
            row = session.get(models.Homologation, homologation_id)
            if row is None:
                raise RessourceIntrouvable(f"Homologation introuvable: {homologation_id}")
            has_decision = session.scalar(
                select(models.DecisionCouverture.id)
                .where(models.DecisionCouverture.homologation_id == homologation_id)
                .limit(1)
            )
            has_silhouette = session.scalar(
                select(models.SilhouetteCouverte.id)
                .where(models.SilhouetteCouverte.homologation_id == homologation_id)
                .limit(1)
            )
            if has_decision is not None or has_silhouette is not None:
                raise RessourceDejaExistante(
                    "Impossible de supprimer une homologation deja tracee"
                )
            session.delete(row)
            session.commit()

    def detecter_retard(
        self,
        homologation: HomologationDTO | models.Homologation,
        aujourdhui: Optional[date] = None,
    ) -> bool:
        today = aujourdhui or date.today()
        return (
            homologation.date_deadline is not None
            and homologation.date_deadline < today
            and homologation.statut != StatutHomologation.TERMINEE
        )

    def detecter_retards(
        self,
        utilisateur_id: int,
        aujourdhui: Optional[date] = None,
    ) -> int:
        if self.event_bus is None:
            return 0
        today = aujourdhui or date.today()
        published = 0
        with self.session_factory() as session:
            homologations = list(
                session.scalars(
                    select(models.Homologation)
                    .where(models.Homologation.date_deadline.is_not(None))
                    .where(models.Homologation.date_deadline < today)
                    .where(models.Homologation.statut != StatutHomologation.TERMINEE)
                )
            )
            for homologation in homologations:
                maquette = session.get(models.Maquette, homologation.maquette_id)
                if maquette is None:
                    continue
                jours = (today - homologation.date_deadline).days
                message = (
                    f"Retard detecte sur la maquette #{maquette.id}: "
                    f"{jours} jour(s)"
                )
                cutoff = datetime.now() - timedelta(hours=24)
                duplicate = session.scalar(
                    select(models.Notification.id)
                    .where(models.Notification.utilisateur_id == utilisateur_id)
                    .where(models.Notification.message == message)
                    .where(models.Notification.date_envoi >= cutoff)
                    .limit(1)
                )
                if duplicate is not None:
                    continue
                self.event_bus.publish(
                    RetardDetecte(
                        maquette_id=maquette.id,
                        jours_de_retard=jours,
                        utilisateur_id=utilisateur_id,
                    )
                )
                published += 1
        return published

    def ajouter_decision_couverture(
        self,
        homologation_id: int,
        est_couverte: bool,
        justification: str,
        projet_couvrant_id: Optional[int] = None,
    ) -> DecisionCouvertureDTO:
        with self.session_factory() as session:
            homologations = SQLAlchemyHomologationRepository(session)
            if homologations.obtenir_par_id(homologation_id) is None:
                raise RessourceIntrouvable(f"Homologation introuvable: {homologation_id}")
            if projet_couvrant_id is not None:
                projets = SQLAlchemyProjetRepository(session)
                if projets.obtenir_par_id(projet_couvrant_id) is None:
                    raise RessourceIntrouvable(f"Projet couvrant introuvable: {projet_couvrant_id}")
            decisions = SQLAlchemyDecisionCouvertureRepository(session)
            decision = decisions.ajouter(
                DecisionCouverture(
                    homologation_id=homologation_id,
                    est_couverte=est_couverte,
                    projet_couvrant_id=projet_couvrant_id,
                    justification=justification,
                )
            )
            session.commit()
            return _decision_dto(decision)

    def verifier_couverture(self, homologation_id: int) -> CouvertureSuggestionDTO:
        with self.session_factory() as session:
            homologation = session.get(models.Homologation, homologation_id)
            if homologation is None:
                raise RessourceIntrouvable(f"Homologation introuvable: {homologation_id}")

            maquette = session.get(models.Maquette, homologation.maquette_id)
            if maquette is None:
                raise RessourceIntrouvable(f"Maquette introuvable: {homologation.maquette_id}")

            architecture = session.get(models.ArchitectureEE, maquette.architecture_ee_id)
            if architecture is None:
                raise RessourceIntrouvable(
                    f"Architecture EE introuvable: {maquette.architecture_ee_id}"
                )

            homologations_couvrantes = list(
                session.scalars(
                    select(models.Homologation)
                    .join(models.Maquette)
                    .where(models.Maquette.architecture_ee_id == maquette.architecture_ee_id)
                    .where(models.Maquette.id != maquette.id)
                    .where(models.Homologation.statut == StatutHomologation.TERMINEE)
                    .order_by(models.Homologation.id.desc())
                )
            )

            architecture_label = f"{architecture.reference} {architecture.version or ''}".strip()
            if not homologations_couvrantes:
                return CouvertureSuggestionDTO(
                    homologation_id=homologation.id,
                    est_couverte=False,
                    projet_couvrant_id=None,
                    projet_couvrant_reference=None,
                    homologation_couvrante_id=None,
                    architecture_ee_id=architecture.id,
                    architecture_ee_label=architecture_label,
                    silhouettes_suggerees=[],
                    projets_couvrants=[],
                    justification=(
                        "Aucune homologation terminee avec la meme ArchitectureEE."
                    ),
                )

            homologation_couvrante = homologations_couvrantes[0]
            maquette_couvrante = session.get(
                models.Maquette,
                homologation_couvrante.maquette_id,
            )
            if maquette_couvrante is None:
                raise RessourceIntrouvable(
                    f"Maquette couvrante introuvable: {homologation_couvrante.maquette_id}"
                )

            silhouettes = self._silhouettes_suggerees(session, homologation_couvrante)
            projet_couvrant = session.get(models.Projet, maquette_couvrante.projet_id)
            if projet_couvrant is None:
                raise RessourceIntrouvable(
                    f"Projet couvrant introuvable: {maquette_couvrante.projet_id}"
                )
            projets_couvrants = self._projets_couvrants(session, homologations_couvrantes)

            return CouvertureSuggestionDTO(
                homologation_id=homologation.id,
                est_couverte=True,
                projet_couvrant_id=projet_couvrant.id,
                projet_couvrant_reference=projet_couvrant.reference,
                homologation_couvrante_id=homologation_couvrante.id,
                architecture_ee_id=architecture.id,
                architecture_ee_label=architecture_label,
                silhouettes_suggerees=silhouettes,
                projets_couvrants=projets_couvrants,
                justification=(
                    "Suggestion automatique: homologation terminee avec la meme "
                    f"ArchitectureEE ({architecture_label})."
                ),
            )

    def enregistrer_decision_couverture(
        self,
        homologation_id: int,
        est_couverte: bool,
        justification: str,
        utilisateur_id: int,
        projet_couvrant_id: Optional[int] = None,
    ) -> DecisionCouvertureDTO:
        with self.session_factory() as session:
            homologations = SQLAlchemyHomologationRepository(session)
            if homologations.obtenir_par_id(homologation_id) is None:
                raise RessourceIntrouvable(f"Homologation introuvable: {homologation_id}")
            if session.get(models.Utilisateur, utilisateur_id) is None:
                raise RessourceIntrouvable(f"Utilisateur introuvable: {utilisateur_id}")
            if projet_couvrant_id is not None:
                projets = SQLAlchemyProjetRepository(session)
                if projets.obtenir_par_id(projet_couvrant_id) is None:
                    raise RessourceIntrouvable(
                        f"Projet couvrant introuvable: {projet_couvrant_id}"
                    )

            decisions = SQLAlchemyDecisionCouvertureRepository(session)
            decision = decisions.ajouter(
                DecisionCouverture(
                    homologation_id=homologation_id,
                    est_couverte=est_couverte,
                    projet_couvrant_id=projet_couvrant_id,
                    justification=justification,
                )
            )
            if decision.id is None:
                raise ValueError("Une decision persistee doit avoir un id")

            session.add(
                models.AuditLog(
                    utilisateur_id=utilisateur_id,
                    action="CREATE_DECISION_COUVERTURE",
                    entity_type="DecisionCouverture",
                    entity_id=decision.id,
                    details={
                        "homologation_id": homologation_id,
                        "est_couverte": est_couverte,
                        "projet_couvrant_id": projet_couvrant_id,
                    },
                )
            )
            session.commit()
            dto = _decision_dto(decision)

        if self.event_bus is not None:
            self.event_bus.publish(
                DecisionCouvertureCreee(
                    decision_id=dto.id,
                    homologation_id=dto.homologation_id,
                    est_couverte=dto.est_couverte,
                    utilisateur_id=utilisateur_id,
                )
            )
        return dto

    def ajouter_silhouette_couverte(
        self,
        homologation_id: int,
        silhouette_id: int,
        origine: OrigineSuggestion = OrigineSuggestion.VALIDATION_INGENIEUR,
    ) -> SilhouetteCouverteDTO:
        with self.session_factory() as session:
            homologations = SQLAlchemyHomologationRepository(session)
            if homologations.obtenir_par_id(homologation_id) is None:
                raise RessourceIntrouvable(f"Homologation introuvable: {homologation_id}")
            silhouettes = SQLAlchemySilhouetteCouverteRepository(session)
            silhouette = silhouettes.ajouter(
                SilhouetteCouverte(
                    homologation_id=homologation_id,
                    silhouette_id=silhouette_id,
                    origine=origine,
                )
            )
            session.commit()
            return _silhouette_dto(silhouette)

    def lister_silhouettes_couvertes(
        self,
        homologation_id: int,
    ) -> list[SilhouetteCouverteDetailDTO]:
        with self.session_factory() as session:
            if session.get(models.Homologation, homologation_id) is None:
                raise RessourceIntrouvable(f"Homologation introuvable: {homologation_id}")

            statement = (
                select(models.SilhouetteCouverte, models.Silhouette)
                .join(models.Silhouette)
                .where(models.SilhouetteCouverte.homologation_id == homologation_id)
                .order_by(models.Silhouette.libelle)
            )
            return [
                SilhouetteCouverteDetailDTO(
                    id=row.id,
                    homologation_id=row.homologation_id,
                    silhouette_id=row.silhouette_id,
                    silhouette_libelle=silhouette.libelle,
                    origine=row.origine,
                )
                for row, silhouette in session.execute(statement)
            ]

    def ajouter_silhouette_couverte_manuelle(
        self,
        homologation_id: int,
        silhouette_id: int,
    ) -> SilhouetteCouverteDTO:
        try:
            return self.ajouter_silhouette_couverte(
                homologation_id=homologation_id,
                silhouette_id=silhouette_id,
                origine=OrigineSuggestion.VALIDATION_INGENIEUR,
            )
        except IntegrityError as exc:
            raise RessourceDejaExistante(
                "Cette silhouette est deja couverte par cette homologation"
            ) from exc

    def retirer_silhouette_couverte(self, silhouette_couverte_id: int) -> None:
        with self.session_factory() as session:
            silhouettes = SQLAlchemySilhouetteCouverteRepository(session)
            try:
                silhouettes.retirer(silhouette_couverte_id)
            except ValueError as exc:
                raise RessourceIntrouvable(
                    f"Silhouette couverte introuvable: {silhouette_couverte_id}"
                ) from exc
            session.commit()

    def _silhouettes_suggerees(
        self,
        session: Session,
        homologation_couvrante: models.Homologation,
    ) -> list[SilhouetteSuggestionDTO]:
        statement = (
            select(models.Silhouette)
            .join(
                models.SilhouetteCouverte,
                models.SilhouetteCouverte.silhouette_id == models.Silhouette.id,
            )
            .where(models.SilhouetteCouverte.homologation_id == homologation_couvrante.id)
            .order_by(models.Silhouette.libelle)
        )
        silhouettes = [
            SilhouetteSuggestionDTO(silhouette_id=row.id, libelle=row.libelle)
            for row in session.scalars(statement)
        ]
        if silhouettes:
            return silhouettes

        maquette_couvrante = session.get(models.Maquette, homologation_couvrante.maquette_id)
        if maquette_couvrante is None:
            return []
        silhouette = session.get(models.Silhouette, maquette_couvrante.silhouette_id)
        if silhouette is None:
            return []
        return [SilhouetteSuggestionDTO(silhouette_id=silhouette.id, libelle=silhouette.libelle)]

    def _projets_couvrants(
        self,
        session: Session,
        homologations_couvrantes: list[models.Homologation],
    ) -> list[ProjetCouvrantDTO]:
        projets: list[ProjetCouvrantDTO] = []
        seen: set[int] = set()
        for homologation in homologations_couvrantes:
            maquette = session.get(models.Maquette, homologation.maquette_id)
            if maquette is None or maquette.projet_id in seen:
                continue
            projet = session.get(models.Projet, maquette.projet_id)
            if projet is None:
                continue
            seen.add(projet.id)
            projets.append(
                ProjetCouvrantDTO(
                    projet_id=projet.id,
                    reference=projet.reference,
                    homologation_id=homologation.id,
                )
            )
        return projets
