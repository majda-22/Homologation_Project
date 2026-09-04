"""
Modèles SQLAlchemy — schéma relationnel du projet R116.

Ordre de définition volontaire (détecte les problèmes de relations tôt) :
1. Utilisateur
2. Référentiels (Silhouette, ArchitectureEE, Fournisseur)
3. Projet
4. Maquette
5. Homologation
6. DecisionCouverture
7. Prediction
8. PlanningConstruction
9. EtapeConstruction
10. Notification
11. AuditLog

Aucune logique métier ici (pas de "if est_couverte: ..."). Ce fichier ne
décrit que la structure et les contraintes ; la logique vit dans
app/domain/.
"""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    Boolean,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.infrastructure.database.base import Base, CreatedAtMixin, UpdatedAtMixin
from app.shared.enums import (
    ConfidenceLevel,
    OrigineSuggestion,
    RoleUtilisateur,
    StatutAvancement,
    StatutEtape,
    StatutHomologation,
    StatutProjet,
    TypeHomologation,
    TypeNotification,
)


# ---------------------------------------------------------------------------
# 1. Utilisateur
# ---------------------------------------------------------------------------
class Utilisateur(Base, CreatedAtMixin):
    __tablename__ = "utilisateur"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[RoleUtilisateur] = mapped_column(
        Enum(RoleUtilisateur, native_enum=False), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Relations inverses
    projets_crees: Mapped[list["Projet"]] = relationship(back_populates="created_by")
    notifications: Mapped[list["Notification"]] = relationship(back_populates="utilisateur")
    audit_logs: Mapped[list["AuditLog"]] = relationship(back_populates="utilisateur")

    def __repr__(self) -> str:
        return f"<Utilisateur {self.username} ({self.role})>"


# ---------------------------------------------------------------------------
# 2. Référentiels
# ---------------------------------------------------------------------------
class Silhouette(Base, CreatedAtMixin):
    __tablename__ = "silhouette"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    libelle: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    maquettes: Mapped[list["Maquette"]] = relationship(back_populates="silhouette")

    def __repr__(self) -> str:
        return f"<Silhouette {self.libelle}>"


class ArchitectureEE(Base, CreatedAtMixin):
    __tablename__ = "architecture_ee"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reference: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    version: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    maquettes: Mapped[list["Maquette"]] = relationship(back_populates="architecture_ee")

    def __repr__(self) -> str:
        return f"<ArchitectureEE {self.reference}>"


class Fournisseur(Base, CreatedAtMixin):
    __tablename__ = "fournisseur"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nom: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)

    maquettes: Mapped[list["Maquette"]] = relationship(back_populates="fournisseur")

    def __repr__(self) -> str:
        return f"<Fournisseur {self.nom}>"


class TypeComposant(Base, CreatedAtMixin):
    """Référentiel des codes composants réutilisés dans les CDC
    (ex: 'T1', 'P3', 'T18') — catalogue standardisé, pas du texte libre."""

    __tablename__ = "type_composant"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(10), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    lignes_cdc: Mapped[list["LigneCDC"]] = relationship(back_populates="type_composant")

    def __repr__(self) -> str:
        return f"<TypeComposant {self.code}>"


class Sujet(Base, CreatedAtMixin):
    __tablename__ = "sujet"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    maquettes: Mapped[list["MaquetteSujet"]] = relationship(back_populates="sujet")

    def __repr__(self) -> str:
        return f"<Sujet {self.code}>"


# ---------------------------------------------------------------------------
# 3. Projet
# ---------------------------------------------------------------------------
class Projet(Base, CreatedAtMixin, UpdatedAtMixin):
    __tablename__ = "projet"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reference: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    date_creation: Mapped[date] = mapped_column(Date, nullable=False)
    statut: Mapped[StatutProjet] = mapped_column(
        Enum(StatutProjet, native_enum=False), nullable=False, default=StatutProjet.PLANIFIEE
    )
    created_by_id: Mapped[int] = mapped_column(
        ForeignKey("utilisateur.id", ondelete="RESTRICT"), nullable=False
    )

    created_by: Mapped["Utilisateur"] = relationship(back_populates="projets_crees")
    maquettes: Mapped[list["Maquette"]] = relationship(back_populates="projet")
    decisions_ou_il_est_couvrant: Mapped[list["DecisionCouverture"]] = relationship(
        back_populates="projet_couvrant"
    )

    __table_args__ = (
        Index("ix_projet_statut", "statut"),
    )

    def __repr__(self) -> str:
        return f"<Projet {self.reference} ({self.statut})>"


# ---------------------------------------------------------------------------
# 4. Maquette
# ---------------------------------------------------------------------------
class Maquette(Base, CreatedAtMixin):
    __tablename__ = "maquette"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    projet_id: Mapped[int] = mapped_column(
        ForeignKey("projet.id", ondelete="RESTRICT"), nullable=False
    )
    silhouette_id: Mapped[int] = mapped_column(
        ForeignKey("silhouette.id", ondelete="RESTRICT"), nullable=False
    )
    architecture_ee_id: Mapped[int] = mapped_column(
        ForeignKey("architecture_ee.id", ondelete="RESTRICT"), nullable=False
    )
    fournisseur_id: Mapped[int] = mapped_column(
        ForeignKey("fournisseur.id", ondelete="RESTRICT"), nullable=False
    )
    composant_modifie: Mapped[str] = mapped_column(String(150), nullable=False)
    type_homologation: Mapped[TypeHomologation] = mapped_column(
        Enum(TypeHomologation, native_enum=False), nullable=False
    )
    # Correspond à la colonne "Mot" du suivi réel (ex: "M3") — code modèle
    # véhicule. Nullable : pas toujours connu à la création de la maquette.
    modele: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    date_creation: Mapped[date] = mapped_column(Date, nullable=False)

    projet: Mapped["Projet"] = relationship(back_populates="maquettes")
    silhouette: Mapped["Silhouette"] = relationship(back_populates="maquettes")
    architecture_ee: Mapped["ArchitectureEE"] = relationship(back_populates="maquettes")
    fournisseur: Mapped["Fournisseur"] = relationship(back_populates="maquettes")

    homologations: Mapped[list["Homologation"]] = relationship(back_populates="maquette")
    predictions: Mapped[list["Prediction"]] = relationship(back_populates="maquette")
    planning: Mapped[Optional["PlanningConstruction"]] = relationship(
        back_populates="maquette", uselist=False
    )
    lignes_cdc: Mapped[list["LigneCDC"]] = relationship(back_populates="maquette")
    sujets: Mapped[list["MaquetteSujet"]] = relationship(back_populates="maquette")

    __table_args__ = (
        Index("ix_maquette_silhouette", "silhouette_id"),
        Index("ix_maquette_architecture_ee", "architecture_ee_id"),
    )

    def __repr__(self) -> str:
        return f"<Maquette id={self.id} projet={self.projet_id}>"


# ---------------------------------------------------------------------------
# 4bis. LigneCDC
# ---------------------------------------------------------------------------
class LigneCDC(Base, CreatedAtMixin):
    """Ligne de nomenclature du cahier des charges : un type de composant
    et sa quantité, pour une Maquette donnée. Le CDC généré en PDF est la
    concaténation de ces lignes (cf. exemple réel : T1, P3, T2 x2, ...)."""

    __tablename__ = "ligne_cdc"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    maquette_id: Mapped[int] = mapped_column(
        ForeignKey("maquette.id", ondelete="RESTRICT"), nullable=False
    )
    type_composant_id: Mapped[int] = mapped_column(
        ForeignKey("type_composant.id", ondelete="RESTRICT"), nullable=False
    )
    quantite_hw: Mapped[int] = mapped_column(Integer, nullable=False)
    # Traçabilité : cette ligne vient-elle de la suggestion automatique par
    # similarité (CDC du projet historique le plus proche) ou d'une
    # validation/correction manuelle par l'ingénieur ? Même pattern hybride
    # que SilhouetteCouverte.origine.
    origine: Mapped[OrigineSuggestion] = mapped_column(
        Enum(OrigineSuggestion, native_enum=False), nullable=False
    )
    suggestion_source: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)

    maquette: Mapped["Maquette"] = relationship(back_populates="lignes_cdc")
    type_composant: Mapped["TypeComposant"] = relationship(back_populates="lignes_cdc")

    __table_args__ = (
        UniqueConstraint("maquette_id", "type_composant_id", name="uq_ligne_cdc_maquette_type"),
        CheckConstraint("quantite_hw > 0", name="ck_ligne_cdc_quantite_positive"),
    )

    def __repr__(self) -> str:
        return f"<LigneCDC maquette={self.maquette_id} type={self.type_composant_id} qte={self.quantite_hw}>"


class MaquetteSujet(Base, CreatedAtMixin):
    __tablename__ = "maquette_sujet"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    maquette_id: Mapped[int] = mapped_column(
        ForeignKey("maquette.id", ondelete="RESTRICT"), nullable=False
    )
    sujet_id: Mapped[int] = mapped_column(
        ForeignKey("sujet.id", ondelete="RESTRICT"), nullable=False
    )

    maquette: Mapped["Maquette"] = relationship(back_populates="sujets")
    sujet: Mapped["Sujet"] = relationship(back_populates="maquettes")

    __table_args__ = (
        UniqueConstraint("maquette_id", "sujet_id", name="uq_maquette_sujet"),
    )


class SuggestionComposantSource(Base, CreatedAtMixin):
    """Source contextuelle de suggestion CDC, jamais validation finale."""

    __tablename__ = "suggestion_composant_source"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_valeur: Mapped[str] = mapped_column(String(50), nullable=False)
    type_composant_id: Mapped[int] = mapped_column(
        ForeignKey("type_composant.id", ondelete="RESTRICT"), nullable=False
    )

    type_composant: Mapped["TypeComposant"] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "source_type",
            "source_valeur",
            "type_composant_id",
            name="uq_suggestion_source_composant",
        ),
    )


# ---------------------------------------------------------------------------
# 5. Homologation
# ---------------------------------------------------------------------------
class Homologation(Base, CreatedAtMixin):
    __tablename__ = "homologation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    maquette_id: Mapped[int] = mapped_column(
        ForeignKey("maquette.id", ondelete="RESTRICT"), nullable=False
    )
    # Cycle de vie du PROCESSUS uniquement. Le résultat de couverture vit
    # exclusivement dans DecisionCouverture — jamais dupliqué ici.
    statut: Mapped[StatutHomologation] = mapped_column(
        Enum(StatutHomologation, native_enum=False),
        nullable=False,
        default=StatutHomologation.EN_ATTENTE,
    )

    # --- Jalons datés, alignés sur le suivi réel Capgemini ---
    # Tous nullable : remplis progressivement au fil du cycle de vie,
    # pas tous connus dès la création de l'Homologation.
    date_livraison_cdc: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    date_cmde: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    date_montage: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    date_validation_fonctionnelle: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    date_deadline_buffer: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    date_deadline: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # Vérité terrain pour l'entraînement du modèle de régression :
    # durée réelle = date_retour_reel - date_cmde (ou date_creation Maquette).
    date_retour_reel: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    maquette: Mapped["Maquette"] = relationship(back_populates="homologations")
    decisions_couverture: Mapped[list["DecisionCouverture"]] = relationship(
        back_populates="homologation"
    )
    # Silhouettes que CETTE homologation couvre pour l'avenir (colonne
    # "Silh couvertes" du suivi réel) — distinct de DecisionCouverture, qui
    # gère le sens inverse ("cette nouvelle maquette est-elle couverte par
    # une homologation existante ?").
    silhouettes_couvertes: Mapped[list["SilhouetteCouverte"]] = relationship(
        back_populates="homologation"
    )

    def __repr__(self) -> str:
        return f"<Homologation id={self.id} statut={self.statut}>"


# ---------------------------------------------------------------------------
# 6bis. SilhouetteCouverte (table pont)
# ---------------------------------------------------------------------------
class SilhouetteCouverte(Base, CreatedAtMixin):
    """Déclare qu'une Homologation couvre une Silhouette donnée pour les
    projets futurs. Alimentée en deux temps :
    1. Suggestion automatique du Coverage Engine (même ArchitectureEE) ;
    2. Validation/ajustement manuel par l'ingénieur homologation.
    """

    __tablename__ = "silhouette_couverte"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    homologation_id: Mapped[int] = mapped_column(
        ForeignKey("homologation.id", ondelete="RESTRICT"), nullable=False
    )
    silhouette_id: Mapped[int] = mapped_column(
        ForeignKey("silhouette.id", ondelete="RESTRICT"), nullable=False
    )
    origine: Mapped[OrigineSuggestion] = mapped_column(
        Enum(OrigineSuggestion, native_enum=False), nullable=False
    )

    homologation: Mapped["Homologation"] = relationship(back_populates="silhouettes_couvertes")
    silhouette: Mapped["Silhouette"] = relationship()

    __table_args__ = (
        UniqueConstraint("homologation_id", "silhouette_id", name="uq_homologation_silhouette"),
    )

    def __repr__(self) -> str:
        return f"<SilhouetteCouverte homologation={self.homologation_id} silhouette={self.silhouette_id} ({self.origine})>"


# ---------------------------------------------------------------------------
# 6. DecisionCouverture
# ---------------------------------------------------------------------------
class DecisionCouverture(Base):
    __tablename__ = "decision_couverture"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    homologation_id: Mapped[int] = mapped_column(
        ForeignKey("homologation.id", ondelete="RESTRICT"), nullable=False
    )
    est_couverte: Mapped[bool] = mapped_column(Boolean, nullable=False)
    projet_couvrant_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("projet.id", ondelete="RESTRICT"), nullable=True
    )
    justification: Mapped[str] = mapped_column(Text, nullable=False)
    date_decision: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )

    homologation: Mapped["Homologation"] = relationship(back_populates="decisions_couverture")
    projet_couvrant: Mapped[Optional["Projet"]] = relationship(
        back_populates="decisions_ou_il_est_couvrant"
    )

    __table_args__ = (
        # Filet de sécurité DB en plus de la validation du domaine :
        # cohérence entre est_couverte et projet_couvrant_id.
        CheckConstraint(
            "(est_couverte = 0 AND projet_couvrant_id IS NULL) "
            "OR (est_couverte = 1 AND projet_couvrant_id IS NOT NULL)",
            name="ck_decision_couverture_coherence",
        ),
    )

    def __repr__(self) -> str:
        return f"<DecisionCouverture homologation={self.homologation_id} couverte={self.est_couverte}>"


# ---------------------------------------------------------------------------
# 7. Prediction
# ---------------------------------------------------------------------------
class Prediction(Base, CreatedAtMixin):
    __tablename__ = "prediction"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    maquette_id: Mapped[int] = mapped_column(
        ForeignKey("maquette.id", ondelete="RESTRICT"), nullable=False
    )
    predicted_duration: Mapped[float] = mapped_column(Float, nullable=False)
    predicted_dll: Mapped[date] = mapped_column(Date, nullable=False)
    confidence_level: Mapped[ConfidenceLevel] = mapped_column(
        Enum(ConfidenceLevel, native_enum=False), nullable=False
    )
    model_name: Mapped[str] = mapped_column(String(50), nullable=False)
    model_version: Mapped[str] = mapped_column(String(20), nullable=False)
    # Type logique JSON -> dict côté Python, pas de json.dumps/loads manuel.
    input_snapshot: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    maquette: Mapped["Maquette"] = relationship(back_populates="predictions")

    __table_args__ = (
        CheckConstraint("predicted_duration > 0", name="ck_prediction_duration_positive"),
        Index("ix_prediction_maquette_created", "maquette_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Prediction maquette={self.maquette_id} dll={self.predicted_dll} ({self.model_name} {self.model_version})>"


# ---------------------------------------------------------------------------
# 8. PlanningConstruction
# ---------------------------------------------------------------------------
class PlanningConstruction(Base, CreatedAtMixin, UpdatedAtMixin):
    __tablename__ = "planning_construction"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    maquette_id: Mapped[int] = mapped_column(
        ForeignKey("maquette.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    statut_avancement: Mapped[StatutAvancement] = mapped_column(
        Enum(StatutAvancement, native_enum=False),
        nullable=False,
        default=StatutAvancement.PLANIFIEE,
    )
    # Score unique — les composantes (deadline_urgency, delay_penalty,
    # business_priority) sont calculées à la volée par le domaine
    # (PriorityCalculator), jamais persistées séparément.
    # Pas de champ DLL ici : toujours lu depuis la dernière Prediction valide.
    priorite_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    maquette: Mapped["Maquette"] = relationship(back_populates="planning")
    etapes: Mapped[list["EtapeConstruction"]] = relationship(
        back_populates="planning", order_by="EtapeConstruction.ordre"
    )

    __table_args__ = (
        CheckConstraint(
            "priorite_score IS NULL OR priorite_score >= 0",
            name="ck_planning_priorite_non_negative",
        ),
    )

    def __repr__(self) -> str:
        return f"<PlanningConstruction maquette={self.maquette_id} priorite={self.priorite_score}>"


# ---------------------------------------------------------------------------
# 9. EtapeConstruction
# ---------------------------------------------------------------------------
class EtapeConstruction(Base, CreatedAtMixin):
    __tablename__ = "etape_construction"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    planning_id: Mapped[int] = mapped_column(
        ForeignKey("planning_construction.id", ondelete="RESTRICT"), nullable=False
    )
    ordre: Mapped[int] = mapped_column(Integer, nullable=False)
    libelle: Mapped[str] = mapped_column(String(100), nullable=False)
    date_debut: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    date_fin: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    statut: Mapped[StatutEtape] = mapped_column(
        Enum(StatutEtape, native_enum=False), nullable=False, default=StatutEtape.A_FAIRE
    )

    planning: Mapped["PlanningConstruction"] = relationship(back_populates="etapes")

    __table_args__ = (
        UniqueConstraint("planning_id", "ordre", name="uq_etape_planning_ordre"),
        CheckConstraint("ordre > 0", name="ck_etape_ordre_positive"),
    )

    def __repr__(self) -> str:
        return f"<EtapeConstruction {self.libelle} (ordre={self.ordre})>"


# ---------------------------------------------------------------------------
# 10. Notification
# ---------------------------------------------------------------------------
class Notification(Base):
    __tablename__ = "notification"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    utilisateur_id: Mapped[int] = mapped_column(
        ForeignKey("utilisateur.id", ondelete="RESTRICT"), nullable=False
    )
    type: Mapped[TypeNotification] = mapped_column(
        Enum(TypeNotification, native_enum=False), nullable=False
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    date_envoi: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )
    lu: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    utilisateur: Mapped["Utilisateur"] = relationship(back_populates="notifications")

    __table_args__ = (
        Index("ix_notification_utilisateur_lu", "utilisateur_id", "lu"),
    )

    def __repr__(self) -> str:
        return f"<Notification {self.type} utilisateur={self.utilisateur_id} lu={self.lu}>"


# ---------------------------------------------------------------------------
# 11. AuditLog
# ---------------------------------------------------------------------------
class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Nullable : une action système (ex. réordonnancement automatique du
    # planning) n'a pas d'utilisateur humain associé.
    utilisateur_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("utilisateur.id", ondelete="RESTRICT"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        nullable=False, server_default=func.now()
    )
    details: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    utilisateur: Mapped[Optional["Utilisateur"]] = relationship(back_populates="audit_logs")

    __table_args__ = (
        Index("ix_audit_entity", "entity_type", "entity_id"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog {self.action} {self.entity_type}#{self.entity_id}>"
