"""
Initialisation de la base de données R116.

Responsabilités :
- importer tous les modèles afin qu'ils soient enregistrés dans Base.metadata ;
- créer les tables manquantes ;
- vérifier que SQLite applique bien les foreign keys.

Ce script ne contient PAS le seed métier.
Le seed est réalisé séparément par seed.py.
"""

from __future__ import annotations

from sqlalchemy import inspect, text

from .base import Base
from .database import engine

# IMPORTANT :
# L'import explicite de models garantit que toutes les classes SQLAlchemy
# sont enregistrées dans Base.metadata avant create_all().
from . import models  # noqa: F401


def init_db() -> None:
    """Crée les tables de la base si elles n'existent pas encore."""

    print("Initialisation de la base de données R116...")

    Base.metadata.create_all(bind=engine)
    _apply_lightweight_migrations()

    inspector = inspect(engine)
    tables = inspector.get_table_names()

    print(f"Base de données : {engine.url}")
    print(f"Tables créées/existantes : {len(tables)}")

    for table in sorted(tables):
        print(f"  [OK] {table}")

    # Vérification explicite de SQLite foreign_keys.
    with engine.connect() as connection:
        foreign_keys_enabled = connection.execute(
            text("PRAGMA foreign_keys")
        ).scalar()

    if foreign_keys_enabled != 1:
        raise RuntimeError(
            "Les contraintes SQLite FOREIGN KEY ne sont pas activées."
        )

    print("[OK] SQLite foreign_keys = ON")
    print("[OK] Initialisation terminée.")


def _apply_lightweight_migrations() -> None:
    """Ajoute les colonnes simples attendues par les anciennes bases SQLite."""

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    with engine.begin() as connection:
        if "ligne_cdc" in tables:
            columns = {column["name"] for column in inspector.get_columns("ligne_cdc")}
            if "suggestion_source" not in columns:
                connection.execute(
                    text("ALTER TABLE ligne_cdc ADD COLUMN suggestion_source VARCHAR(120)")
                )
        if {"planning_construction", "etape_construction", "maquette"}.issubset(tables):
            _migrer_phase_cdc_planning(connection)


def _migrer_phase_cdc_planning(connection) -> None:
    """Ajoute la phase CDC aux anciens plannings qui demarraient au CMDE."""

    connection.execute(
        text(
            """
            UPDATE etape_construction
            SET libelle = 'Cahier des charges',
                date_fin = COALESCE(
                    (
                        SELECT commande.date_debut
                        FROM etape_construction AS commande
                        WHERE commande.planning_id = etape_construction.planning_id
                          AND commande.libelle = 'Commande'
                        ORDER BY commande.ordre
                        LIMIT 1
                    ),
                    date_fin
                )
            WHERE libelle = 'Livraison CDC'
            """
        )
    )

    connection.execute(
        text(
            """
            UPDATE etape_construction
            SET ordre = ordre + 1000
            WHERE planning_id IN (
                SELECT planning.id
                FROM planning_construction AS planning
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM etape_construction AS cdc
                    WHERE cdc.planning_id = planning.id
                      AND cdc.libelle = 'Cahier des charges'
                )
                AND EXISTS (
                    SELECT 1
                    FROM etape_construction AS commande
                    WHERE commande.planning_id = planning.id
                      AND commande.libelle = 'Commande'
                      AND commande.ordre = 1
                )
            )
            """
        )
    )

    connection.execute(
        text(
            """
            INSERT INTO etape_construction (
                planning_id,
                ordre,
                libelle,
                date_debut,
                date_fin,
                statut,
                created_at
            )
            SELECT
                planning.id,
                1,
                'Cahier des charges',
                COALESCE(maquette.date_creation, date(commande.date_debut, '-49 days')),
                commande.date_debut,
                commande.statut,
                CURRENT_TIMESTAMP
            FROM planning_construction AS planning
            JOIN maquette ON maquette.id = planning.maquette_id
            JOIN etape_construction AS commande
              ON commande.planning_id = planning.id
             AND commande.libelle = 'Commande'
             AND commande.ordre = 1001
            WHERE NOT EXISTS (
                SELECT 1
                FROM etape_construction AS cdc
                WHERE cdc.planning_id = planning.id
                  AND cdc.libelle = 'Cahier des charges'
            )
            """
        )
    )

    connection.execute(
        text(
            """
            UPDATE etape_construction
            SET ordre = ordre - 999
            WHERE ordre >= 1001
            """
        )
    )


if __name__ == "__main__":
    init_db()
