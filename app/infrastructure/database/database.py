"""
Configuration de la base de données SQLite pour la plateforme R116.

Responsabilités :
- créer le moteur SQLAlchemy ;
- configurer SQLite ;
- activer les contraintes de clés étrangères ;
- exposer une factory de sessions ;
- fournir une session contextuelle simple.

La base utilisée par défaut est :
    data/r116.db
"""

from __future__ import annotations

from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import settings


# ============================================================================
# CONFIGURATION
# ============================================================================

# Racine du projet :
# app/infrastructure/database/database.py
#                         ↑
# parents[0] = database
# parents[1] = infrastructure
# parents[2] = app
# parents[3] = racine du projet
settings.ensure_directories()
DATABASE_URL = settings.database_url


# ============================================================================
# ENGINE
# ============================================================================

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False,
)


# ============================================================================
# SQLITE FOREIGN KEYS
# ============================================================================

@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record) -> None:
    """
    Active les contraintes de clés étrangères SQLite.

    Important :
    Les ON DELETE RESTRICT définis dans models.py ne sont réellement
    appliqués par SQLite que si foreign_keys est activé.
    """
    cursor = dbapi_connection.cursor()

    try:
        cursor.execute("PRAGMA foreign_keys = ON")
    finally:
        cursor.close()


# ============================================================================
# SESSION
# ============================================================================

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """
    Fournit une session SQLAlchemy.

    Usage :

        db = next(get_db())

    ou, plus généralement, dans une couche application/service :

        db = SessionLocal()
        try:
            ...
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    """
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()
