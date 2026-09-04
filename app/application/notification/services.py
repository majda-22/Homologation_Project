"""Services applicatifs Notification."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.domain.notification.entities import Notification
from app.infrastructure.database.database import SessionLocal
from app.infrastructure.database.repositories.notification_repositories import (
    SQLAlchemyNotificationRepository,
)
from app.shared.enums import TypeNotification
from app.shared.exceptions import RessourceIntrouvable


@dataclass(frozen=True)
class NotificationDTO:
    id: int
    utilisateur_id: int
    type: TypeNotification
    message: str
    date_envoi: Optional[datetime]
    lu: bool


def _notification_dto(item: Notification) -> NotificationDTO:
    if item.id is None:
        raise ValueError("Une notification persistee doit avoir un id")
    return NotificationDTO(
        id=item.id,
        utilisateur_id=item.utilisateur_id,
        type=item.type,
        message=item.message,
        date_envoi=item.date_envoi,
        lu=item.lu,
    )


class NotificationService:
    def __init__(self, session_factory: Callable[[], Session] = SessionLocal) -> None:
        self.session_factory = session_factory

    def creer(
        self,
        utilisateur_id: int,
        type_notification: TypeNotification,
        message: str,
    ) -> NotificationDTO:
        return self.envoyer(utilisateur_id, type_notification, message)

    def envoyer(
        self,
        utilisateur_id: int,
        type_notification: TypeNotification,
        message: str,
    ) -> NotificationDTO:
        with self.session_factory() as session:
            notifications = SQLAlchemyNotificationRepository(session)
            notification = notifications.ajouter(
                Notification(
                    utilisateur_id=utilisateur_id,
                    type=type_notification,
                    message=message,
                )
            )
            session.commit()
            return _notification_dto(notification)

    def lister(
        self,
        utilisateur_id: int,
        lu: Optional[bool] = None,
    ) -> list[NotificationDTO]:
        with self.session_factory() as session:
            notifications = SQLAlchemyNotificationRepository(session)
            return [
                _notification_dto(item)
                for item in notifications.lister_par_utilisateur(utilisateur_id, lu)
            ]

    def marquer_lue(self, notification_id: int) -> NotificationDTO:
        with self.session_factory() as session:
            notifications = SQLAlchemyNotificationRepository(session)
            notification = notifications.obtenir_par_id(notification_id)
            if notification is None:
                raise RessourceIntrouvable(f"Notification introuvable: {notification_id}")
            notification.marquer_lue()
            notification = notifications.sauvegarder(notification)
            session.commit()
            return _notification_dto(notification)
