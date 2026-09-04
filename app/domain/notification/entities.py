"""Entites du bounded context Notification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.shared.enums import TypeNotification
from app.shared.exceptions import RegleMetierViolee


@dataclass
class Notification:
    utilisateur_id: int
    type: TypeNotification
    message: str
    id: Optional[int] = None
    date_envoi: Optional[datetime] = None
    lu: bool = False

    def __post_init__(self) -> None:
        if not self.message.strip():
            raise RegleMetierViolee("Le message de notification est obligatoire")

    def marquer_lue(self) -> None:
        self.lu = True
