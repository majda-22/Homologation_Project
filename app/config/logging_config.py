"""
Configuration du logging applicatif.

Appelé une seule fois, au démarrage (`app/main.py`), avant tout autre
import de couche métier. Log à la fois sur la console (lisible en dev)
et dans un fichier tournant (utile une fois packagé en .exe, où la
console n'est pas toujours visible).
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app.config.settings import settings

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging() -> None:
    settings.ensure_directories()

    root_logger = logging.getLogger()
    root_logger.setLevel(settings.log_level)

    # Évite les handlers dupliqués si configure_logging() est appelé
    # plusieurs fois (ex. dans les tests).
    if root_logger.handlers:
        return

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    file_handler = RotatingFileHandler(
        settings.log_file,
        maxBytes=5 * 1024 * 1024,  # 5 Mo
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Bibliothèques tierces bruyantes en DEBUG : on les garde en WARNING.
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.log_level == "DEBUG" else logging.WARNING
    )
