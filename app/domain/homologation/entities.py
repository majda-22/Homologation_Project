"""Entites du bounded context Homologation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

from app.shared.enums import OrigineSuggestion, StatutHomologation
from app.shared.exceptions import RegleMetierViolee


@dataclass
class Homologation:
    maquette_id: int
    id: Optional[int] = None
    statut: StatutHomologation = StatutHomologation.EN_ATTENTE
    date_livraison_cdc: Optional[date] = None
    date_cmde: Optional[date] = None
    date_montage: Optional[date] = None
    date_validation_fonctionnelle: Optional[date] = None
    date_deadline_buffer: Optional[date] = None
    date_deadline: Optional[date] = None
    date_retour_reel: Optional[date] = None

    def changer_statut(self, nouveau_statut: StatutHomologation) -> None:
        transitions_interdites = {
            (StatutHomologation.TERMINEE, StatutHomologation.EN_ATTENTE),
            (StatutHomologation.TERMINEE, StatutHomologation.EN_COURS),
        }
        if (self.statut, nouveau_statut) in transitions_interdites:
            raise RegleMetierViolee(
                f"Transition homologation invalide : {self.statut} -> {nouveau_statut}"
            )
        self.statut = nouveau_statut

    def renseigner_dates(
        self,
        date_livraison_cdc: Optional[date] = None,
        date_cmde: Optional[date] = None,
        date_montage: Optional[date] = None,
        date_validation_fonctionnelle: Optional[date] = None,
        date_deadline_buffer: Optional[date] = None,
        date_deadline: Optional[date] = None,
        date_retour_reel: Optional[date] = None,
    ) -> None:
        self.date_livraison_cdc = date_livraison_cdc or self.date_livraison_cdc
        self.date_cmde = date_cmde or self.date_cmde
        self.date_montage = date_montage or self.date_montage
        self.date_validation_fonctionnelle = (
            date_validation_fonctionnelle or self.date_validation_fonctionnelle
        )
        self.date_deadline_buffer = date_deadline_buffer or self.date_deadline_buffer
        self.date_deadline = date_deadline or self.date_deadline
        self.date_retour_reel = date_retour_reel or self.date_retour_reel
        self._verifier_ordre_dates()

    def _verifier_ordre_dates(self) -> None:
        jalons = [
            self.date_livraison_cdc,
            self.date_cmde,
            self.date_montage,
            self.date_validation_fonctionnelle,
            self.date_retour_reel,
        ]
        connus = [jalon for jalon in jalons if jalon is not None]
        if connus != sorted(connus):
            raise RegleMetierViolee("Les dates d'homologation sont incoherentes")


@dataclass
class DecisionCouverture:
    homologation_id: int
    est_couverte: bool
    justification: str
    projet_couvrant_id: Optional[int] = None
    id: Optional[int] = None
    date_decision: Optional[datetime] = None

    def __post_init__(self) -> None:
        if self.est_couverte and self.projet_couvrant_id is None:
            raise RegleMetierViolee("Une couverture valide exige un projet couvrant")
        if not self.est_couverte and self.projet_couvrant_id is not None:
            raise RegleMetierViolee("Une non-couverture ne doit pas avoir de projet couvrant")
        if not self.justification.strip():
            raise RegleMetierViolee("La justification de couverture est obligatoire")


@dataclass
class SilhouetteCouverte:
    homologation_id: int
    silhouette_id: int
    origine: OrigineSuggestion
    id: Optional[int] = None
