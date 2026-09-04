"""Repositories SQLAlchemy pour le bounded context Notification."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.notification.entities import Notification
from app.domain.notification.repositories import NotificationRepository
from app.infrastructure.database import models


def _to_domain_notification(row: models.Notification) -> Notification:
    return Notification(
        id=row.id,
        utilisateur_id=row.utilisateur_id,
        type=row.type,
        message=row.message,
        date_envoi=row.date_envoi,
        lu=row.lu,
    )


class SQLAlchemyNotificationRepository(NotificationRepository):
    def __init__(self, session: Session) -> None:
        self.session = session

    def ajouter(self, notification: Notification) -> Notification:
        row = models.Notification(
            utilisateur_id=notification.utilisateur_id,
            type=notification.type,
            message=notification.message,
            lu=notification.lu,
        )
        self.session.add(row)
        self.session.flush()
        return _to_domain_notification(row)

    def obtenir_par_id(self, notification_id: int) -> Optional[Notification]:
        row = self.session.get(models.Notification, notification_id)
        return _to_domain_notification(row) if row else None

    def lister_par_utilisateur(
        self,
        utilisateur_id: int,
        lu: Optional[bool] = None,
    ) -> list[Notification]:
        statement = (
            select(models.Notification)
            .where(models.Notification.utilisateur_id == utilisateur_id)
            .order_by(models.Notification.id.desc())
        )
        if lu is not None:
            statement = statement.where(models.Notification.lu == lu)
        return [_to_domain_notification(row) for row in self.session.scalars(statement)]

    def sauvegarder(self, notification: Notification) -> Notification:
        row = self.session.get(models.Notification, notification.id)
        if row is None:
            raise ValueError(f"Notification introuvable: {notification.id}")
        row.lu = notification.lu
        row.message = notification.message
        row.type = notification.type
        self.session.flush()
        return _to_domain_notification(row)
