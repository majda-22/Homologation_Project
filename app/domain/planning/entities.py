"""Entites du bounded context Planning."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from app.shared.enums import StatutAvancement, StatutEtape
from app.shared.exceptions import RegleMetierViolee


@dataclass
class PlanningConstruction:
    maquette_id: int
    id: Optional[int] = None
    statut_avancement: StatutAvancement = StatutAvancement.PLANIFIEE
    priorite_score: Optional[float] = None

    def definir_priorite(self, score: Optional[float]) -> None:
        if score is not None and score < 0:
            raise RegleMetierViolee("Le score de priorite ne peut pas etre negatif")
        self.priorite_score = score

    def changer_statut(self, statut: StatutAvancement) -> None:
        self.statut_avancement = statut


@dataclass
class EtapeConstruction:
    planning_id: int
    ordre: int
    libelle: str
    id: Optional[int] = None
    date_debut: Optional[date] = None
    date_fin: Optional[date] = None
    statut: StatutEtape = StatutEtape.A_FAIRE

    def __post_init__(self) -> None:
        if self.ordre <= 0:
            raise RegleMetierViolee("L'ordre d'une etape doit etre positif")
        if not self.libelle.strip():
            raise RegleMetierViolee("Le libelle d'une etape est obligatoire")
        if self.date_debut and self.date_fin and self.date_fin < self.date_debut:
            raise RegleMetierViolee("La date de fin d'une etape precede sa date de debut")

    def changer_statut(self, statut: StatutEtape) -> None:
        self.statut = statut
