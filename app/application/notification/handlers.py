"""Handlers de notification branches sur les evenements metier."""

from __future__ import annotations

from app.application.notification.services import NotificationService
from app.domain.homologation.events import (
    DecisionCouvertureCreee,
    HomologationDemarree,
    RetardDetecte,
    StatutProjetChange,
)
from app.shared.enums import TypeNotification


def handle_statut_projet_change(
    event: StatutProjetChange,
    notification_service: NotificationService,
) -> None:
    if event.utilisateur_id is None:
        return
    notification_service.creer(
        utilisateur_id=event.utilisateur_id,
        type_notification=TypeNotification.CHANGEMENT_STATUT,
        message=(
            f"Projet #{event.projet_id}: statut {event.ancien_statut.value} -> "
            f"{event.nouveau_statut.value}"
        ),
    )


def handle_homologation_demarree(
    event: HomologationDemarree,
    notification_service: NotificationService,
) -> None:
    if event.utilisateur_id is None:
        return
    notification_service.creer(
        utilisateur_id=event.utilisateur_id,
        type_notification=TypeNotification.CHANGEMENT_STATUT,
        message=(
            f"Homologation #{event.homologation_id} demarree pour la maquette "
            f"#{event.maquette_id}"
        ),
    )


def handle_decision_couverture_creee(
    event: DecisionCouvertureCreee,
    notification_service: NotificationService,
) -> None:
    if event.utilisateur_id is None:
        return
    resultat = "couverte" if event.est_couverte else "non couverte"
    notification_service.creer(
        utilisateur_id=event.utilisateur_id,
        type_notification=TypeNotification.CHANGEMENT_STATUT,
        message=(
            f"Decision de couverture #{event.decision_id} creee pour "
            f"l'homologation #{event.homologation_id}: {resultat}"
        ),
    )


def handle_retard_detecte(
    event: RetardDetecte,
    notification_service: NotificationService,
) -> None:
    if event.utilisateur_id is None:
        return
    notification_service.creer(
        utilisateur_id=event.utilisateur_id,
        type_notification=TypeNotification.ALERTE_RETARD,
        message=(
            f"Retard detecte sur la maquette #{event.maquette_id}: "
            f"{event.jours_de_retard} jour(s)"
        ),
    )
