"""Contrats repositories du bounded context Homologation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from app.domain.homologation.entities import (
    DecisionCouverture,
    Homologation,
    SilhouetteCouverte,
)


class HomologationRepository(ABC):
    @abstractmethod
    def ajouter(self, homologation: Homologation) -> Homologation:
        ...

    @abstractmethod
    def obtenir_par_id(self, homologation_id: int) -> Optional[Homologation]:
        ...

    @abstractmethod
    def lister(self, maquette_id: Optional[int] = None) -> list[Homologation]:
        ...

    @abstractmethod
    def sauvegarder(self, homologation: Homologation) -> Homologation:
        ...


class DecisionCouvertureRepository(ABC):
    @abstractmethod
    def ajouter(self, decision: DecisionCouverture) -> DecisionCouverture:
        ...

    @abstractmethod
    def lister_par_homologation(self, homologation_id: int) -> list[DecisionCouverture]:
        ...


class SilhouetteCouverteRepository(ABC):
    @abstractmethod
    def ajouter(self, silhouette: SilhouetteCouverte) -> SilhouetteCouverte:
        ...

    @abstractmethod
    def lister_par_homologation(self, homologation_id: int) -> list[SilhouetteCouverte]:
        ...

    @abstractmethod
    def retirer(self, silhouette_couverte_id: int) -> None:
        ...
