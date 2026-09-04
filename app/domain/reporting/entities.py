"""Objets domaine du bounded context Reporting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class RapportDemande:
    type_rapport: str
    projet_id: Optional[int] = None
    utilisateur_id: Optional[int] = None


@dataclass(frozen=True)
class RapportGenere:
    chemin: Path
    type_rapport: str
    genere_le: datetime
