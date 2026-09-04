"""Exceptions métier partagées par l'ensemble du domaine.

Une seule hiérarchie simple pour l'instant -- à spécialiser (ex:
CouvertureIncoherente, RetardDetecte) au fur et à mesure des besoins réels
des couches application, plutôt que de préanticiper une taxonomie complète.
"""


class RegleMetierViolee(Exception):
    """Levée quand une règle du domaine est violée (ex: transition de
    statut invalide, donnée obligatoire manquante). Distincte des erreurs
    techniques (IntegrityError SQLAlchemy, etc.), qui restent dans la
    couche infrastructure."""
    pass


class RessourceIntrouvable(Exception):
    """Le cas demande n'existe pas dans le systeme."""

    pass


class RessourceDejaExistante(Exception):
    """Une ressource unique existe deja, par exemple une reference projet."""

    pass
