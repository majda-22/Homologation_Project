"""Gabarit metier pour generer un planning theorique de maquette."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

DUREE_CDC_CMDE = 49
DUREE_CMDE_MONTAGE = 98
DUREE_MONTAGE_VALIDATION = 35
DUREE_VALIDATION_DEADLINE_BUFFER = 56
DUREE_DEADLINE_RETOUR = 42


@dataclass(frozen=True)
class EtapePlanifiee:
    libelle: str
    date_debut_estimee: date
    date_fin_estimee: date


def generer_planning_theorique(
    date_livraison_cdc: date,
    residu_predit: int,
) -> list[EtapePlanifiee]:
    """Construit le calendrier complet a partir du CDC et du residu ML."""

    date_cmde = date_livraison_cdc + timedelta(days=DUREE_CDC_CMDE)
    montage = date_cmde + timedelta(days=DUREE_CMDE_MONTAGE)
    validation = montage + timedelta(days=DUREE_MONTAGE_VALIDATION)
    deadline_buffer = validation + timedelta(days=DUREE_VALIDATION_DEADLINE_BUFFER)
    deadline = deadline_buffer + timedelta(days=residu_predit)
    dll_retour_estimee = deadline + timedelta(days=DUREE_DEADLINE_RETOUR)

    return [
        EtapePlanifiee("Cahier des charges", date_livraison_cdc, date_cmde),
        EtapePlanifiee("Commande", date_cmde, date_cmde),
        EtapePlanifiee("Montage", date_cmde, montage),
        EtapePlanifiee("Validation fonctionnelle", montage, validation),
        EtapePlanifiee("Deadline avec buffer", validation, deadline_buffer),
        EtapePlanifiee("Deadline contractuelle", deadline_buffer, deadline),
        EtapePlanifiee("Retour estime", deadline, dll_retour_estimee),
    ]
