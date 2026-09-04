"""
Enumérations métier partagées entre le domaine et l'infrastructure.

Vivent dans app/shared/ (et non dans infrastructure/) pour respecter le
sens de dépendance DDD : le domaine ne doit jamais dépendre de
l'infrastructure. Ces enums sont de simples types de valeur, sans aucun
comportement lié à SQLAlchemy ou à la base de données -- les importer
depuis le domaine ne crée donc pas de couplage vers l'infrastructure.

Chaque enum est stocké en SQLite comme VARCHAR + CHECK constraint
(SQLAlchemy s'en charge automatiquement via sa.Enum, SQLite n'ayant pas
de type ENUM natif).
"""

import enum


class RoleUtilisateur(str, enum.Enum):
    INGENIEUR = "INGENIEUR"
    PLANNER = "PLANNER"
    ADMIN = "ADMIN"


class StatutProjet(str, enum.Enum):
    PLANIFIEE = "PLANIFIEE"
    EN_COURS = "EN_COURS"
    TERMINEE = "TERMINEE"


class TypeHomologation(str, enum.Enum):
    MAQUETTE = "MAQUETTE"
    VEHICULE = "VEHICULE"
    COLONNE_DIRECTION = "COLONNE_DIRECTION"


class StatutHomologation(str, enum.Enum):
    """Représente uniquement le cycle de vie du processus d'homologation.
    Le résultat de couverture (couvert/non couvert) N'EST PAS ici :
    il vit exclusivement dans DecisionCouverture.est_couverte.
    """
    EN_ATTENTE = "EN_ATTENTE"
    EN_COURS = "EN_COURS"
    TERMINEE = "TERMINEE"


class ConfidenceLevel(str, enum.Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class StatutAvancement(str, enum.Enum):
    PLANIFIEE = "PLANIFIEE"
    EN_COURS = "EN_COURS"
    TERMINEE = "TERMINEE"


class StatutEtape(str, enum.Enum):
    A_FAIRE = "A_FAIRE"
    EN_COURS = "EN_COURS"
    TERMINEE = "TERMINEE"


class TypeNotification(str, enum.Enum):
    CHANGEMENT_STATUT = "CHANGEMENT_STATUT"
    ALERTE_RETARD = "ALERTE_RETARD"
    RAPPORT_GENERE = "RAPPORT_GENERE"


class OrigineSuggestion(str, enum.Enum):
    """Générique : indique si une donnée a été suggérée automatiquement par
    le système (similarité / correspondance de règles) ou validée/ajoutée
    manuellement par l'ingénieur. Utilisé pour SilhouetteCouverte.origine
    ET LigneCDC.origine — même sémantique, même pattern hybride partout."""
    SUGGESTION_AUTO = "SUGGESTION_AUTO"
    VALIDATION_INGENIEUR = "VALIDATION_INGENIEUR"
