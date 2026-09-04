"""Chemins utilisateur pour les fichiers generes."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path


def chemin_base_app() -> Path:
    """Racine mutable de l'application, compatible PyInstaller."""

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def obtenir_dossier_downloads() -> Path:
    """Detecte le dossier Downloads utilisateur, sans fallback interne a l'app."""

    home = Path.home()
    downloads = home / "Downloads"
    if downloads.exists():
        return downloads
    downloads_fr = home / "Téléchargements"
    if downloads_fr.exists():
        return downloads_fr
    return home


def chemin_unique_downloads(filename: str, suffix_timestamp: datetime | None = None) -> Path:
    """Retourne un chemin Downloads unique en ajoutant un timestamp si besoin."""

    directory = obtenir_dossier_downloads()
    directory.mkdir(parents=True, exist_ok=True)
    output_path = directory / filename
    if not output_path.exists():
        return output_path

    timestamp = suffix_timestamp or datetime.now()
    return output_path.with_name(
        f"{output_path.stem}_{timestamp:%Y%m%d_%H%M%S}{output_path.suffix}"
    )
