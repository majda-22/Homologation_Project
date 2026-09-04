"""Point d'entree de l'application R116 Platform."""

from __future__ import annotations

import logging

import flet as ft

from app.application.notification.handlers import (
    handle_decision_couverture_creee,
    handle_homologation_demarree,
    handle_retard_detecte,
    handle_statut_projet_change,
)
from app.application.notification.services import NotificationService
from app.application.planning.handlers import on_reordonnancement_necessaire
from app.application.planning.services import PlanningService
from app.config.logging_config import configure_logging
from app.config.settings import settings
from app.domain.homologation.events import (
    DateDeadlineChangee,
    DecisionCouvertureCreee,
    HomologationDemarree,
    RetardDetecte,
    StatutProjetChange,
)
from app.infrastructure.database import init_db
from app.infrastructure.database.database import SessionLocal
from app.infrastructure.database.seed import seed_admin
from app.presentation.project_app import build_project_app
from app.shared.events import EventBus

logger = logging.getLogger(__name__)

event_bus = EventBus()
first_launch_admin_password_file = None


def configure_event_handlers() -> None:
    notification_service = NotificationService()
    planning_service = PlanningService()
    event_bus.subscribe(
        StatutProjetChange,
        lambda event: handle_statut_projet_change(event, notification_service),
    )
    event_bus.subscribe(
        HomologationDemarree,
        lambda event: handle_homologation_demarree(event, notification_service),
    )
    event_bus.subscribe(
        DecisionCouvertureCreee,
        lambda event: handle_decision_couverture_creee(event, notification_service),
    )
    event_bus.subscribe(
        RetardDetecte,
        lambda event: handle_retard_detecte(event, notification_service),
    )
    event_bus.subscribe(
        DateDeadlineChangee,
        lambda event: on_reordonnancement_necessaire(event, planning_service),
    )
    event_bus.subscribe(
        RetardDetecte,
        lambda event: on_reordonnancement_necessaire(event, planning_service),
    )


def main() -> None:
    global first_launch_admin_password_file
    configure_logging()
    settings.ensure_directories()
    init_db()
    with SessionLocal() as session:
        first_launch_admin_password_file = seed_admin(session)
        session.commit()
    configure_event_handlers()

    logger.info("Demarrage de R116 Platform (env=%s)", settings.app_env)
    logger.info("Base de donnees : %s", settings.database_path)

    ft.app(
        target=lambda page: build_project_app(
            page,
            event_bus=event_bus,
            first_launch_admin_password_file=first_launch_admin_password_file,
        )
    )


if __name__ == "__main__":
    main()
