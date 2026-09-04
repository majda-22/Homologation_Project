"""Services applicatifs pour les projets et maquettes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.homologation.events import StatutProjetChange
from app.domain.project.entities import Maquette, Projet
from app.application.planning.services import PlanningService
from app.infrastructure.database import models
from app.infrastructure.database.database import SessionLocal
from app.infrastructure.ml.predict import predire_residu_dll_par_maquette_id
from app.infrastructure.database.repositories.project_repositories import (
    ReferentielItem,
    SQLAlchemyMaquetteRepository,
    SQLAlchemyProjetRepository,
    SQLAlchemyReferentielRepository,
)
from app.infrastructure.ml.similarity import trouver_maquette_similaire
from app.infrastructure.reporting.pdf_generator import CDCData, CDCLigneData, generer_cdc_pdf
from app.shared.enums import StatutProjet, TypeHomologation
from app.shared.enums import OrigineSuggestion
from app.shared.events import EventBus
from app.shared.exceptions import RessourceDejaExistante, RessourceIntrouvable
from app.shared.subject_parser import parser_sujets


@dataclass(frozen=True)
class ProjetDTO:
    id: int
    reference: str
    date_creation: date
    statut: StatutProjet
    created_by_id: int


@dataclass(frozen=True)
class MaquetteDTO:
    id: int
    projet_id: int
    silhouette_id: int
    architecture_ee_id: int
    fournisseur_id: int
    composant_modifie: str
    type_homologation: TypeHomologation
    date_creation: date
    modele: Optional[str]


@dataclass(frozen=True)
class ReferentielsProjetDTO:
    silhouettes: list[ReferentielItem]
    architectures: list[ReferentielItem]
    fournisseurs: list[ReferentielItem]
    types_homologation: list[TypeHomologation]
    types_composants: list[ReferentielItem]


@dataclass(frozen=True)
class LigneCDCDTO:
    id: int
    maquette_id: int
    type_composant_id: int
    type_composant_code: str
    quantite_hw: int
    origine: OrigineSuggestion
    suggestion_source: Optional[str] = None


@dataclass(frozen=True)
class SuggestionComposantDTO:
    type_composant_id: int
    type_composant_code: str
    source_type: str
    source_valeur: str


def _projet_dto(projet: Projet) -> ProjetDTO:
    if projet.id is None:
        raise ValueError("Un projet persiste doit avoir un id")
    return ProjetDTO(
        id=projet.id,
        reference=projet.reference,
        date_creation=projet.date_creation,
        statut=projet.statut,
        created_by_id=projet.created_by_id,
    )


def _maquette_dto(maquette: Maquette) -> MaquetteDTO:
    if maquette.id is None:
        raise ValueError("Une maquette persistee doit avoir un id")
    return MaquetteDTO(
        id=maquette.id,
        projet_id=maquette.projet_id,
        silhouette_id=maquette.silhouette_id,
        architecture_ee_id=maquette.architecture_ee_id,
        fournisseur_id=maquette.fournisseur_id,
        composant_modifie=maquette.composant_modifie,
        type_homologation=maquette.type_homologation,
        modele=maquette.modele,
        date_creation=maquette.date_creation,
    )


class ProjectService:
    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        event_bus: Optional[EventBus] = None,
    ) -> None:
        self.session_factory = session_factory
        self.event_bus = event_bus

    def creer_projet(
        self,
        reference: str,
        created_by_id: int,
        date_creation: Optional[date] = None,
    ) -> ProjetDTO:
        reference = reference.strip().upper()
        if not reference:
            raise ValueError("La reference projet est obligatoire")

        with self.session_factory() as session:
            projets = SQLAlchemyProjetRepository(session)
            if projets.obtenir_par_reference(reference) is not None:
                raise RessourceDejaExistante(
                    f"Le projet {reference} existe deja"
                )

            projet = Projet(
                reference=reference,
                date_creation=date_creation or date.today(),
                created_by_id=created_by_id,
            )

            try:
                nouveau = projets.ajouter(projet)
                session.commit()
                return _projet_dto(nouveau)
            except IntegrityError as exc:
                session.rollback()
                raise RessourceDejaExistante(
                    f"Impossible de creer le projet {reference}"
                ) from exc

    def lister_projets(self, statut: Optional[StatutProjet] = None) -> list[ProjetDTO]:
        with self.session_factory() as session:
            projets = SQLAlchemyProjetRepository(session)
            statut_value = statut.value if statut else None
            return [_projet_dto(projet) for projet in projets.lister(statut_value)]

    def changer_statut_projet(
        self,
        projet_id: int,
        nouveau_statut: StatutProjet,
        utilisateur_id: Optional[int] = None,
    ) -> ProjetDTO:
        with self.session_factory() as session:
            projets = SQLAlchemyProjetRepository(session)
            projet = projets.obtenir_par_id(projet_id)
            if projet is None:
                raise RessourceIntrouvable(f"Projet introuvable: {projet_id}")
            ancien_statut = projet.statut
            projet.changer_statut(nouveau_statut)
            projet = projets.mettre_a_jour_statut(projet)
            session.commit()
            dto = _projet_dto(projet)

        if self.event_bus is not None:
            self.event_bus.publish(
                StatutProjetChange(
                    projet_id=projet_id,
                    ancien_statut=ancien_statut,
                    nouveau_statut=nouveau_statut,
                    utilisateur_id=utilisateur_id,
                )
            )
        return dto

    def modifier_projet(
        self,
        projet_id: int,
        reference: Optional[str] = None,
        statut: Optional[StatutProjet] = None,
        utilisateur_id: Optional[int] = None,
    ) -> ProjetDTO:
        ancien_statut = None
        with self.session_factory() as session:
            row = session.get(models.Projet, projet_id)
            if row is None:
                raise RessourceIntrouvable(f"Projet introuvable: {projet_id}")
            if reference is not None:
                nouvelle_reference = reference.strip().upper()
                if not nouvelle_reference:
                    raise ValueError("La reference projet est obligatoire")
                duplicate = session.scalar(
                    select(models.Projet).where(
                        models.Projet.reference == nouvelle_reference,
                        models.Projet.id != projet_id,
                    )
                )
                if duplicate is not None:
                    raise RessourceDejaExistante(
                        f"Le projet {nouvelle_reference} existe deja"
                    )
                row.reference = nouvelle_reference
            if statut is not None and statut != row.statut:
                ancien_statut = row.statut
                row.statut = statut
            session.commit()
            dto = ProjetDTO(
                id=row.id,
                reference=row.reference,
                date_creation=row.date_creation,
                statut=row.statut,
                created_by_id=row.created_by_id,
            )

        if ancien_statut is not None and self.event_bus is not None:
            self.event_bus.publish(
                StatutProjetChange(
                    projet_id=projet_id,
                    ancien_statut=ancien_statut,
                    nouveau_statut=dto.statut,
                    utilisateur_id=utilisateur_id,
                )
            )
        return dto

    def supprimer_projet(self, projet_id: int) -> None:
        with self.session_factory() as session:
            row = session.get(models.Projet, projet_id)
            if row is None:
                raise RessourceIntrouvable(f"Projet introuvable: {projet_id}")
            has_maquettes = session.scalar(
                select(models.Maquette.id)
                .where(models.Maquette.projet_id == projet_id)
                .limit(1)
            )
            if has_maquettes is not None:
                raise RessourceDejaExistante(
                    "Impossible de supprimer un projet qui possede des maquettes"
                )
            session.delete(row)
            session.commit()

    def creer_maquette(
        self,
        projet_id: int,
        silhouette_id: int,
        architecture_ee_id: int,
        fournisseur_id: int,
        composant_modifie: str,
        type_homologation: TypeHomologation,
        modele: Optional[str] = None,
        sujet_codes: Optional[list[str]] = None,
        date_creation: Optional[date] = None,
        generer_planning: bool = False,
        generer_cdc_auto: bool = False,
    ) -> MaquetteDTO:
        with self.session_factory() as session:
            projets = SQLAlchemyProjetRepository(session)
            if projets.obtenir_par_id(projet_id) is None:
                raise RessourceIntrouvable(f"Projet introuvable: {projet_id}")

            maquettes = SQLAlchemyMaquetteRepository(session)
            maquette = Maquette(
                projet_id=projet_id,
                silhouette_id=silhouette_id,
                architecture_ee_id=architecture_ee_id,
                fournisseur_id=fournisseur_id,
                composant_modifie=composant_modifie,
                type_homologation=type_homologation,
                modele=modele.strip() if modele else None,
                date_creation=date_creation or date.today(),
            )

            try:
                maquettes_existantes = maquettes.rechercher()
                nouvelle = maquettes.ajouter(maquette)
                self._associer_sujets(
                    session,
                    nouvelle.id,
                    sujet_codes or parser_sujets(f"{composant_modifie} {modele or ''}"),
                )
                session.flush()
                for suggestion in self._suggestions_composition(session, nouvelle.id):
                    self._upsert_ligne_cdc_suggeree(
                        session,
                        cible_maquette_id=nouvelle.id,
                        type_composant_id=suggestion.type_composant_id,
                        quantite_hw=1,
                        suggestion_source=self._source_label(suggestion),
                    )
                session.flush()
                maquette_similaire = trouver_maquette_similaire(
                    nouvelle,
                    maquettes_existantes,
                )
                if maquette_similaire is not None:
                    self._copier_lignes_cdc_suggerees(
                        session,
                        source_maquette_id=maquette_similaire.id,
                        cible_maquette_id=nouvelle.id,
                    )
                session.commit()
                dto = _maquette_dto(nouvelle)
            except IntegrityError:
                session.rollback()
                raise
        if generer_planning:
            residu = predire_residu_dll_par_maquette_id(
                dto.id,
                session_factory=self.session_factory,
            )
            PlanningService(self.session_factory).generer_planning_theorique_maquette(
                maquette_id=dto.id,
                date_livraison_cdc=dto.date_creation,
                residu_predit=round(residu.predicted_residual),
            )
        if generer_cdc_auto:
            self.generer_cdc_automatique_si_possible(dto.id)
        return dto

    def lister_maquettes(
        self,
        projet_id: Optional[int] = None,
        silhouette_id: Optional[int] = None,
        architecture_ee_id: Optional[int] = None,
        fournisseur_id: Optional[int] = None,
        type_homologation: Optional[TypeHomologation] = None,
    ) -> list[MaquetteDTO]:
        with self.session_factory() as session:
            maquettes = SQLAlchemyMaquetteRepository(session)
            result = maquettes.rechercher(
                projet_id=projet_id,
                silhouette_id=silhouette_id,
                architecture_ee_id=architecture_ee_id,
                fournisseur_id=fournisseur_id,
                type_homologation=type_homologation.value if type_homologation else None,
            )
            return [_maquette_dto(maquette) for maquette in result]

    def charger_referentiels(self) -> ReferentielsProjetDTO:
        with self.session_factory() as session:
            referentiels = SQLAlchemyReferentielRepository(session)
            return ReferentielsProjetDTO(
                silhouettes=referentiels.lister_silhouettes(),
                architectures=referentiels.lister_architectures(),
                fournisseurs=referentiels.lister_fournisseurs(),
                types_homologation=list(TypeHomologation),
                types_composants=referentiels.lister_types_composants(),
            )

    def lister_lignes_cdc(self, maquette_id: int) -> list[LigneCDCDTO]:
        with self.session_factory() as session:
            if session.get(models.Maquette, maquette_id) is None:
                raise RessourceIntrouvable(f"Maquette introuvable: {maquette_id}")
            return self._lignes_cdc_dto(session, maquette_id)

    def ajouter_ligne_cdc(
        self,
        maquette_id: int,
        type_composant_id: int,
        quantite_hw: int,
    ) -> LigneCDCDTO:
        with self.session_factory() as session:
            if session.get(models.Maquette, maquette_id) is None:
                raise RessourceIntrouvable(f"Maquette introuvable: {maquette_id}")
            if session.get(models.TypeComposant, type_composant_id) is None:
                raise RessourceIntrouvable(
                    f"Type composant introuvable: {type_composant_id}"
                )
            ligne = models.LigneCDC(
                maquette_id=maquette_id,
                type_composant_id=type_composant_id,
                quantite_hw=quantite_hw,
                origine=OrigineSuggestion.VALIDATION_INGENIEUR,
            )
            session.add(ligne)
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise RessourceDejaExistante(
                    "Cette ligne CDC existe deja pour cette maquette"
                ) from exc
            return self._ligne_cdc_dto(session, ligne)

    def modifier_ligne_cdc(
        self,
        ligne_cdc_id: int,
        quantite_hw: int,
    ) -> LigneCDCDTO:
        with self.session_factory() as session:
            ligne = session.get(models.LigneCDC, ligne_cdc_id)
            if ligne is None:
                raise RessourceIntrouvable(f"Ligne CDC introuvable: {ligne_cdc_id}")
            ligne.quantite_hw = quantite_hw
            ligne.origine = OrigineSuggestion.VALIDATION_INGENIEUR
            session.commit()
            return self._ligne_cdc_dto(session, ligne)

    def supprimer_ligne_cdc(self, ligne_cdc_id: int) -> None:
        with self.session_factory() as session:
            ligne = session.get(models.LigneCDC, ligne_cdc_id)
            if ligne is None:
                raise RessourceIntrouvable(f"Ligne CDC introuvable: {ligne_cdc_id}")
            session.delete(ligne)
            session.commit()

    def generer_cdc(self, maquette_id: int) -> Path:
        with self.session_factory() as session:
            maquette = session.get(models.Maquette, maquette_id)
            if maquette is None:
                raise RessourceIntrouvable(f"Maquette introuvable: {maquette_id}")
            projet = session.get(models.Projet, maquette.projet_id)
            silhouette = session.get(models.Silhouette, maquette.silhouette_id)
            if projet is None or silhouette is None:
                raise RessourceIntrouvable("Donnees CDC incompletes")
            lignes = self._lignes_cdc_dto(session, maquette_id)

        data = CDCData(
            projet_reference=projet.reference,
            modele=maquette.modele or "-",
            silhouette=silhouette.libelle,
            lignes=[
                CDCLigneData(
                    type_composant=ligne.type_composant_code,
                    quantite_hw=ligne.quantite_hw,
                )
                for ligne in lignes
            ],
        )
        return generer_cdc_pdf(data)

    def generer_cdc_automatique_si_possible(self, maquette_id: int) -> Optional[Path]:
        lignes = self.lister_lignes_cdc(maquette_id)
        if not lignes:
            return None
        return self.generer_cdc(maquette_id)

    def suggerer_composants_par_composition(
        self,
        maquette_id: int,
    ) -> list[SuggestionComposantDTO]:
        with self.session_factory() as session:
            if session.get(models.Maquette, maquette_id) is None:
                raise RessourceIntrouvable(f"Maquette introuvable: {maquette_id}")
            return self._suggestions_composition(session, maquette_id)

    def _associer_sujets(
        self,
        session: Session,
        maquette_id: int | None,
        sujet_codes: list[str],
    ) -> None:
        if maquette_id is None:
            return
        for code in sujet_codes:
            sujet = session.scalar(
                select(models.Sujet).where(models.Sujet.code == code)
            )
            if sujet is None:
                sujet = models.Sujet(code=code)
                session.add(sujet)
                session.flush()
            existing = session.scalar(
                select(models.MaquetteSujet).where(
                    models.MaquetteSujet.maquette_id == maquette_id,
                    models.MaquetteSujet.sujet_id == sujet.id,
                )
            )
            if existing is None:
                session.add(
                    models.MaquetteSujet(maquette_id=maquette_id, sujet_id=sujet.id)
                )

    def _suggestions_composition(
        self,
        session: Session,
        maquette_id: int,
    ) -> list[SuggestionComposantDTO]:
        maquette = session.get(models.Maquette, maquette_id)
        if maquette is None:
            raise RessourceIntrouvable(f"Maquette introuvable: {maquette_id}")
        projet = session.get(models.Projet, maquette.projet_id)
        criteres: list[tuple[str, str]] = [("commune", "toujours")]
        if maquette.modele:
            for modele in self._extraire_motorisations(maquette.modele):
                criteres.append(("motorisation", modele))
        if projet is not None:
            for programme in self._extraire_programmes(projet.reference):
                criteres.append(("programme", programme))
        sujet_codes = [
            code
            for code in session.scalars(
                select(models.Sujet.code)
                .join(models.MaquetteSujet)
                .where(models.MaquetteSujet.maquette_id == maquette_id)
                .order_by(models.Sujet.code)
            )
        ]
        for sujet_code in sujet_codes:
            criteres.append(("sujet", sujet_code))

        seen_criteres = []
        for critere in criteres:
            if critere not in seen_criteres:
                seen_criteres.append(critere)

        suggestions: list[SuggestionComposantDTO] = []
        for source_type, source_valeur in seen_criteres:
            rows = session.execute(
                select(models.SuggestionComposantSource, models.TypeComposant)
                .join(models.TypeComposant)
                .where(models.SuggestionComposantSource.source_type == source_type)
                .where(models.SuggestionComposantSource.source_valeur == source_valeur)
                .order_by(models.TypeComposant.code)
            )
            for source, type_composant in rows:
                suggestions.append(
                    SuggestionComposantDTO(
                        type_composant_id=source.type_composant_id,
                        type_composant_code=type_composant.code,
                        source_type=source.source_type,
                        source_valeur=source.source_valeur,
                    ),
                )
        return sorted(
            suggestions,
            key=lambda item: (
                self._component_sort_key(item.type_composant_code),
                item.source_type,
                item.source_valeur,
            ),
        )

    def _copier_lignes_cdc_suggerees(
        self,
        session: Session,
        source_maquette_id: int | None,
        cible_maquette_id: int | None,
    ) -> None:
        if source_maquette_id is None or cible_maquette_id is None:
            return
        lignes_source = session.scalars(
            select(models.LigneCDC).where(models.LigneCDC.maquette_id == source_maquette_id)
        )
        for ligne in lignes_source:
            self._upsert_ligne_cdc_suggeree(
                session,
                cible_maquette_id=cible_maquette_id,
                type_composant_id=ligne.type_composant_id,
                quantite_hw=ligne.quantite_hw,
                suggestion_source="Historique similaire",
            )

    def _upsert_ligne_cdc_suggeree(
        self,
        session: Session,
        cible_maquette_id: int | None,
        type_composant_id: int,
        quantite_hw: int,
        suggestion_source: str,
    ) -> None:
        if cible_maquette_id is None:
            return
        existing = session.scalar(
            select(models.LigneCDC).where(
                models.LigneCDC.maquette_id == cible_maquette_id,
                models.LigneCDC.type_composant_id == type_composant_id,
            )
        )
        if existing is None:
            session.add(
                models.LigneCDC(
                    maquette_id=cible_maquette_id,
                    type_composant_id=type_composant_id,
                    quantite_hw=quantite_hw,
                    origine=OrigineSuggestion.SUGGESTION_AUTO,
                    suggestion_source=suggestion_source,
                )
            )
            return
        if existing.origine == OrigineSuggestion.SUGGESTION_AUTO:
            existing.quantite_hw = max(existing.quantite_hw, quantite_hw)
            sources = [
                source.strip()
                for source in (existing.suggestion_source or "").split(",")
                if source.strip()
            ]
            if suggestion_source not in sources:
                sources.append(suggestion_source)
                existing.suggestion_source = ", ".join(sources)

    @staticmethod
    def _source_label(suggestion: SuggestionComposantDTO) -> str:
        labels = {
            "motorisation": "Motorisation",
            "programme": "Programme",
            "sujet": "Sujet",
            "commune": "Piece commune",
        }
        return labels.get(suggestion.source_type, suggestion.source_type)

    @staticmethod
    def _extraire_motorisations(value: str) -> list[str]:
        import re

        return list(dict.fromkeys(re.findall(r"\bM\d+\b", value.upper())))

    @staticmethod
    def _extraire_programmes(value: str) -> list[str]:
        import re

        return list(dict.fromkeys(re.findall(r"\b(?:X\d+|SMC|D\d+|Y\d+)\b", value.upper())))

    @staticmethod
    def _component_sort_key(code: str) -> tuple[str, int]:
        import re

        match = re.fullmatch(r"([A-Z]+)(\d+)", code)
        if not match:
            return code, 0
        return match.group(1), int(match.group(2))

    def _lignes_cdc_dto(self, session: Session, maquette_id: int) -> list[LigneCDCDTO]:
        statement = (
            select(models.LigneCDC, models.TypeComposant)
            .join(models.TypeComposant)
            .where(models.LigneCDC.maquette_id == maquette_id)
            .order_by(models.TypeComposant.code)
        )
        return [
            LigneCDCDTO(
                id=ligne.id,
                maquette_id=ligne.maquette_id,
                type_composant_id=ligne.type_composant_id,
                type_composant_code=type_composant.code,
                quantite_hw=ligne.quantite_hw,
                origine=ligne.origine,
                suggestion_source=ligne.suggestion_source,
            )
            for ligne, type_composant in session.execute(statement)
        ]

    def _ligne_cdc_dto(self, session: Session, ligne: models.LigneCDC) -> LigneCDCDTO:
        type_composant = session.get(models.TypeComposant, ligne.type_composant_id)
        if type_composant is None:
            raise RessourceIntrouvable(
                f"Type composant introuvable: {ligne.type_composant_id}"
            )
        return LigneCDCDTO(
            id=ligne.id,
            maquette_id=ligne.maquette_id,
            type_composant_id=ligne.type_composant_id,
            type_composant_code=type_composant.code,
            quantite_hw=ligne.quantite_hw,
            origine=ligne.origine,
            suggestion_source=ligne.suggestion_source,
        )
