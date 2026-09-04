"""
Données initiales de la base R116.

Le seed est volontairement idempotent :
- exécuter le script plusieurs fois ne doit pas créer de doublons ;
- les référentiels existants sont conservés ;
- un compte ADMIN est créé uniquement s'il n'existe pas.

IMPORTANT :
Le mot de passe ci-dessous est uniquement destiné au développement local.
Il devra être remplacé avant toute utilisation réelle.
"""

from __future__ import annotations

import re
import secrets
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from app.application.auth.services import hash_password
from app.config.settings import BASE_DIR
from app.domain.planning.gabarit_service import DUREE_CDC_CMDE, generer_planning_theorique
from app.shared.component_codes import TYPE_COMPOSANT_CODES_OFFICIELS
from app.shared.paths import obtenir_dossier_downloads
from app.shared.subject_parser import parser_sujets
from .database import SessionLocal
from .models import (
    ArchitectureEE,
    AuditLog,
    DecisionCouverture,
    EtapeConstruction,
    Fournisseur,
    Homologation,
    LigneCDC,
    Maquette,
    MaquetteSujet,
    Notification,
    PlanningConstruction,
    Prediction,
    Projet,
    Silhouette,
    SilhouetteCouverte,
    Sujet,
    SuggestionComposantSource,
    TypeComposant,
    Utilisateur,
)
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


# ============================================================================
# DONNÉES DE SEED
# ============================================================================

SILHOUETTES = [
    "P18",
    "P21",
    "P22",
    "Y18",
]

ARCHITECTURES_EE = [
    {
        "reference": "ARCH-EE-001",
        "version": "V1",
    },
    {
        "reference": "ARCH-EE-002",
        "version": "V1",
    },
    {
        "reference": "EE-X9",
        "version": "V1",
    },
    {
        "reference": "ARCH-EE-CDC",
        "version": "HIST",
    },
]

FOURNISSEURS = [
    "FOURNISSEUR_A",
    "FOURNISSEUR_B",
]

TYPES_COMPOSANTS = [
    {
        "code": "Affectation",
        "description": "Affectation composant",
    },
    *(
        {
            "code": code,
            "description": f"Type de composant {code}",
        }
        for code in TYPE_COMPOSANT_CODES_OFFICIELS
        if code != "Affectation"
    ),
]

ADMIN_USERNAME = "admin"

# IMPORTANT :
# Mot de passe de développement uniquement.
# Le hash doit etre genere avec Argon2.
# Ne jamais stocker un mot de passe en clair dans la base.
ADMIN_PASSWORD_FILENAME = "R116_admin_password_PREMIERE_CONNEXION.txt"
RAW_CDC_DIR = BASE_DIR / "data" / "raw" / "cdc"
RAW_PROJECTS_PATH = BASE_DIR / "data" / "raw" / "projects" / "Suivi_Homologation_R116.xlsx"


# ============================================================================
# SEED REFERENTIELS
# ============================================================================

def seed_silhouettes(session) -> None:
    """Insère les silhouettes absentes."""

    for libelle in SILHOUETTES:
        existing = session.scalar(
            select(Silhouette).where(
                Silhouette.libelle == libelle
            )
        )

        if existing is None:
            session.add(
                Silhouette(
                    libelle=libelle,
                )
            )


def seed_architectures(session) -> None:
    """Insère les architectures EE absentes."""

    for data in ARCHITECTURES_EE:
        existing = session.scalar(
            select(ArchitectureEE).where(
                ArchitectureEE.reference == data["reference"]
            )
        )

        if existing is None:
            session.add(
                ArchitectureEE(
                    reference=data["reference"],
                    version=data["version"],
                )
            )


def seed_fournisseurs(session) -> None:
    """Insère les fournisseurs absents."""

    for nom in FOURNISSEURS:
        existing = session.scalar(
            select(Fournisseur).where(
                Fournisseur.nom == nom
            )
        )

        if existing is None:
            session.add(
                Fournisseur(
                    nom=nom,
                )
            )


def seed_types_composants(session) -> None:
    """Insère les types de composants absents."""

    for data in TYPES_COMPOSANTS:
        existing = session.scalar(
            select(TypeComposant).where(
                TypeComposant.code == data["code"]
            )
        )

        if existing is None:
            session.add(
                TypeComposant(
                    code=data["code"],
                    description=data["description"],
                )
            )
        elif data.get("description") and existing.description != data["description"]:
            existing.description = data["description"]
    session.flush()


def seed_historical_cdc(session) -> None:
    """Importe les anciens CDC Excel en projets/maquettes historiques."""

    if not RAW_CDC_DIR.exists():
        return

    for path in sorted(RAW_CDC_DIR.glob("*.xlsx")):
        if path.name.lower() == "pieces_cdc_codes.xlsx":
            seed_pieces_cdc_codes_workbook(session, path)
            continue

        title, lignes = parse_cdc_workbook(path)
        if not lignes:
            continue

        reference = f"HIST-{path.stem.upper().replace(' ', '-')}"
        existing_project = session.scalar(
            select(Projet).where(Projet.reference == reference)
        )
        if existing_project is not None:
            continue

        silhouette_label = extract_silhouette(title)
        modele = extract_modele(title)

        silhouette = get_or_create_silhouette(session, silhouette_label)
        architecture = get_or_create_architecture(session, "ARCH-EE-CDC", "HIST")
        fournisseur = get_or_create_fournisseur(session, "FOURNISSEUR_A")
        admin = session.scalar(select(Utilisateur).where(Utilisateur.username == ADMIN_USERNAME))
        if admin is None:
            seed_admin(session)
            session.flush()
            admin = session.scalar(
                select(Utilisateur).where(Utilisateur.username == ADMIN_USERNAME)
            )
        if admin is None:
            raise RuntimeError("Compte admin introuvable pour importer les CDC")

        projet = Projet(
            reference=reference,
            date_creation=date_today(),
            created_by_id=admin.id,
        )
        session.add(projet)
        session.flush()

        maquette = Maquette(
            projet_id=projet.id,
            silhouette_id=silhouette.id,
            architecture_ee_id=architecture.id,
            fournisseur_id=fournisseur.id,
            composant_modifie="Nomenclature CDC historique",
            type_homologation=TypeHomologation.MAQUETTE,
            modele=modele,
            date_creation=date_today(),
        )
        session.add(maquette)
        session.flush()

        for code, quantite in lignes:
            type_composant = get_or_create_type_composant(session, code)
            session.add(
                LigneCDC(
                    maquette_id=maquette.id,
                    type_composant_id=type_composant.id,
                    quantite_hw=quantite,
                    origine=OrigineSuggestion.VALIDATION_INGENIEUR,
                )
            )


def seed_sujets_depuis_suivi_historique(session) -> None:
    """Complete le referentiel Sujet avec les codes vus dans le suivi reel."""

    if not RAW_PROJECTS_PATH.exists():
        return
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise RuntimeError(
            "Le package 'openpyxl' est necessaire pour importer les sujets historiques."
        ) from exc

    workbook = load_workbook(RAW_PROJECTS_PATH, read_only=True, data_only=True)
    worksheet = workbook.active
    rows = list(worksheet.iter_rows(values_only=True))
    if not rows:
        return
    headers = [str(value).strip().lower() if value is not None else "" for value in rows[0]]
    try:
        sujet_index = headers.index("sujet")
    except ValueError:
        return
    for row in rows[1:]:
        value = row[sujet_index] if sujet_index < len(row) else None
        for code in parser_sujets(str(value) if value is not None else ""):
            get_or_create_sujet(
                session,
                code,
                description="Sujet extrait du suivi historique R116",
            )


def seed_suivi_homologation_projects(session) -> None:
    """Importe les 20 maquettes reelles du suivi homologation R116."""

    if not RAW_PROJECTS_PATH.exists():
        return
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise RuntimeError(
            "Le package 'openpyxl' est necessaire pour importer le suivi R116."
        ) from exc

    admin = session.scalar(select(Utilisateur).where(Utilisateur.username == ADMIN_USERNAME))
    if admin is None:
        seed_admin(session)
        session.flush()
        admin = session.scalar(select(Utilisateur).where(Utilisateur.username == ADMIN_USERNAME))
    if admin is None:
        raise RuntimeError("Compte admin introuvable pour importer le suivi R116")

    fournisseur = get_or_create_fournisseur(session, "FOURNISSEUR_NON_RENSEIGNE")
    workbook = load_workbook(RAW_PROJECTS_PATH, read_only=True, data_only=True)
    worksheet = workbook.active
    rows = list(worksheet.iter_rows(values_only=True))
    if not rows:
        return
    headers = [str(value).strip() if value is not None else "" for value in rows[0]]

    for index, row in enumerate(rows[1:], start=1):
        data = {
            header: row[column_index] if column_index < len(row) else None
            for column_index, header in enumerate(headers)
        }
        pro = _clean_raw_token(data.get("Pro")) or f"LIGNE{index:02d}"
        mot = _clean_raw_token(data.get("Mot")) or "M0"
        silhouette_label = _clean_raw_token(data.get("Silh hom.")) or "NON_RENSEIGNE"
        sujet_text = str(data.get("Sujet") or "").strip()
        reference = f"SUIVI-R116-{index:02d}-{_slug_reference(pro)}-{_slug_reference(mot)}-{_slug_reference(silhouette_label)}"[:50]
        if session.scalar(select(Projet).where(Projet.reference == reference)) is not None:
            continue

        silhouette = get_or_create_silhouette(session, silhouette_label)
        architecture = get_or_create_architecture(session, pro, "SUIVI")
        projet = Projet(
            reference=reference,
            date_creation=_parse_raw_date(data.get("Livraison du CDC")) or date_today(),
            statut=_statut_projet_from_raw(data.get("Statut")),
            created_by_id=admin.id,
        )
        session.add(projet)
        session.flush()

        maquette = Maquette(
            projet_id=projet.id,
            silhouette_id=silhouette.id,
            architecture_ee_id=architecture.id,
            fournisseur_id=fournisseur.id,
            composant_modifie=sujet_text or "Sujet non renseigne",
            type_homologation=TypeHomologation.MAQUETTE,
            modele=mot,
            date_creation=_parse_raw_date(data.get("Livraison du CDC")) or date_today(),
        )
        session.add(maquette)
        session.flush()
        associer_sujets_maquette(
            session,
            maquette.id,
            parser_sujets(sujet_text),
            description="Sujet extrait du suivi historique R116",
        )

        homologation = Homologation(
            maquette_id=maquette.id,
            statut=_statut_homologation_from_raw(data.get("Statut")),
            date_livraison_cdc=_parse_raw_date(data.get("Livraison du CDC")),
            date_cmde=_parse_raw_date(data.get("CMDE")),
            date_montage=_parse_raw_date(data.get("montage")),
            date_validation_fonctionnelle=_parse_raw_date(data.get("Validation fonctionnelle")),
            date_deadline_buffer=_parse_raw_date(data.get("Dead Line avec BUFFER")),
            date_deadline=_parse_raw_date(data.get("Dead Line")),
            date_retour_reel=_parse_raw_date(data.get("DLL de retour")),
        )
        session.add(homologation)
        session.flush()

        planning = PlanningConstruction(
            maquette_id=maquette.id,
            statut_avancement=_statut_avancement_from_raw(data.get("Statut")),
            priorite_score=0.0,
        )
        session.add(planning)
        session.flush()
        _add_real_steps_from_tracking_row(session, planning.id, data)


def seed_pieces_cdc_codes_workbook(session, path: Path) -> None:
    """Importe le classeur enrichi Pieces_CDC_codes par configuration."""

    configs, descriptions = parse_pieces_cdc_codes_workbook(path)
    for code, description in descriptions.items():
        get_or_create_type_composant(session, code, description=description)
    seed_suggestion_sources_from_workbook(session, path, descriptions)

    admin = session.scalar(select(Utilisateur).where(Utilisateur.username == ADMIN_USERNAME))
    if admin is None:
        seed_admin(session)
        session.flush()
        admin = session.scalar(select(Utilisateur).where(Utilisateur.username == ADMIN_USERNAME))
    if admin is None:
        raise RuntimeError("Compte admin introuvable pour importer Pieces_CDC_codes")

    architecture = get_or_create_architecture(session, "ARCH-EE-PIECES-CDC", "HIST")
    fournisseur = get_or_create_fournisseur(session, "FOURNISSEUR_A")
    for config in configs:
        title = config["title"]
        reference = f"HIST-PIECES-{_slug_reference(title)}"[:50]
        if session.scalar(select(Projet).where(Projet.reference == reference)) is not None:
            continue

        silhouette = get_or_create_silhouette(session, extract_silhouette(title))
        projet = Projet(
            reference=reference,
            date_creation=date_today(),
            created_by_id=admin.id,
        )
        session.add(projet)
        session.flush()

        maquette = Maquette(
            projet_id=projet.id,
            silhouette_id=silhouette.id,
            architecture_ee_id=architecture.id,
            fournisseur_id=fournisseur.id,
            composant_modifie=f"Nomenclature Pieces_CDC_codes - {title}",
            type_homologation=TypeHomologation.MAQUETTE,
            modele=extract_modele(title),
            date_creation=date_today(),
        )
        session.add(maquette)
        session.flush()
        associer_sujets_maquette(
            session,
            maquette.id,
            parser_sujets(title),
            description=f"Sujet extrait de {title}",
        )

        for code, quantite in config["lignes"]:
            type_composant = get_or_create_type_composant(
                session,
                code,
                description=descriptions.get(code),
            )
            session.add(
                LigneCDC(
                    maquette_id=maquette.id,
                    type_composant_id=type_composant.id,
                    quantite_hw=quantite,
                    origine=OrigineSuggestion.VALIDATION_INGENIEUR,
                )
            )


# ============================================================================
# SEED DONNEES DEMO
# ============================================================================

def seed_demo_data(session) -> None:
    """Ajoute un jeu de donnees de demonstration pour visualiser l'app."""

    admin = session.scalar(select(Utilisateur).where(Utilisateur.username == ADMIN_USERNAME))
    if admin is None:
        seed_admin(session)
        session.flush()
        admin = session.scalar(select(Utilisateur).where(Utilisateur.username == ADMIN_USERNAME))
    if admin is None:
        raise RuntimeError("Compte admin introuvable pour creer les donnees demo")

    engineer = get_or_create_user(
        session,
        username="ingenieur",
        password="ingenieur123",
        role=RoleUtilisateur.INGENIEUR,
    )
    planner = get_or_create_user(
        session,
        username="planner",
        password="planner123",
        role=RoleUtilisateur.PLANNER,
    )

    today = date.today()
    p18 = get_or_create_silhouette(session, "P18")
    y18 = get_or_create_silhouette(session, "Y18")
    p21 = get_or_create_silhouette(session, "P21")
    arch_x9 = get_or_create_architecture(session, "EE-X9", "V1")
    arch_002 = get_or_create_architecture(session, "ARCH-EE-002", "V1")
    fournisseur_a = get_or_create_fournisseur(session, "FOURNISSEUR_A")
    fournisseur_b = get_or_create_fournisseur(session, "FOURNISSEUR_B")

    cover_project, cover_created = get_or_create_project(
        session,
        reference="DEMO-COVER-HIST",
        created_by_id=admin.id,
        date_creation=today - timedelta(days=360),
        statut=StatutProjet.TERMINEE,
    )
    cover_maquette = get_or_create_maquette(
        session,
        projet_id=cover_project.id,
        silhouette_id=y18.id,
        architecture_ee_id=arch_x9.id,
        fournisseur_id=fournisseur_a.id,
        composant_modifie="Calculateur ADAS",
        type_homologation=TypeHomologation.MAQUETTE,
        modele="M2",
        date_creation=today - timedelta(days=350),
    )
    add_cdc_lines(
        session,
        cover_maquette.id,
        [
            ("T1", 2, OrigineSuggestion.VALIDATION_INGENIEUR),
            ("P3", 1, OrigineSuggestion.VALIDATION_INGENIEUR),
            ("T2", 3, OrigineSuggestion.VALIDATION_INGENIEUR),
            ("C4", 1, OrigineSuggestion.VALIDATION_INGENIEUR),
        ],
    )
    cover_homologation = get_or_create_homologation(
        session,
        maquette_id=cover_maquette.id,
        statut=StatutHomologation.TERMINEE,
        date_livraison_cdc=today - timedelta(days=330),
        date_cmde=today - timedelta(days=281),
        date_montage=today - timedelta(days=183),
        date_validation_fonctionnelle=today - timedelta(days=148),
        date_deadline_buffer=today - timedelta(days=92),
        date_deadline=today - timedelta(days=50),
        date_retour_reel=today - timedelta(days=40),
    )
    add_silhouette_couverte(session, cover_homologation.id, y18.id, OrigineSuggestion.VALIDATION_INGENIEUR)
    add_silhouette_couverte(session, cover_homologation.id, p18.id, OrigineSuggestion.VALIDATION_INGENIEUR)
    cover_planning = get_or_create_planning(
        session,
        maquette_id=cover_maquette.id,
        statut=StatutAvancement.TERMINEE,
        priorite_score=0.0,
    )
    replace_with_theoretical_steps(
        session,
        cover_planning.id,
        cover_homologation.date_cmde,
        residu_predit=10,
        statuses=[StatutEtape.TERMINEE] * 6,
    )

    covered_project, _ = get_or_create_project(
        session,
        reference="DEMO-COVER-CANDIDATE",
        created_by_id=engineer.id,
        date_creation=today - timedelta(days=20),
        statut=StatutProjet.EN_COURS,
    )
    covered_maquette = get_or_create_maquette(
        session,
        projet_id=covered_project.id,
        silhouette_id=y18.id,
        architecture_ee_id=arch_x9.id,
        fournisseur_id=fournisseur_a.id,
        composant_modifie="Radar avant",
        type_homologation=TypeHomologation.MAQUETTE,
        modele="M2-BIS",
        date_creation=today - timedelta(days=18),
    )
    add_cdc_lines(
        session,
        covered_maquette.id,
        [
            ("T1", 2, OrigineSuggestion.SUGGESTION_AUTO),
            ("P3", 1, OrigineSuggestion.SUGGESTION_AUTO),
            ("T2", 3, OrigineSuggestion.SUGGESTION_AUTO),
        ],
    )
    covered_homologation = get_or_create_homologation(
        session,
        maquette_id=covered_maquette.id,
        statut=StatutHomologation.EN_ATTENTE,
        date_livraison_cdc=today - timedelta(days=15),
        date_cmde=today + timedelta(days=34),
        date_deadline=today + timedelta(days=231),
    )
    covered_planning = get_or_create_planning(
        session,
        maquette_id=covered_maquette.id,
        statut=StatutAvancement.PLANIFIEE,
        priorite_score=620.0,
    )
    replace_with_theoretical_steps(
        session,
        covered_planning.id,
        covered_homologation.date_cmde,
        residu_predit=0,
        statuses=[
            StatutEtape.A_FAIRE,
            StatutEtape.A_FAIRE,
            StatutEtape.A_FAIRE,
            StatutEtape.A_FAIRE,
            StatutEtape.A_FAIRE,
            StatutEtape.A_FAIRE,
        ],
    )
    decision = add_decision_couverture(
        session,
        homologation_id=covered_homologation.id,
        est_couverte=True,
        projet_couvrant_id=cover_project.id,
        justification="Suggestion demo validee : architecture EE-X9 deja homologuee sur DEMO-COVER-HIST.",
    )
    if decision is not None:
        session.flush()
        session.add(
            AuditLog(
                utilisateur_id=engineer.id,
                action="CREATE_DECISION_COUVERTURE",
                entity_type="DecisionCouverture",
                entity_id=decision.id,
                details={"source": "seed_demo_data"},
            )
        )

    late_project, _ = get_or_create_project(
        session,
        reference="DEMO-RETARD",
        created_by_id=planner.id,
        date_creation=today - timedelta(days=140),
        statut=StatutProjet.EN_COURS,
    )
    late_maquette = get_or_create_maquette(
        session,
        projet_id=late_project.id,
        silhouette_id=p21.id,
        architecture_ee_id=arch_002.id,
        fournisseur_id=fournisseur_b.id,
        composant_modifie="Faisceau habitacle",
        type_homologation=TypeHomologation.VEHICULE,
        modele="M5",
        date_creation=today - timedelta(days=130),
    )
    late_homologation = get_or_create_homologation(
        session,
        maquette_id=late_maquette.id,
        statut=StatutHomologation.EN_COURS,
        date_livraison_cdc=today - timedelta(days=120),
        date_cmde=today - timedelta(days=71),
        date_montage=today - timedelta(days=12),
        date_deadline=today - timedelta(days=7),
    )
    add_prediction(
        session,
        maquette_id=late_maquette.id,
        predicted_duration=265.0,
        predicted_dll=today + timedelta(days=64),
        confidence_level=ConfidenceLevel.LOW,
        input_snapshot={"demo": True, "trace": ["DEMO-COVER-HIST"]},
    )
    late_planning = get_or_create_planning(
        session,
        maquette_id=late_maquette.id,
        statut=StatutAvancement.EN_COURS,
        priorite_score=10_007.0,
    )
    replace_with_theoretical_steps(
        session,
        late_planning.id,
        late_homologation.date_cmde,
        residu_predit=0,
        statuses=[
            StatutEtape.TERMINEE,
            StatutEtape.EN_COURS,
            StatutEtape.A_FAIRE,
            StatutEtape.A_FAIRE,
            StatutEtape.A_FAIRE,
            StatutEtape.A_FAIRE,
        ],
    )

    active_project, _ = get_or_create_project(
        session,
        reference="DEMO-EN-COURS",
        created_by_id=engineer.id,
        date_creation=today - timedelta(days=45),
        statut=StatutProjet.EN_COURS,
    )
    active_maquette = get_or_create_maquette(
        session,
        projet_id=active_project.id,
        silhouette_id=p18.id,
        architecture_ee_id=arch_x9.id,
        fournisseur_id=fournisseur_a.id,
        composant_modifie="Colonne direction",
        type_homologation=TypeHomologation.COLONNE_DIRECTION,
        modele="M3",
        date_creation=today - timedelta(days=42),
    )
    active_homologation = get_or_create_homologation(
        session,
        maquette_id=active_maquette.id,
        statut=StatutHomologation.EN_COURS,
        date_livraison_cdc=today - timedelta(days=30),
        date_cmde=today + timedelta(days=19),
        date_deadline=today + timedelta(days=140),
    )
    add_prediction(
        session,
        maquette_id=active_maquette.id,
        predicted_duration=231.0,
        predicted_dll=today + timedelta(days=189),
        confidence_level=ConfidenceLevel.HIGH,
        input_snapshot={"demo": True, "modele": "baseline_gabarit_231"},
    )
    active_planning = get_or_create_planning(
        session,
        maquette_id=active_maquette.id,
        statut=StatutAvancement.PLANIFIEE,
        priorite_score=860.0,
    )
    replace_with_theoretical_steps(
        session,
        active_planning.id,
        active_homologation.date_cmde,
        residu_predit=0,
        statuses=[
            StatutEtape.TERMINEE,
            StatutEtape.A_FAIRE,
            StatutEtape.A_FAIRE,
            StatutEtape.A_FAIRE,
            StatutEtape.A_FAIRE,
            StatutEtape.A_FAIRE,
        ],
    )

    done_project, _ = get_or_create_project(
        session,
        reference="DEMO-TERMINE",
        created_by_id=admin.id,
        date_creation=today - timedelta(days=300),
        statut=StatutProjet.TERMINEE,
    )
    done_maquette = get_or_create_maquette(
        session,
        projet_id=done_project.id,
        silhouette_id=p18.id,
        architecture_ee_id=arch_002.id,
        fournisseur_id=fournisseur_b.id,
        composant_modifie="Boitier gateway",
        type_homologation=TypeHomologation.MAQUETTE,
        modele="M1",
        date_creation=today - timedelta(days=295),
    )
    done_homologation = get_or_create_homologation(
        session,
        maquette_id=done_maquette.id,
        statut=StatutHomologation.TERMINEE,
        date_livraison_cdc=today - timedelta(days=280),
        date_cmde=today - timedelta(days=231),
        date_montage=today - timedelta(days=133),
        date_validation_fonctionnelle=today - timedelta(days=98),
        date_deadline_buffer=today - timedelta(days=42),
        date_deadline=today,
        date_retour_reel=today,
    )
    done_planning = get_or_create_planning(
        session,
        maquette_id=done_maquette.id,
        statut=StatutAvancement.TERMINEE,
        priorite_score=0.0,
    )
    replace_with_theoretical_steps(
        session,
        done_planning.id,
        done_homologation.date_cmde,
        residu_predit=0,
        statuses=[StatutEtape.TERMINEE] * 6,
    )

    seed_demo_gantt_rows(
        session,
        owner_id=planner.id,
        today=today,
        silhouettes=[p18, p21, y18],
        architectures=[arch_x9, arch_002],
        fournisseurs=[fournisseur_a, fournisseur_b],
    )

    add_notification(
        session,
        utilisateur_id=admin.id,
        type_notification=TypeNotification.CHANGEMENT_STATUT,
        message="Demo : le projet DEMO-EN-COURS est passe en cours.",
        lu=False,
    )
    add_notification(
        session,
        utilisateur_id=admin.id,
        type_notification=TypeNotification.ALERTE_RETARD,
        message=f"Retard detecte sur maquette {late_maquette.id} : homologation {late_homologation.id} depassee de 7 jours.",
        lu=False,
    )
    add_notification(
        session,
        utilisateur_id=admin.id,
        type_notification=TypeNotification.RAPPORT_GENERE,
        message="Demo : CDC genere pour DEMO-COVER-CANDIDATE.",
        lu=True,
    )

    if cover_created:
        print("[OK] Donnees demo ajoutees : projets, maquettes, homologations, planning, predictions.")


# ============================================================================
# SEED UTILISATEUR ADMIN
# ============================================================================

def seed_admin(session) -> Path | None:
    """
    Crée le compte administrateur initial s'il n'existe pas.

    Le compte est créé actif et avec le rôle ADMIN.
    """

    existing = session.scalar(
        select(Utilisateur).where(
            Utilisateur.username == ADMIN_USERNAME
        )
    )

    if existing is not None:
        return None

    mot_de_passe = secrets.token_urlsafe(12)

    admin = Utilisateur(
        username=ADMIN_USERNAME,
        password_hash=hash_password(mot_de_passe),
        role=RoleUtilisateur.ADMIN,
        is_active=True,
    )

    session.add(admin)
    message = (
        f"Compte admin cree - mot de passe : {mot_de_passe}\n"
        "(Ce fichier ne sera plus regenere apres le premier lancement.)"
    )
    print(message)
    chemin_fichier = obtenir_dossier_downloads() / ADMIN_PASSWORD_FILENAME
    chemin_fichier.write_text(message, encoding="utf-8")
    return chemin_fichier


def get_or_create_user(
    session,
    username: str,
    password: str,
    role: RoleUtilisateur,
) -> Utilisateur:
    row = session.scalar(select(Utilisateur).where(Utilisateur.username == username))
    if row is None:
        row = Utilisateur(
            username=username,
            password_hash=hash_password(password),
            role=role,
            is_active=True,
        )
        session.add(row)
        session.flush()
    return row


def get_or_create_project(
    session,
    reference: str,
    created_by_id: int,
    date_creation: date,
    statut: StatutProjet,
) -> tuple[Projet, bool]:
    row = session.scalar(select(Projet).where(Projet.reference == reference))
    if row is not None:
        return row, False
    row = Projet(
        reference=reference,
        date_creation=date_creation,
        statut=statut,
        created_by_id=created_by_id,
    )
    session.add(row)
    session.flush()
    return row, True


def get_or_create_maquette(
    session,
    projet_id: int,
    silhouette_id: int,
    architecture_ee_id: int,
    fournisseur_id: int,
    composant_modifie: str,
    type_homologation: TypeHomologation,
    modele: str,
    date_creation: date,
) -> Maquette:
    row = session.scalar(select(Maquette).where(Maquette.projet_id == projet_id))
    if row is not None:
        return row
    row = Maquette(
        projet_id=projet_id,
        silhouette_id=silhouette_id,
        architecture_ee_id=architecture_ee_id,
        fournisseur_id=fournisseur_id,
        composant_modifie=composant_modifie,
        type_homologation=type_homologation,
        modele=modele,
        date_creation=date_creation,
    )
    session.add(row)
    session.flush()
    return row


def get_or_create_homologation(
    session,
    maquette_id: int,
    statut: StatutHomologation,
    date_livraison_cdc: date | None = None,
    date_cmde: date | None = None,
    date_montage: date | None = None,
    date_validation_fonctionnelle: date | None = None,
    date_deadline_buffer: date | None = None,
    date_deadline: date | None = None,
    date_retour_reel: date | None = None,
) -> Homologation:
    row = session.scalar(select(Homologation).where(Homologation.maquette_id == maquette_id))
    if row is not None:
        return row
    row = Homologation(
        maquette_id=maquette_id,
        statut=statut,
        date_livraison_cdc=date_livraison_cdc,
        date_cmde=date_cmde,
        date_montage=date_montage,
        date_validation_fonctionnelle=date_validation_fonctionnelle,
        date_deadline_buffer=date_deadline_buffer,
        date_deadline=date_deadline,
        date_retour_reel=date_retour_reel,
    )
    session.add(row)
    session.flush()
    return row


def get_or_create_planning(
    session,
    maquette_id: int,
    statut: StatutAvancement,
    priorite_score: float,
) -> PlanningConstruction:
    row = session.scalar(
        select(PlanningConstruction).where(PlanningConstruction.maquette_id == maquette_id)
    )
    if row is not None:
        return row
    row = PlanningConstruction(
        maquette_id=maquette_id,
        statut_avancement=statut,
        priorite_score=priorite_score,
    )
    session.add(row)
    session.flush()
    return row


def add_planning_steps(
    session,
    planning_id: int,
    steps: list[tuple[int, str, date | None, date | None, StatutEtape]],
) -> None:
    for ordre, libelle, date_debut, date_fin, statut in steps:
        existing = session.scalar(
            select(EtapeConstruction).where(
                EtapeConstruction.planning_id == planning_id,
                EtapeConstruction.ordre == ordre,
            )
        )
        if existing is None:
            session.add(
                EtapeConstruction(
                    planning_id=planning_id,
                    ordre=ordre,
                    libelle=libelle,
                    date_debut=date_debut,
                    date_fin=date_fin,
                    statut=statut,
                )
            )


def replace_with_theoretical_steps(
    session,
    planning_id: int,
    date_cmde: date | None,
    residu_predit: int = 0,
    statuses: list[StatutEtape] | None = None,
) -> None:
    """Garantit les etapes planifiees, depuis le CDC, pour les maquettes demo."""

    if date_cmde is None:
        planning = session.get(PlanningConstruction, planning_id)
        maquette = session.get(Maquette, planning.maquette_id) if planning else None
        date_cmde = (maquette.date_creation if maquette and maquette.date_creation else date.today()) + timedelta(
            days=DUREE_CDC_CMDE
        )

    date_livraison_cdc = date_cmde - timedelta(days=DUREE_CDC_CMDE)
    expected = generer_planning_theorique(date_livraison_cdc, residu_predit=residu_predit)
    existing = list(
        session.scalars(
            select(EtapeConstruction)
            .where(EtapeConstruction.planning_id == planning_id)
            .order_by(EtapeConstruction.ordre)
        )
    )
    is_complete = (
        len(existing) == len(expected)
        and all(step.date_debut is not None and step.date_fin is not None for step in existing)
    )
    if is_complete:
        return

    for step in existing:
        session.delete(step)
    session.flush()

    statuses = statuses or [StatutEtape.A_FAIRE] * len(expected)
    for ordre, etape in enumerate(expected, start=1):
        session.add(
            EtapeConstruction(
                planning_id=planning_id,
                ordre=ordre,
                libelle=etape.libelle,
                date_debut=etape.date_debut_estimee,
                date_fin=etape.date_fin_estimee,
                statut=statuses[ordre - 1] if ordre <= len(statuses) else StatutEtape.A_FAIRE,
            )
        )


def seed_demo_gantt_rows(
    session,
    owner_id: int,
    today: date,
    silhouettes: list[Silhouette],
    architectures: list[ArchitectureEE],
    fournisseurs: list[Fournisseur],
) -> None:
    """Ajoute assez de lignes DEMO-GANTT pour tester le scroll vertical du Gantt."""

    for index in range(1, 9):
        project, _ = get_or_create_project(
            session,
            reference=f"DEMO-GANTT-{index:02d}",
            created_by_id=owner_id,
            date_creation=today - timedelta(days=70 + index * 7),
            statut=StatutProjet.EN_COURS if index % 4 else StatutProjet.PLANIFIEE,
        )
        maquette = get_or_create_maquette(
            session,
            projet_id=project.id,
            silhouette_id=silhouettes[index % len(silhouettes)].id,
            architecture_ee_id=architectures[index % len(architectures)].id,
            fournisseur_id=fournisseurs[index % len(fournisseurs)].id,
            composant_modifie=f"Scenario Gantt {index}",
            type_homologation=TypeHomologation.MAQUETTE if index % 2 else TypeHomologation.VEHICULE,
            modele=f"MG-{index:02d}",
            date_creation=today - timedelta(days=60 + index * 5),
        )
        date_cmde = today - timedelta(days=90 - index * 9)
        homologation = get_or_create_homologation(
            session,
            maquette_id=maquette.id,
            statut=StatutHomologation.EN_COURS,
            date_livraison_cdc=date_cmde - timedelta(days=DUREE_CDC_CMDE),
            date_cmde=date_cmde,
            date_deadline=date_cmde + timedelta(days=231 + (index % 3) * 12),
        )
        planning = get_or_create_planning(
            session,
            maquette_id=maquette.id,
            statut=StatutAvancement.EN_COURS if index % 3 else StatutAvancement.PLANIFIEE,
            priorite_score=float(900 - index * 45),
        )
        statuses = [
            StatutEtape.TERMINEE,
            StatutEtape.TERMINEE if index % 2 else StatutEtape.EN_COURS,
            StatutEtape.EN_COURS if index % 2 else StatutEtape.A_FAIRE,
            StatutEtape.A_FAIRE,
            StatutEtape.A_FAIRE,
            StatutEtape.A_FAIRE,
        ]
        replace_with_theoretical_steps(
            session,
            planning.id,
            homologation.date_cmde,
            residu_predit=(index % 4) * 6,
            statuses=statuses,
        )


def add_cdc_lines(
    session,
    maquette_id: int,
    lignes: list[tuple[str, int, OrigineSuggestion]],
) -> None:
    for code, quantite, origine in lignes:
        type_composant = get_or_create_type_composant(session, code)
        existing = session.scalar(
            select(LigneCDC).where(
                LigneCDC.maquette_id == maquette_id,
                LigneCDC.type_composant_id == type_composant.id,
            )
        )
        if existing is None:
            session.add(
                LigneCDC(
                    maquette_id=maquette_id,
                    type_composant_id=type_composant.id,
                    quantite_hw=quantite,
                    origine=origine,
                )
            )


def add_silhouette_couverte(
    session,
    homologation_id: int,
    silhouette_id: int,
    origine: OrigineSuggestion,
) -> None:
    existing = session.scalar(
        select(SilhouetteCouverte).where(
            SilhouetteCouverte.homologation_id == homologation_id,
            SilhouetteCouverte.silhouette_id == silhouette_id,
        )
    )
    if existing is None:
        session.add(
            SilhouetteCouverte(
                homologation_id=homologation_id,
                silhouette_id=silhouette_id,
                origine=origine,
            )
        )


def add_decision_couverture(
    session,
    homologation_id: int,
    est_couverte: bool,
    projet_couvrant_id: int | None,
    justification: str,
) -> DecisionCouverture | None:
    existing = session.scalar(
        select(DecisionCouverture).where(
            DecisionCouverture.homologation_id == homologation_id,
            DecisionCouverture.est_couverte == est_couverte,
        )
    )
    if existing is not None:
        return None
    row = DecisionCouverture(
        homologation_id=homologation_id,
        est_couverte=est_couverte,
        projet_couvrant_id=projet_couvrant_id,
        justification=justification,
    )
    session.add(row)
    return row


def add_prediction(
    session,
    maquette_id: int,
    predicted_duration: float,
    predicted_dll: date,
    confidence_level: ConfidenceLevel,
    input_snapshot: dict,
) -> None:
    existing = session.scalar(select(Prediction).where(Prediction.maquette_id == maquette_id))
    if existing is None:
        session.add(
            Prediction(
                maquette_id=maquette_id,
                predicted_duration=predicted_duration,
                predicted_dll=predicted_dll,
                confidence_level=confidence_level,
                model_name="demo_baseline",
                model_version="seed",
                input_snapshot=input_snapshot,
            )
        )


def add_notification(
    session,
    utilisateur_id: int,
    type_notification: TypeNotification,
    message: str,
    lu: bool,
) -> None:
    existing = session.scalar(
        select(Notification).where(
            Notification.utilisateur_id == utilisateur_id,
            Notification.message == message,
        )
    )
    if existing is None:
        session.add(
            Notification(
                utilisateur_id=utilisateur_id,
                type=type_notification,
                message=message,
                date_envoi=datetime.now(),
                lu=lu,
            )
        )


def parse_cdc_workbook(path: Path) -> tuple[str, list[tuple[str, int]]]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise RuntimeError(
            "Le package 'openpyxl' est necessaire pour importer les CDC Excel."
        ) from exc

    workbook = load_workbook(path, read_only=True, data_only=True)
    worksheet = workbook.active
    title = path.stem
    header_row = None

    for row_index, row in enumerate(worksheet.iter_rows(values_only=True), start=1):
        first_value = row[0] if row else None
        if isinstance(first_value, str) and first_value.strip():
            lowered = first_value.lower()
            if "type" not in lowered and "composant" not in lowered:
                title = first_value.strip()
        first = str(row[0]).lower() if row and row[0] is not None else ""
        second = str(row[1]).lower() if len(row) > 1 and row[1] is not None else ""
        if "type" in first and "composant" in first and ("qte" in second or "qt" in second):
            header_row = row_index
            break

    if header_row is None:
        return title, []

    quantites_par_code: dict[str, int] = {}
    for row in worksheet.iter_rows(min_row=header_row + 1, values_only=True):
        code = row[0] if row else None
        quantite = row[1] if len(row) > 1 else None
        if code is None:
            continue
        code = str(code).strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9]*", code):
            continue
        try:
            quantite_int = int(quantite)
        except (TypeError, ValueError):
            continue
        if quantite_int > 0:
            quantites_par_code[code] = quantites_par_code.get(code, 0) + quantite_int
    return title, sorted(quantites_par_code.items())


def parse_pieces_cdc_codes_workbook(path: Path) -> tuple[list[dict], dict[str, str]]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise RuntimeError(
            "Le package 'openpyxl' est necessaire pour importer les CDC Excel."
        ) from exc

    workbook = load_workbook(path, read_only=True, data_only=True)
    descriptions = _collect_component_descriptions(workbook)
    worksheet = workbook["MAQUETTES"]
    rows = list(worksheet.iter_rows(values_only=True))
    if not rows:
        return [], descriptions

    headers = rows[0]
    configs = []
    for column_index, header in enumerate(headers):
        title = str(header).strip() if header is not None else ""
        if not title:
            continue
        quantities: dict[str, int] = {}
        for row in rows[1:]:
            value = row[column_index] if column_index < len(row) else None
            for code in _extract_component_codes(value):
                quantities[code] = quantities.get(code, 0) + 1
        if quantities:
            configs.append(
                {
                    "title": title,
                    "lignes": sorted(quantities.items(), key=lambda item: _component_sort_key(item[0])),
                }
            )
    return configs, descriptions


def seed_suggestion_sources_from_workbook(
    session,
    path: Path,
    descriptions: dict[str, str] | None = None,
) -> None:
    """Importe les regles contextuelles Motorisation/Programme/Sujets/Communes."""

    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise RuntimeError(
            "Le package 'openpyxl' est necessaire pour importer les sources CDC."
        ) from exc

    workbook = load_workbook(path, read_only=True, data_only=True)
    descriptions = descriptions or _collect_component_descriptions(workbook)
    _seed_motorisation_sources(session, workbook, descriptions)
    _seed_programme_sources(session, workbook, descriptions)
    _seed_sujet_sources(session, workbook, descriptions)
    _seed_commune_sources(session, workbook, descriptions)


def _seed_motorisation_sources(session, workbook, descriptions: dict[str, str]) -> None:
    worksheet = _worksheet_by_normalized_name(workbook, "motorisation")
    if worksheet is None:
        return
    rows = list(worksheet.iter_rows(values_only=True))
    if not rows:
        return
    for row_index, row in enumerate(rows):
        headers = [
            (column_index, _parse_motorisation_values(value))
            for column_index, value in enumerate(row)
            if _parse_motorisation_values(value)
        ]
        if not headers:
            continue
        for column_index, motorisations in headers:
            for component_row in rows[row_index + 1:]:
                value = component_row[column_index] if column_index < len(component_row) else None
                for code in _extract_component_codes(value):
                    for motorisation in motorisations:
                        add_suggestion_source(
                            session,
                            "motorisation",
                            motorisation,
                            code,
                            descriptions.get(code),
                        )
        return


def _seed_programme_sources(session, workbook, descriptions: dict[str, str]) -> None:
    worksheet = _worksheet_by_normalized_name(workbook, "programme")
    if worksheet is None:
        return
    rows = list(worksheet.iter_rows(values_only=True))
    for row_index, row in enumerate(rows):
        headers = [
            (column_index, _parse_programme_values(value))
            for column_index, value in enumerate(row)
            if _parse_programme_values(value)
        ]
        if len(headers) < 2:
            continue
        for column_index, programmes in headers:
            for component_row in rows[row_index + 1:]:
                value = component_row[column_index] if column_index < len(component_row) else None
                for code in _extract_component_codes(value):
                    for programme in programmes:
                        add_suggestion_source(
                            session,
                            "programme",
                            programme,
                            code,
                            descriptions.get(code),
                        )
        return


def _seed_sujet_sources(session, workbook, descriptions: dict[str, str]) -> None:
    worksheet = _worksheet_by_normalized_name(workbook, "sujets")
    if worksheet is None:
        return
    rows = list(worksheet.iter_rows(values_only=True))
    for row_index, row in enumerate(rows):
        headers = [
            (column_index, parser_sujets(str(value)))
            for column_index, value in enumerate(row)
            if parser_sujets(str(value) if value is not None else "")
        ]
        if not headers:
            continue
        for column_index, sujets in headers:
            for sujet in sujets:
                get_or_create_sujet(session, sujet)
            for component_row in rows[row_index + 1:]:
                value = component_row[column_index] if column_index < len(component_row) else None
                for code in _extract_component_codes(value):
                    for sujet in sujets:
                        add_suggestion_source(
                            session,
                            "sujet",
                            sujet,
                            code,
                            descriptions.get(code),
                        )
        return


def _seed_commune_sources(session, workbook, descriptions: dict[str, str]) -> None:
    sheet_name = next(
        (
            name
            for name in workbook.sheetnames
            if "commune" in name.lower() or "communes" in name.lower()
        ),
        None,
    )
    if sheet_name is None:
        return
    worksheet = workbook[sheet_name]
    for row in worksheet.iter_rows(values_only=True):
        for value in row:
            for code in _extract_component_codes(value):
                add_suggestion_source(
                    session,
                    "commune",
                    "toujours",
                    code,
                    descriptions.get(code),
                )


def _worksheet_by_normalized_name(workbook, expected: str):
    expected = expected.strip().lower()
    for name in workbook.sheetnames:
        if name.strip().lower() == expected:
            return workbook[name]
    return None


def _parse_motorisation_values(value) -> list[str]:
    if value is None:
        return []
    return _unique([match.upper() for match in re.findall(r"\bM\d+\b", str(value).upper())])


def _parse_programme_values(value) -> list[str]:
    if value is None:
        return []
    text = str(value).upper()
    return _unique(
        [
            match.upper()
            for match in re.findall(r"\b(?:X\d+|SMC|D\d+|Y\d+)\b", text)
        ]
    )


def _unique(values: list[str]) -> list[str]:
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _collect_component_descriptions(workbook) -> dict[str, str]:
    descriptions: dict[str, str] = {}
    for worksheet in workbook.worksheets:
        for row in worksheet.iter_rows(values_only=True):
            for value in row:
                text = str(value).strip() if value is not None else ""
                if not text:
                    continue
                codes = _extract_component_codes(text)
                if not codes:
                    continue
                if text.upper() in set(codes):
                    continue
                for code in codes:
                    current = descriptions.get(code)
                    if current is None or len(text) > len(current):
                        descriptions[code] = text
    return descriptions


def _extract_component_codes(value) -> list[str]:
    if value is None:
        return []
    text = str(value).upper()
    codes = [match.upper() for match in re.findall(r"\b[TP]\d+\b", text)]
    t_codes = [code for code in codes if code.startswith("T")]
    selected = t_codes or codes
    return sorted(set(selected), key=_component_sort_key)


def _parse_raw_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _clean_raw_token(value) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value).strip().upper())
    return text or None


def _statut_projet_from_raw(value) -> StatutProjet:
    text = str(value or "").strip().lower()
    if "sold" in text:
        return StatutProjet.TERMINEE
    if text:
        return StatutProjet.EN_COURS
    return StatutProjet.PLANIFIEE


def _statut_homologation_from_raw(value) -> StatutHomologation:
    return (
        StatutHomologation.TERMINEE
        if _statut_projet_from_raw(value) == StatutProjet.TERMINEE
        else StatutHomologation.EN_COURS
    )


def _statut_avancement_from_raw(value) -> StatutAvancement:
    return (
        StatutAvancement.TERMINEE
        if _statut_projet_from_raw(value) == StatutProjet.TERMINEE
        else StatutAvancement.EN_COURS
    )


def _add_real_steps_from_tracking_row(session, planning_id: int, data: dict) -> None:
    steps = [
        ("Cahier des charges", data.get("Livraison du CDC"), data.get("CMDE")),
        ("Commande", data.get("CMDE"), data.get("CMDE")),
        ("Montage", data.get("CMDE"), data.get("montage")),
        ("Validation fonctionnelle", data.get("montage"), data.get("Validation fonctionnelle")),
        ("Deadline avec buffer", data.get("Validation fonctionnelle"), data.get("Dead Line avec BUFFER")),
        ("Deadline contractuelle", data.get("Dead Line avec BUFFER"), data.get("Dead Line")),
        ("Retour reel", data.get("Dead Line"), data.get("DLL de retour")),
    ]
    for ordre, (libelle, debut, fin) in enumerate(steps, start=1):
        date_debut = _parse_raw_date(debut)
        date_fin = _parse_raw_date(fin) or date_debut
        if date_debut is None and date_fin is None:
            continue
        session.add(
            EtapeConstruction(
                planning_id=planning_id,
                ordre=ordre,
                libelle=libelle,
                date_debut=date_debut or date_fin,
                date_fin=date_fin or date_debut,
                statut=StatutEtape.TERMINEE,
            )
        )


def _component_sort_key(code: str) -> tuple[str, int]:
    match = re.fullmatch(r"([A-Z]+)(\d+)", code)
    if not match:
        return code, 0
    return match.group(1), int(match.group(2))


def _slug_reference(value: str) -> str:
    text = re.sub(r"[^A-Z0-9]+", "-", value.upper()).strip("-")
    return text or "CDC"


def extract_silhouette(title: str) -> str:
    tokens = re.findall(r"[A-Z]+\d+", title.upper())
    for token in reversed(tokens):
        if token.startswith(("P", "Y")):
            return token
    return "P18"


def extract_modele(title: str) -> str:
    tokens = re.findall(r"[A-Z]+\d+", title.upper())
    for token in tokens:
        if token.startswith("M"):
            return token
    return tokens[0] if tokens else "M0"


def date_today():
    from datetime import date

    return date.today()


def get_or_create_silhouette(session, libelle: str) -> Silhouette:
    row = session.scalar(select(Silhouette).where(Silhouette.libelle == libelle))
    if row is None:
        row = Silhouette(libelle=libelle)
        session.add(row)
        session.flush()
    return row


def get_or_create_architecture(session, reference: str, version: str) -> ArchitectureEE:
    row = session.scalar(
        select(ArchitectureEE).where(ArchitectureEE.reference == reference)
    )
    if row is None:
        row = ArchitectureEE(reference=reference, version=version)
        session.add(row)
        session.flush()
    return row


def get_or_create_fournisseur(session, nom: str) -> Fournisseur:
    row = session.scalar(select(Fournisseur).where(Fournisseur.nom == nom))
    if row is None:
        row = Fournisseur(nom=nom)
        session.add(row)
        session.flush()
    return row


def get_or_create_type_composant(session, code: str, description: str | None = None) -> TypeComposant:
    row = session.scalar(select(TypeComposant).where(TypeComposant.code == code))
    if row is None:
        row = TypeComposant(
            code=code,
            description=description or f"Type de composant {code}",
        )
        session.add(row)
        session.flush()
    elif description and row.description != description:
        row.description = description
    return row


def get_or_create_sujet(session, code: str, description: str | None = None) -> Sujet:
    code = code.strip().upper()
    row = session.scalar(select(Sujet).where(Sujet.code == code))
    if row is None:
        row = Sujet(code=code, description=description)
        session.add(row)
        session.flush()
    elif description and not row.description:
        row.description = description
    return row


def associer_sujets_maquette(
    session,
    maquette_id: int,
    sujet_codes: list[str],
    description: str | None = None,
) -> None:
    for code in sujet_codes:
        sujet = get_or_create_sujet(session, code, description=description)
        existing = session.scalar(
            select(MaquetteSujet).where(
                MaquetteSujet.maquette_id == maquette_id,
                MaquetteSujet.sujet_id == sujet.id,
            )
        )
        if existing is None:
            session.add(MaquetteSujet(maquette_id=maquette_id, sujet_id=sujet.id))


def add_suggestion_source(
    session,
    source_type: str,
    source_valeur: str,
    type_composant_code: str,
    description: str | None = None,
) -> None:
    type_composant = get_or_create_type_composant(
        session,
        type_composant_code,
        description=description,
    )
    existing = session.scalar(
        select(SuggestionComposantSource).where(
            SuggestionComposantSource.source_type == source_type,
            SuggestionComposantSource.source_valeur == source_valeur,
            SuggestionComposantSource.type_composant_id == type_composant.id,
        )
    )
    if existing is None:
        session.add(
            SuggestionComposantSource(
                source_type=source_type,
                source_valeur=source_valeur,
                type_composant_id=type_composant.id,
            )
        )
        session.flush()


def migrer_sujets_maquettes_existantes(session) -> None:
    """Associe les sujets Pxx detectables dans les champs texte deja presents."""

    maquettes = list(session.scalars(select(Maquette)))
    for maquette in maquettes:
        projet = session.get(Projet, maquette.projet_id)
        texte = " ".join(
            filter(
                None,
                [
                    projet.reference if projet else "",
                    maquette.composant_modifie,
                    maquette.modele or "",
                ],
            )
        )
        associer_sujets_maquette(
            session,
            maquette.id,
            parser_sujets(texte),
            description="Sujet migre depuis les champs texte existants",
        )


# ============================================================================
# SEED GLOBAL
# ============================================================================

def seed_database() -> None:
    """Exécute l'ensemble du seed dans une transaction."""

    session = SessionLocal()

    try:
        seed_silhouettes(session)
        seed_architectures(session)
        seed_fournisseurs(session)
        seed_types_composants(session)
        seed_admin(session)
        seed_historical_cdc(session)
        seed_suivi_homologation_projects(session)
        seed_sujets_depuis_suivi_historique(session)
        migrer_sujets_maquettes_existantes(session)

        session.commit()

        print("[OK] Seed terminé avec succès.")

    except Exception:
        session.rollback()
        raise

    finally:
        session.close()


# ============================================================================
# MAIN
# ============================================================================

if __name__ == "__main__":
    seed_database()
