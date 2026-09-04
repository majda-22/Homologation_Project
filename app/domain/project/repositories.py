"""
Interfaces (contrats) des repositories du bounded context Project.

Définies côté domaine, implémentées côté infrastructure
(app/infrastructure/database/repositories/). Le domaine dépend de ces
abstractions, jamais de SQLAlchemy directement -- c'est ce qui permet de
tester la logique métier sans base de données.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from app.domain.project.entities import Maquette, Projet


class ProjetRepository(ABC):
    @abstractmethod
    def ajouter(self, projet: Projet) -> Projet:
        ...

    @abstractmethod
    def obtenir_par_id(self, projet_id: int) -> Optional[Projet]:
        ...

    @abstractmethod
    def obtenir_par_reference(self, reference: str) -> Optional[Projet]:
        ...

    @abstractmethod
    def lister(self, statut: Optional[str] = None) -> list[Projet]:
        ...


class MaquetteRepository(ABC):
    @abstractmethod
    def ajouter(self, maquette: Maquette) -> Maquette:
        ...

    @abstractmethod
    def obtenir_par_id(self, maquette_id: int) -> Optional[Maquette]:
        ...

    @abstractmethod
    def rechercher(
        self,
        projet_id: Optional[int] = None,
        silhouette_id: Optional[int] = None,
        architecture_ee_id: Optional[int] = None,
        fournisseur_id: Optional[int] = None,
        type_homologation: Optional[str] = None,
    ) -> list[Maquette]:
        ...
