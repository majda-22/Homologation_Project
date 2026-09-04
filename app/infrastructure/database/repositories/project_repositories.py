"""Repositories SQLAlchemy pour le bounded context Project."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.project.entities import Maquette, Projet
from app.domain.project.repositories import MaquetteRepository, ProjetRepository
from app.infrastructure.database import models
from app.shared.component_codes import TYPE_COMPOSANT_CODES_OFFICIELS
from app.shared.enums import StatutProjet


@dataclass(frozen=True)
class ReferentielItem:
    id: int
    label: str


def _to_domain_projet(row: models.Projet) -> Projet:
    return Projet(
        id=row.id,
        reference=row.reference,
        date_creation=row.date_creation,
        statut=row.statut,
        created_by_id=row.created_by_id,
    )


def _to_domain_maquette(row: models.Maquette) -> Maquette:
    return Maquette(
        id=row.id,
        projet_id=row.projet_id,
        silhouette_id=row.silhouette_id,
        architecture_ee_id=row.architecture_ee_id,
        fournisseur_id=row.fournisseur_id,
        composant_modifie=row.composant_modifie,
        type_homologation=row.type_homologation,
        modele=row.modele,
        date_creation=row.date_creation,
    )


class SQLAlchemyProjetRepository(ProjetRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def ajouter(self, projet: Projet) -> Projet:
        row = models.Projet(
            reference=projet.reference,
            date_creation=projet.date_creation,
            statut=projet.statut,
            created_by_id=projet.created_by_id,
        )
        self.session.add(row)
        self.session.flush()
        return _to_domain_projet(row)

    def obtenir_par_id(self, projet_id: int) -> Optional[Projet]:
        row = self.session.get(models.Projet, projet_id)
        return _to_domain_projet(row) if row else None

    def obtenir_par_reference(self, reference: str) -> Optional[Projet]:
        row = self.session.scalar(
            select(models.Projet).where(models.Projet.reference == reference)
        )
        return _to_domain_projet(row) if row else None

    def lister(self, statut: Optional[str] = None) -> list[Projet]:
        statement = select(models.Projet).order_by(models.Projet.date_creation.desc())
        if statut:
            statement = statement.where(models.Projet.statut == StatutProjet(statut))
        return [_to_domain_projet(row) for row in self.session.scalars(statement)]

    def mettre_a_jour_statut(self, projet: Projet) -> Projet:
        row = self.session.get(models.Projet, projet.id)
        if row is None:
            raise ValueError(f"Projet introuvable: {projet.id}")
        row.statut = projet.statut
        self.session.flush()
        return _to_domain_projet(row)


class SQLAlchemyMaquetteRepository(MaquetteRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def ajouter(self, maquette: Maquette) -> Maquette:
        row = models.Maquette(
            projet_id=maquette.projet_id,
            silhouette_id=maquette.silhouette_id,
            architecture_ee_id=maquette.architecture_ee_id,
            fournisseur_id=maquette.fournisseur_id,
            composant_modifie=maquette.composant_modifie,
            type_homologation=maquette.type_homologation,
            modele=maquette.modele,
            date_creation=maquette.date_creation,
        )
        self.session.add(row)
        self.session.flush()
        return _to_domain_maquette(row)

    def obtenir_par_id(self, maquette_id: int) -> Optional[Maquette]:
        row = self.session.get(models.Maquette, maquette_id)
        return _to_domain_maquette(row) if row else None

    def rechercher(
        self,
        projet_id: Optional[int] = None,
        silhouette_id: Optional[int] = None,
        architecture_ee_id: Optional[int] = None,
        fournisseur_id: Optional[int] = None,
        type_homologation: Optional[str] = None,
    ) -> list[Maquette]:
        statement = select(models.Maquette).order_by(models.Maquette.date_creation.desc())
        if projet_id is not None:
            statement = statement.where(models.Maquette.projet_id == projet_id)
        if silhouette_id is not None:
            statement = statement.where(models.Maquette.silhouette_id == silhouette_id)
        if architecture_ee_id is not None:
            statement = statement.where(models.Maquette.architecture_ee_id == architecture_ee_id)
        if fournisseur_id is not None:
            statement = statement.where(models.Maquette.fournisseur_id == fournisseur_id)
        if type_homologation is not None:
            statement = statement.where(models.Maquette.type_homologation == type_homologation)
        return [_to_domain_maquette(row) for row in self.session.scalars(statement)]

    def lister_par_projet(self, projet_id: int) -> list[Maquette]:
        statement = (
            select(models.Maquette)
            .where(models.Maquette.projet_id == projet_id)
            .order_by(models.Maquette.date_creation.desc())
        )
        return [_to_domain_maquette(row) for row in self.session.scalars(statement)]


class SQLAlchemyReferentielRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def lister_silhouettes(self) -> list[ReferentielItem]:
        statement = select(models.Silhouette).order_by(models.Silhouette.libelle)
        return [
            ReferentielItem(id=row.id, label=row.libelle)
            for row in self.session.scalars(statement)
        ]

    def lister_architectures(self) -> list[ReferentielItem]:
        statement = select(models.ArchitectureEE).order_by(models.ArchitectureEE.reference)
        return [
            ReferentielItem(id=row.id, label=f"{row.reference} {row.version or ''}".strip())
            for row in self.session.scalars(statement)
        ]

    def lister_fournisseurs(self) -> list[ReferentielItem]:
        statement = select(models.Fournisseur).order_by(models.Fournisseur.nom)
        return [
            ReferentielItem(id=row.id, label=row.nom)
            for row in self.session.scalars(statement)
        ]

    def lister_types_composants(self) -> list[ReferentielItem]:
        statement = select(models.TypeComposant).where(
            models.TypeComposant.code.in_(TYPE_COMPOSANT_CODES_OFFICIELS)
        )
        rows_by_code = {row.code: row for row in self.session.scalars(statement)}
        return [
            ReferentielItem(id=rows_by_code[code].id, label=code)
            for code in TYPE_COMPOSANT_CODES_OFFICIELS
            if code in rows_by_code
        ]
