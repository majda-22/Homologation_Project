"""
Entités du bounded context Project.

Aucune dépendance à SQLAlchemy ni à l'infrastructure ici -- ce sont des
objets Python purs. Le mapping vers les tables se fait exclusivement dans
la couche infrastructure (repositories), jamais l'inverse.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from app.shared.enums import StatutProjet, TypeHomologation
from app.shared.exceptions import RegleMetierViolee


@dataclass
class Projet:
    reference: str
    date_creation: date
    created_by_id: int
    id: Optional[int] = None
    statut: StatutProjet = StatutProjet.PLANIFIEE

    def changer_statut(self, nouveau_statut: StatutProjet) -> None:
        """Applique une transition de statut, en rejetant les retours en
        arrière incohérents (ex: repasser une TERMINEE en PLANIFIEE)."""
        transitions_interdites = {
            (StatutProjet.TERMINEE, StatutProjet.PLANIFIEE),
            (StatutProjet.TERMINEE, StatutProjet.EN_COURS),
        }
        if (self.statut, nouveau_statut) in transitions_interdites:
            raise RegleMetierViolee(
                f"Transition de statut invalide : {self.statut} -> {nouveau_statut}"
            )
        self.statut = nouveau_statut

    def est_modifiable(self) -> bool:
        """Un projet terminé ne devrait plus être modifié en surface --
        règle simple, à affiner si le métier l'exige."""
        return self.statut != StatutProjet.TERMINEE


@dataclass
class Maquette:
    projet_id: int
    silhouette_id: int
    architecture_ee_id: int
    fournisseur_id: int
    composant_modifie: str
    type_homologation: TypeHomologation
    date_creation: date
    id: Optional[int] = None
    modele: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.composant_modifie or not self.composant_modifie.strip():
            raise RegleMetierViolee("Le composant modifié ne peut pas être vide")