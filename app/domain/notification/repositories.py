"""Contrats repositories du bounded context Notification."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from app.domain.notification.entities import Notification


class NotificationRepository(ABC):
    @abstractmethod
    def ajouter(self, notification: Notification) -> Notification:
        ...

    @abstractmethod
    def obtenir_par_id(self, notification_id: int) -> Optional[Notification]:
        ...

    @abstractmethod
    def lister_par_utilisateur(
        self,
        utilisateur_id: int,
        lu: Optional[bool] = None,
    ) -> list[Notification]:
        ...

    @abstractmethod
    def sauvegarder(self, notification: Notification) -> Notification:
        ...
