"""Evenements metier publies par les workflows R116."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from app.shared.enums import StatutProjet


@dataclass(frozen=True)
class StatutProjetChange:
    projet_id: int
    ancien_statut: StatutProjet
    nouveau_statut: StatutProjet
    utilisateur_id: Optional[int] = None


@dataclass(frozen=True)
class HomologationDemarree:
    homologation_id: int
    maquette_id: int
    utilisateur_id: Optional[int] = None


@dataclass(frozen=True)
class DecisionCouvertureCreee:
    decision_id: int
    homologation_id: int
    est_couverte: bool
    utilisateur_id: Optional[int] = None


@dataclass(frozen=True)
class DateDeadlineChangee:
    homologation_id: int
    maquette_id: int
    ancienne_deadline: Optional[date]
    nouvelle_deadline: date


@dataclass(frozen=True)
class RetardDetecte:
    maquette_id: int
    jours_de_retard: int
    utilisateur_id: Optional[int] = None
