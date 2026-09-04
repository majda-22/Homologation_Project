"""
Base déclarative SQLAlchemy 2.0 et mixin de timestamp commun.

Le TimestampMixin fournit uniquement `created_at`, de type DATETIME,
avec une valeur par défaut générée par la base de données.

Les champs de type DATE, comme `date_creation` dans Projet ou Maquette,
sont déclarés directement dans leurs modèles avec :

    server_default=text("CURRENT_DATE")

Les champs DATETIME utilisent :

    server_default=text("CURRENT_TIMESTAMP")
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, func, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class CreatedAtMixin:
    """
    Ajoute un champ `created_at` commun aux entités persistées.

    Le timestamp est généré côté base de données afin d'avoir
    une valeur cohérente lors de la création de l'enregistrement.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class UpdatedAtMixin:
    """Ajoute un champ `updated_at` maintenu lors des modifications."""

    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        onupdate=func.now(),
    )


class TimestampMixin(CreatedAtMixin):
    """Alias historique conserve pour compatibilite."""

    pass


class Base(DeclarativeBase):
    """
    Base déclarative SQLAlchemy 2.0 de l'application.

    Tous les modèles persistants héritent de cette classe.
    """

    pass
