"""Handlers du bounded context Planning."""

from __future__ import annotations

from datetime import date
from typing import Optional

from app.application.planning.services import PlanningService
from app.domain.homologation.events import DateDeadlineChangee


def on_reordonnancement_necessaire(
    event,
    planning_service: PlanningService,
    aujourdhui: Optional[date] = None,
) -> None:
    """Reordonnancement global, quelle que soit la cause metier."""
    planning_service.reordonnancer_toutes_les_maquettes_actives(aujourdhui=aujourdhui)


def handle_date_deadline_changee(
    event: DateDeadlineChangee,
    planning_service: PlanningService,
    aujourdhui: Optional[date] = None,
) -> None:
    on_reordonnancement_necessaire(event, planning_service, aujourdhui=aujourdhui)
