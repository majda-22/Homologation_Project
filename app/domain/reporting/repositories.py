"""Contrats de lecture pour le bounded context Reporting."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class ReportingReadRepository(ABC):
    @abstractmethod
    def resume_projet(self, projet_id: int) -> dict:
        ...

    @abstractmethod
    def tableau_bord(self) -> dict:
        ...

    @abstractmethod
    def lignes_cdc(self, maquette_id: Optional[int] = None) -> list[dict]:
        ...
