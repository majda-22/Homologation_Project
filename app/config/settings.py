"""
Configuration centralisée de l'application.

Toute constante de chemin, tout paramètre lu depuis l'environnement,
passe par ce module. Aucun autre module ne doit lire os.environ ou
construire un chemin en dur — on importe `settings` depuis ici.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from app.shared.paths import chemin_base_app

# --- Racine du projet (dossier parent de app/) ---
BASE_DIR: Path = chemin_base_app()

# Charge le .env s'il existe (ne fait rien en son absence, donc les
# valeurs par défaut ci-dessous s'appliquent aussi hors développement).
load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    # --- Environnement ---
    app_env: str = os.getenv("APP_ENV", "development")

    # --- Base de données ---
    database_path: Path = BASE_DIR / os.getenv("DATABASE_PATH", "data/r116.db")

    # --- Dossiers de travail ---
    ml_models_dir: Path = BASE_DIR / "ml_models"
    data_dir: Path = BASE_DIR / "data"

    # --- Logging ---
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    log_file: Path = BASE_DIR / os.getenv("LOG_FILE", "logs/r116.log")

    @property
    def database_url(self) -> str:
        """URL SQLAlchemy pour SQLite (fichier unique embarqué)."""
        return f"sqlite:///{self.database_path}"

    def ensure_directories(self) -> None:
        """Crée les dossiers nécessaires s'ils n'existent pas encore."""
        for directory in (
            self.database_path.parent,
            self.ml_models_dir,
            self.log_file.parent,
        ):
            directory.mkdir(parents=True, exist_ok=True)


settings = Settings()
