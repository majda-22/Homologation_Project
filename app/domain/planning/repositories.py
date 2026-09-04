"""Contrats repositories du bounded context Planning."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from app.domain.planning.entities import EtapeConstruction, PlanningConstruction


class PlanningRepository(ABC):
    @abstractmethod
    def ajouter(self, planning: PlanningConstruction) -> PlanningConstruction:
        ...

    @abstractmethod
    def obtenir_par_id(self, planning_id: int) -> Optional[PlanningConstruction]:
        ...

    @abstractmethod
    def obtenir_par_maquette(self, maquette_id: int) -> Optional[PlanningConstruction]:
        ...

    @abstractmethod
    def lister(self) -> list[PlanningConstruction]:
        ...

    @abstractmethod
    def sauvegarder(self, planning: PlanningConstruction) -> PlanningConstruction:
        ...


class EtapeConstructionRepository(ABC):
    @abstractmethod
    def ajouter(self, etape: EtapeConstruction) -> EtapeConstruction:
        ...

    @abstractmethod
    def lister_par_planning(self, planning_id: int) -> list[EtapeConstruction]:
        ...

    @abstractmethod
    def sauvegarder(self, etape: EtapeConstruction) -> EtapeConstruction:
        ...
