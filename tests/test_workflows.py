from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import pandas as pd
import flet as ft
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.application.auth.services import AuthService, hash_password, verifier_password
from app.application.homologation.services import HomologationService
from app.application.notification.handlers import (
    handle_retard_detecte,
    handle_statut_projet_change,
)
from app.application.notification.services import NotificationService
from app.application.planning.services import PlanningService
from app.application.planning.handlers import (
    handle_date_deadline_changee,
    on_reordonnancement_necessaire,
)
from app.application.project.services import ProjectService
from app.application.reporting.services import ReportingService
from app.domain.planning.gabarit_service import (
    DUREE_CDC_CMDE,
    generer_planning_theorique,
)
from app.infrastructure.database.base import Base
from app.infrastructure.database import models
from app.infrastructure.database.models import (
    ArchitectureEE,
    AuditLog,
    DecisionCouverture,
    Fournisseur,
    Prediction,
    Silhouette,
    TypeComposant,
    Utilisateur,
)
from app.infrastructure.ml.predict import predire_dll_par_maquette_id
from app.infrastructure.ml.predict_coverage import predire_couverture
from app.infrastructure.ml.coverage_dataset import construire_dataset_couverture
from app.infrastructure.ml.coverage_training import (
    entrainer_couverture,
    predire_regle_pure_loocv,
)
from app.infrastructure.ml.eda import (
    disponibilite_features,
    duree_moyenne_historique,
)
from app.infrastructure.ml.training import entrainer_pipeline
from app.infrastructure.ml.run_history import read_run_history
from app.infrastructure.ml.simulation import generer_dataset_simulation
from app.presentation.components.gantt_view import (
    BAR_HEIGHT_PX,
    LARGEUR_MIN_PX,
    ROW_HEIGHT_PX,
    VIEWPORT_HEIGHT_PX,
    ZOOM_JOUR_LARGEUR_PX,
    calculer_offset_date,
    calculer_position_barre,
    calculer_segment_etape,
    construire_gantt,
    statut_etape_affichage,
)
from app.presentation.project_app import (
    _cdc_auto_feedback_banner,
    _cdc_empty_message,
    _cdc_maquette_labels,
    _first_launch_admin_message,
    _gantt_items,
)
from app.infrastructure.database.repositories.project_repositories import (
    SQLAlchemyProjetRepository,
)
from app.infrastructure.database.seed import parse_pieces_cdc_codes_workbook
from app.infrastructure.database.seed import seed_admin
from app.infrastructure.database.seed import seed_suggestion_sources_from_workbook
from app.domain.homologation.events import (
    DateDeadlineChangee,
    RetardDetecte,
    StatutProjetChange,
)
from app.shared.component_codes import TYPE_COMPOSANT_CODES_OFFICIELS
from app.shared.subject_parser import parser_sujets
from app.shared.enums import (
    OrigineSuggestion,
    RoleUtilisateur,
    StatutAvancement,
    StatutHomologation,
    StatutProjet,
    TypeHomologation,
    TypeNotification,
)
from app.shared.events import EventBus
from app.shared.exceptions import RessourceDejaExistante


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
        finally:
            cursor.close()

    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(
        bind=engine,
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
    )

    with factory() as session:
        session.add_all(
            [
                Utilisateur(
                    username="admin",
                    password_hash=hash_password("admin123"),
                    role=RoleUtilisateur.ADMIN,
                    is_active=True,
                ),
                Silhouette(libelle="P18"),
                Silhouette(libelle="P21"),
                Silhouette(libelle="Y18"),
                ArchitectureEE(reference="ARCH-EE-001", version="V1"),
                ArchitectureEE(reference="EE-X9", version="V1"),
                Fournisseur(nom="FOURNISSEUR_A"),
                TypeComposant(code="T1", description="Type de composant T1"),
                TypeComposant(code="P3", description="Type de composant P3"),
                TypeComposant(code="T2", description="Type de composant T2"),
                TypeComposant(code="P6", description="Type de composant P6"),
            ]
        )
        session.commit()

    try:
        yield factory
    finally:
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture()
def project_and_maquette(session_factory):
    service = ProjectService(session_factory)
    projet = service.creer_projet(
        reference=" r116-test-001 ",
        created_by_id=1,
        date_creation=date(2026, 8, 11),
    )
    maquette = service.creer_maquette(
        projet_id=projet.id,
        silhouette_id=1,
        architecture_ee_id=1,
        fournisseur_id=1,
        composant_modifie="Colonne direction",
        type_homologation=TypeHomologation.MAQUETTE,
        modele="M1",
        date_creation=date(2026, 8, 11),
    )
    return projet, maquette


def test_project_service_creates_maquette_and_repository_reads_it(
    session_factory,
    project_and_maquette,
):
    projet, maquette = project_and_maquette

    assert projet.reference == "R116-TEST-001"
    assert maquette.projet_id == projet.id

    with session_factory() as session:
        repository = SQLAlchemyProjetRepository(session)
        persisted = repository.obtenir_par_reference("R116-TEST-001")

    assert persisted is not None
    assert persisted.id == projet.id


def test_project_service_rejects_duplicate_reference(
    session_factory,
    project_and_maquette,
):
    service = ProjectService(session_factory)

    with pytest.raises(RessourceDejaExistante):
        service.creer_projet("R116-TEST-001", created_by_id=1)


def test_project_service_filters_maquettes_by_business_criteria(
    session_factory,
    project_and_maquette,
):
    _, first_maquette = project_and_maquette
    service = ProjectService(session_factory)
    second_project = service.creer_projet("R116-FILTER-002", created_by_id=1)
    second_maquette = service.creer_maquette(
        projet_id=second_project.id,
        silhouette_id=2,
        architecture_ee_id=2,
        fournisseur_id=1,
        composant_modifie="Filtre cible",
        type_homologation=TypeHomologation.MAQUETTE,
        modele="M2",
        date_creation=date(2026, 8, 12),
    )
    third_project = service.creer_projet("R116-FILTER-003", created_by_id=1)
    third_maquette = service.creer_maquette(
        projet_id=third_project.id,
        silhouette_id=3,
        architecture_ee_id=1,
        fournisseur_id=1,
        composant_modifie="Filtre fournisseur",
        type_homologation=TypeHomologation.VEHICULE,
        modele="M3",
        date_creation=date(2026, 8, 13),
    )

    by_silhouette = service.lister_maquettes(silhouette_id=2)
    by_architecture = service.lister_maquettes(architecture_ee_id=2)
    by_type = service.lister_maquettes(type_homologation=TypeHomologation.VEHICULE)
    combined = service.lister_maquettes(
        silhouette_id=2,
        architecture_ee_id=2,
        fournisseur_id=1,
        type_homologation=TypeHomologation.MAQUETTE,
    )

    assert [item.id for item in by_silhouette] == [second_maquette.id]
    assert [item.id for item in by_architecture] == [second_maquette.id]
    assert [item.id for item in by_type] == [third_maquette.id]
    assert [item.id for item in combined] == [second_maquette.id]
    assert first_maquette.id not in [item.id for item in combined]


def test_auth_service_accepts_valid_user_and_rejects_invalid_or_inactive(
    session_factory,
):
    with session_factory() as session:
        session.add(
            Utilisateur(
                username="inactive",
                password_hash=hash_password("secret"),
                role=RoleUtilisateur.INGENIEUR,
                is_active=False,
            )
        )
        session.commit()

    service = AuthService(session_factory)

    assert verifier_password("admin123", hash_password("admin123")) is True
    assert service.authentifier("admin", "admin123").username == "admin"
    assert service.authentifier("admin", "wrong") is None
    assert service.authentifier("inactive", "secret") is None


def test_seed_admin_writes_first_login_password_file(
    session_factory,
    tmp_path,
    monkeypatch,
):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    with session_factory() as session:
        session.query(models.Utilisateur).delete()
        session.commit()

    with session_factory() as session:
        password_file = seed_admin(session)
        session.commit()

    assert password_file is not None
    assert password_file.parent == downloads
    assert password_file.name == "R116_admin_password_PREMIERE_CONNEXION.txt"
    content = password_file.read_text(encoding="utf-8")
    password = content.split("mot de passe : ", 1)[1].splitlines()[0]
    assert AuthService(session_factory).authentifier("admin", password) is not None

    with session_factory() as session:
        assert seed_admin(session) is None


def test_login_first_launch_message_points_to_downloads_file(tmp_path):
    password_file = tmp_path / "Downloads" / "R116_admin_password_PREMIERE_CONNEXION.txt"

    message = _first_launch_admin_message(password_file)

    assert message.visible is None or message.visible is True
    assert "Premier lancement" in message.content.controls[0].value
    assert str(password_file) in message.content.controls[2].value


def test_project_status_change_publishes_notification_automatically(
    session_factory,
    project_and_maquette,
):
    projet, _ = project_and_maquette
    event_bus = EventBus()
    notification_service = NotificationService(session_factory)
    event_bus.subscribe(
        StatutProjetChange,
        lambda event: handle_statut_projet_change(event, notification_service),
    )
    project_service = ProjectService(session_factory, event_bus=event_bus)

    project_service.changer_statut_projet(
        projet.id,
        StatutProjet.EN_COURS,
        utilisateur_id=1,
    )

    notifications = notification_service.lister(utilisateur_id=1, lu=False)

    assert len(notifications) == 1
    assert f"Projet #{projet.id}" in notifications[0].message
    assert "PLANIFIEE -> EN_COURS" in notifications[0].message


def test_dashboard_delay_detection_publishes_single_notification_per_24h(
    session_factory,
    project_and_maquette,
):
    _, maquette = project_and_maquette
    event_bus = EventBus()
    notification_service = NotificationService(session_factory)
    event_bus.subscribe(
        RetardDetecte,
        lambda event: handle_retard_detecte(event, notification_service),
    )
    homologation_service = HomologationService(session_factory, event_bus=event_bus)
    homologation = homologation_service.creer_homologation(maquette.id)
    homologation_service.changer_statut(homologation.id, StatutHomologation.EN_COURS)
    homologation_service.renseigner_dates(
        homologation.id,
        date_deadline=date(2026, 8, 10),
    )

    first = homologation_service.detecter_retards(
        utilisateur_id=1,
        aujourdhui=date(2026, 8, 17),
    )
    second = homologation_service.detecter_retards(
        utilisateur_id=1,
        aujourdhui=date(2026, 8, 17),
    )

    notifications = notification_service.lister(utilisateur_id=1, lu=False)

    assert first == 1
    assert second == 0
    assert len(notifications) == 1
    assert f"maquette #{maquette.id}" in notifications[0].message
    assert "7 jour(s)" in notifications[0].message


def test_homologation_workflow_records_status_decision_and_covered_silhouette(
    session_factory,
    project_and_maquette,
):
    projet, maquette = project_and_maquette
    service = HomologationService(session_factory)

    homologation = service.creer_homologation(maquette.id)
    started = service.changer_statut(homologation.id, StatutHomologation.EN_COURS)
    decision = service.ajouter_decision_couverture(
        homologation_id=homologation.id,
        est_couverte=True,
        projet_couvrant_id=projet.id,
        justification="Projet historique equivalent",
    )
    silhouette = service.ajouter_silhouette_couverte(
        homologation_id=homologation.id,
        silhouette_id=1,
        origine=OrigineSuggestion.VALIDATION_INGENIEUR,
    )

    assert started.statut == StatutHomologation.EN_COURS
    assert decision.est_couverte is True
    assert decision.projet_couvrant_id == projet.id
    assert silhouette.silhouette_id == 1


def test_coverage_suggestion_creates_decision_and_audit_log(
    session_factory,
):
    project_service = ProjectService(session_factory)
    homologation_service = HomologationService(session_factory)

    historical_project = project_service.creer_projet(
        reference="R116-HIST-001",
        created_by_id=1,
        date_creation=date(2026, 8, 1),
    )
    historical_maquette = project_service.creer_maquette(
        projet_id=historical_project.id,
        silhouette_id=2,
        architecture_ee_id=1,
        fournisseur_id=1,
        composant_modifie="Colonne historique",
        type_homologation=TypeHomologation.MAQUETTE,
        modele="M0",
        date_creation=date(2026, 8, 1),
    )
    historical_homologation = homologation_service.creer_homologation(
        historical_maquette.id
    )
    homologation_service.changer_statut(
        historical_homologation.id,
        StatutHomologation.TERMINEE,
    )
    homologation_service.ajouter_silhouette_couverte(
        homologation_id=historical_homologation.id,
        silhouette_id=2,
        origine=OrigineSuggestion.VALIDATION_INGENIEUR,
    )
    second_historical_project = project_service.creer_projet(
        reference="R116-HIST-002",
        created_by_id=1,
        date_creation=date(2026, 8, 2),
    )
    second_historical_maquette = project_service.creer_maquette(
        projet_id=second_historical_project.id,
        silhouette_id=3,
        architecture_ee_id=1,
        fournisseur_id=1,
        composant_modifie="Colonne historique bis",
        type_homologation=TypeHomologation.MAQUETTE,
        modele="M0",
        date_creation=date(2026, 8, 2),
    )
    second_historical_homologation = homologation_service.creer_homologation(
        second_historical_maquette.id
    )
    homologation_service.changer_statut(
        second_historical_homologation.id,
        StatutHomologation.TERMINEE,
    )

    current_project = project_service.creer_projet(
        reference="R116-CURRENT-001",
        created_by_id=1,
        date_creation=date(2026, 8, 11),
    )
    current_maquette = project_service.creer_maquette(
        projet_id=current_project.id,
        silhouette_id=1,
        architecture_ee_id=1,
        fournisseur_id=1,
        composant_modifie="Colonne actuelle",
        type_homologation=TypeHomologation.MAQUETTE,
        modele="M1",
        date_creation=date(2026, 8, 11),
    )
    current_homologation = homologation_service.creer_homologation(current_maquette.id)

    suggestion = homologation_service.verifier_couverture(current_homologation.id)
    decision = homologation_service.enregistrer_decision_couverture(
        homologation_id=current_homologation.id,
        est_couverte=suggestion.est_couverte,
        projet_couvrant_id=suggestion.projet_couvrant_id,
        justification=suggestion.justification,
        utilisateur_id=1,
    )

    assert suggestion.est_couverte is True
    assert suggestion.projet_couvrant_id == second_historical_project.id
    assert [item.reference for item in suggestion.projets_couvrants] == [
        "R116-HIST-002",
        "R116-HIST-001",
    ]
    assert [item.silhouette_id for item in suggestion.silhouettes_suggerees] == [3]

    with session_factory() as session:
        persisted_decision = session.get(DecisionCouverture, decision.id)
        audit_log = session.scalar(
            select(AuditLog).where(AuditLog.entity_id == decision.id)
        )

    assert persisted_decision is not None
    assert persisted_decision.est_couverte is True
    assert persisted_decision.projet_couvrant_id == second_historical_project.id
    assert audit_log is not None
    assert audit_log.action == "CREATE_DECISION_COUVERTURE"
    assert audit_log.entity_type == "DecisionCouverture"
    assert audit_log.utilisateur_id == 1


def test_coverage_dataset_maps_features_and_label(session_factory):
    project_service = ProjectService(session_factory)
    homologation_service = HomologationService(session_factory)
    projet = project_service.creer_projet("R116-COV-DATA", created_by_id=1)
    maquette = project_service.creer_maquette(
        projet_id=projet.id,
        silhouette_id=1,
        architecture_ee_id=1,
        fournisseur_id=1,
        composant_modifie="Dataset couverture",
        type_homologation=TypeHomologation.VEHICULE,
        modele="M1",
    )
    homologation = homologation_service.creer_homologation(maquette.id)
    homologation_service.enregistrer_decision_couverture(
        homologation_id=homologation.id,
        est_couverte=True,
        projet_couvrant_id=projet.id,
        justification="Decision test",
        utilisateur_id=1,
    )

    with session_factory() as session:
        decisions = list(session.scalars(select(DecisionCouverture)))
        dataset = construire_dataset_couverture(decisions)

    assert dataset.to_dict("records") == [
        {
            "silhouette_id": 1,
            "architecture_ee_id": 1,
            "fournisseur_id": 1,
            "type_homologation": TypeHomologation.VEHICULE.value,
            "label_couverture": 1,
        }
    ]


def test_coverage_rule_circularity_baseline_handles_few_decisions():
    dataset = pd.DataFrame(
        [
            {
                "silhouette_id": 1,
                "architecture_ee_id": 10,
                "fournisseur_id": 1,
                "type_homologation": TypeHomologation.MAQUETTE.value,
                "label_couverture": 1,
            },
            {
                "silhouette_id": 2,
                "architecture_ee_id": 20,
                "fournisseur_id": 1,
                "type_homologation": TypeHomologation.MAQUETTE.value,
                "label_couverture": 0,
            },
        ]
    )

    predictions = predire_regle_pure_loocv(dataset)

    assert predictions == [0, 0]


def test_coverage_training_and_prediction_end_to_end(session_factory, tmp_path):
    project_service = ProjectService(session_factory)
    homologation_service = HomologationService(session_factory)
    covered_project = project_service.creer_projet("R116-COV-TRAIN-1", created_by_id=1)
    covered_maquette = project_service.creer_maquette(
        projet_id=covered_project.id,
        silhouette_id=1,
        architecture_ee_id=1,
        fournisseur_id=1,
        composant_modifie="Couverture positive",
        type_homologation=TypeHomologation.MAQUETTE,
        modele="M1",
    )
    covered_homologation = homologation_service.creer_homologation(covered_maquette.id)
    homologation_service.enregistrer_decision_couverture(
        homologation_id=covered_homologation.id,
        est_couverte=True,
        projet_couvrant_id=covered_project.id,
        justification="Positive",
        utilisateur_id=1,
    )

    uncovered_project = project_service.creer_projet("R116-COV-TRAIN-2", created_by_id=1)
    uncovered_maquette = project_service.creer_maquette(
        projet_id=uncovered_project.id,
        silhouette_id=2,
        architecture_ee_id=2,
        fournisseur_id=1,
        composant_modifie="Couverture negative",
        type_homologation=TypeHomologation.MAQUETTE,
        modele="M2",
    )
    uncovered_homologation = homologation_service.creer_homologation(uncovered_maquette.id)
    homologation_service.enregistrer_decision_couverture(
        homologation_id=uncovered_homologation.id,
        est_couverte=False,
        projet_couvrant_id=None,
        justification="Negative",
        utilisateur_id=1,
    )
    target_project = project_service.creer_projet("R116-COV-PREDICT", created_by_id=1)
    target_maquette = project_service.creer_maquette(
        projet_id=target_project.id,
        silhouette_id=3,
        architecture_ee_id=1,
        fournisseur_id=1,
        composant_modifie="Prediction couverture",
        type_homologation=TypeHomologation.MAQUETTE,
        modele="M3",
    )
    model_path = tmp_path / "coverage_pipeline.joblib"

    report = entrainer_couverture(
        output_path=model_path,
        session_factory=session_factory,
    )
    prediction = predire_couverture(
        target_maquette,
        model_path=model_path,
        session_factory=session_factory,
    )

    assert model_path.exists()
    assert report.lignes_utilisables == 2
    assert "rule_baseline" in report.metrics
    assert isinstance(prediction.est_couverte, bool)
    assert prediction.model_name in {
        "rule_baseline",
        "logistic_regression",
        "decision_tree_depth_3",
    }


def test_cdc_lines_are_suggested_from_similar_maquette_and_pdf_is_generated(
    session_factory,
    tmp_path,
    monkeypatch,
):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    service = ProjectService(session_factory)
    projet_source = service.creer_projet("R116-CDC-001", created_by_id=1)
    maquette_source = service.creer_maquette(
        projet_id=projet_source.id,
        silhouette_id=3,
        architecture_ee_id=2,
        fournisseur_id=1,
        composant_modifie="CDC source",
        type_homologation=TypeHomologation.MAQUETTE,
        modele="M1",
    )
    for type_composant_id, quantite in ((1, 1), (2, 1), (3, 2), (4, 1)):
        service.ajouter_ligne_cdc(
            maquette_id=maquette_source.id,
            type_composant_id=type_composant_id,
            quantite_hw=quantite,
        )

    projet_cible = service.creer_projet("R116-CDC-002", created_by_id=1)
    maquette_cible = service.creer_maquette(
        projet_id=projet_cible.id,
        silhouette_id=3,
        architecture_ee_id=2,
        fournisseur_id=1,
        composant_modifie="CDC cible",
        type_homologation=TypeHomologation.MAQUETTE,
        modele="M2",
    )

    lignes = service.lister_lignes_cdc(maquette_cible.id)
    chemin_pdf = service.generer_cdc(maquette_cible.id)

    assert len(lignes) == 4
    assert {ligne.type_composant_code for ligne in lignes} == {"T1", "P3", "T2", "P6"}
    assert all(ligne.origine == OrigineSuggestion.SUGGESTION_AUTO for ligne in lignes)
    assert chemin_pdf.parent == downloads
    assert chemin_pdf.exists()
    assert chemin_pdf.name == "CdC R116-CDC-002 M2 Y18.pdf"


def test_pieces_cdc_codes_workbook_parser_imports_real_configurations():
    configs, descriptions = parse_pieces_cdc_codes_workbook(
        Path("data/raw/cdc/Pieces_CDC_codes.xlsx")
    )

    assert len(configs) == 9
    assert all(config["lignes"] for config in configs)
    assert descriptions["T25"] == "T25 - Body Controler Module"
    assert "T46" in TYPE_COMPOSANT_CODES_OFFICIELS
    assert "P24" in TYPE_COMPOSANT_CODES_OFFICIELS


def test_subject_parser_is_tolerant_and_ignores_programme_or_model_codes():
    assert parser_sujets("P7/ P16") == ["P7", "P16"]
    assert parser_sujets("P12 / P16\nP3 / P6") == ["P12", "P16", "P3", "P6"]
    assert parser_sujets("X2 M1 P16 + P22") == ["P16", "P22"]
    assert parser_sujets("P12 / P19 avec P7\nP1") == ["P12", "P19", "P7", "P1"]
    assert parser_sujets("P11 + P20/ P24\nP18 + P25") == [
        "P11",
        "P20",
        "P24",
        "P18",
        "P25",
    ]


def test_pieces_workbook_imports_contextual_suggestion_sources(session_factory):
    with session_factory() as session:
        seed_suggestion_sources_from_workbook(
            session,
            Path("data/raw/cdc/Pieces_CDC_codes.xlsx"),
        )
        session.commit()

        motorisation_codes = {
            code
            for code in session.scalars(
                select(models.TypeComposant.code)
                .join(models.SuggestionComposantSource)
                .where(models.SuggestionComposantSource.source_type == "motorisation")
                .where(models.SuggestionComposantSource.source_valeur == "M1")
            )
        }
        sujet_codes = {
            code
            for code in session.scalars(
                select(models.TypeComposant.code)
                .join(models.SuggestionComposantSource)
                .where(models.SuggestionComposantSource.source_type == "sujet")
                .where(models.SuggestionComposantSource.source_valeur == "P12")
            )
        }

    assert "T7" in motorisation_codes
    assert {"T18", "T19", "T20", "T21"}.issubset(sujet_codes)


def test_creer_maquette_prefills_cdc_from_motorisation_and_subject(session_factory):
    with session_factory() as session:
        for code in ["T7", "T18", "T19", "T20", "T21"]:
            component = session.scalar(
                select(models.TypeComposant).where(models.TypeComposant.code == code)
            )
            if component is None:
                component = models.TypeComposant(
                    code=code,
                    description=f"Type de composant {code}",
                )
                session.add(component)
                session.flush()
            sources = [("motorisation", "M1")] if code == "T7" else [("sujet", "P12")]
            for source_type, source_valeur in sources:
                session.add(
                    models.SuggestionComposantSource(
                        source_type=source_type,
                        source_valeur=source_valeur,
                        type_composant_id=component.id,
                    )
                )
        session.commit()

    service = ProjectService(session_factory)
    projet = service.creer_projet("X2-COMPOSITION", created_by_id=1)
    maquette = service.creer_maquette(
        projet_id=projet.id,
        silhouette_id=1,
        architecture_ee_id=1,
        fournisseur_id=1,
        composant_modifie="Composition P12",
        type_homologation=TypeHomologation.MAQUETTE,
        modele="M1",
        sujet_codes=["P12"],
    )

    lignes = service.lister_lignes_cdc(maquette.id)
    codes = {ligne.type_composant_code for ligne in lignes}

    assert {"T7", "T18", "T19", "T20", "T21"}.issubset(codes)
    assert all(ligne.origine == OrigineSuggestion.SUGGESTION_AUTO for ligne in lignes)
    assert {ligne.suggestion_source for ligne in lignes} >= {"Motorisation", "Sujet"}


def test_creer_maquette_can_generate_cdc_pdf_automatically(
    session_factory,
    tmp_path,
    monkeypatch,
):
    generated_path = tmp_path / "cdc_auto.pdf"
    monkeypatch.setattr(
        "app.application.project.services.generer_cdc_pdf",
        lambda data: generated_path,
    )
    with session_factory() as session:
        type_t7 = session.scalar(
            select(models.TypeComposant).where(models.TypeComposant.code == "T7")
        )
        if type_t7 is None:
            type_t7 = models.TypeComposant(code="T7", description="Type de composant T7")
            session.add(type_t7)
            session.flush()
        session.add(
            models.SuggestionComposantSource(
                source_type="motorisation",
                source_valeur="M1",
                type_composant_id=type_t7.id,
            )
        )
        session.commit()

    service = ProjectService(session_factory)
    projet = service.creer_projet("R116-CDC-AUTO", created_by_id=1)
    maquette = service.creer_maquette(
        projet_id=projet.id,
        silhouette_id=1,
        architecture_ee_id=1,
        fournisseur_id=1,
        composant_modifie="CDC auto",
        type_homologation=TypeHomologation.MAQUETTE,
        modele="M1",
        generer_cdc_auto=True,
    )

    lignes = service.lister_lignes_cdc(maquette.id)
    path = service.generer_cdc_automatique_si_possible(maquette.id)

    assert [ligne.type_composant_code for ligne in lignes] == ["T7"]
    assert path == generated_path


def test_cdc_auto_generation_returns_none_without_suggestions(session_factory):
    service = ProjectService(session_factory)
    projet = service.creer_projet("R116-CDC-NONE", created_by_id=1)
    maquette = service.creer_maquette(
        projet_id=projet.id,
        silhouette_id=1,
        architecture_ee_id=1,
        fournisseur_id=1,
        composant_modifie="Aucune suggestion",
        type_homologation=TypeHomologation.MAQUETTE,
        modele="MODELE-INCONNU",
        generer_cdc_auto=True,
    )

    assert service.lister_lignes_cdc(maquette.id) == []
    assert service.generer_cdc_automatique_si_possible(maquette.id) is None


def test_cdc_merge_keeps_single_line_with_composition_and_history_sources(session_factory):
    service = ProjectService(session_factory)
    historical_project = service.creer_projet("R116-HIST-MERGE", created_by_id=1)
    historical_maquette = service.creer_maquette(
        projet_id=historical_project.id,
        silhouette_id=1,
        architecture_ee_id=1,
        fournisseur_id=1,
        composant_modifie="Historique merge",
        type_homologation=TypeHomologation.MAQUETTE,
        modele="M0",
    )
    service.ajouter_ligne_cdc(
        maquette_id=historical_maquette.id,
        type_composant_id=1,
        quantite_hw=1,
    )
    with session_factory() as session:
        type_t1 = session.scalar(
            select(models.TypeComposant).where(models.TypeComposant.code == "T1")
        )
        session.add(
            models.SuggestionComposantSource(
                source_type="motorisation",
                source_valeur="M1",
                type_composant_id=type_t1.id,
            )
        )
        session.commit()

    target_project = service.creer_projet("R116-MERGE-TARGET", created_by_id=1)
    target_maquette = service.creer_maquette(
        projet_id=target_project.id,
        silhouette_id=1,
        architecture_ee_id=1,
        fournisseur_id=1,
        composant_modifie="Cible merge",
        type_homologation=TypeHomologation.MAQUETTE,
        modele="M1",
    )

    lignes_t1 = [
        ligne
        for ligne in service.lister_lignes_cdc(target_maquette.id)
        if ligne.type_composant_code == "T1"
    ]

    assert len(lignes_t1) == 1
    assert lignes_t1[0].suggestion_source == "Motorisation, Historique similaire"


def test_cdc_empty_state_explains_manual_entry_is_required(session_factory):
    service = ProjectService(session_factory)
    projet = service.creer_projet("R116-NO-SUGGESTION", created_by_id=1)
    maquette = service.creer_maquette(
        projet_id=projet.id,
        silhouette_id=1,
        architecture_ee_id=1,
        fournisseur_id=1,
        composant_modifie="Combinaison inedite",
        type_homologation=TypeHomologation.MAQUETTE,
        modele="MODELE-INCONNU",
    )

    assert service.lister_lignes_cdc(maquette.id) == []
    assert _cdc_empty_message(False) == "Aucune suggestion disponible, saisie manuelle requise."
    assert _cdc_empty_message(True) == "Aucune ligne CDC trouvee pour ce filtre."


def test_cdc_maquette_dropdown_label_exposes_real_project_reference(session_factory):
    service = ProjectService(session_factory)
    projet = service.creer_projet("HIST-CDC-X2-M2-P18", created_by_id=1)
    maquette = service.creer_maquette(
        projet_id=projet.id,
        silhouette_id=1,
        architecture_ee_id=1,
        fournisseur_id=1,
        composant_modifie="Nomenclature CDC historique",
        type_homologation=TypeHomologation.MAQUETTE,
        modele="M2",
    )
    service.ajouter_ligne_cdc(maquette.id, type_composant_id=1, quantite_hw=1)

    labels = _cdc_maquette_labels(session_factory)

    assert "CDC reel" in labels[maquette.id]["label"]
    assert "HIST-CDC-X2-M2-P18" in labels[maquette.id]["label"]
    assert "1 lignes CDC" in labels[maquette.id]["label"]


def test_cdc_auto_feedback_banner_is_visible_after_generation():
    banner = _cdc_auto_feedback_banner("CDC genere automatiquement avec 5 lignes : test.pdf")

    assert banner.visible is None or banner.visible is True
    assert banner.content.controls[1].value == "CDC genere automatiquement avec 5 lignes : test.pdf"


def test_ml_training_and_prediction_persists_prediction(
    session_factory,
    tmp_path,
):
    raw_path = tmp_path / "suivi.xlsx"
    model_path = tmp_path / "deadline_pipeline.joblib"
    history_path = tmp_path / "run_history.jsonl"
    pd.DataFrame(
        [
            {
                "Pro": "X1",
                "Mot": "M1",
                "Silh hom.": "P18",
                "Sujet": "P3",
                "CMDE": "01/01/2024",
                "DLL de retour": "31/01/2024",
            },
            {
                "Pro": "X2",
                "Mot": "M2",
                "Silh hom.": "P21",
                "Sujet": "P6",
                "CMDE": "01/02/2024",
                "DLL de retour": "17/03/2024",
            },
            {
                "Pro": "X3",
                "Mot": "M3",
                "Silh hom.": "Y18",
                "Sujet": "P7",
                "CMDE": "01/03/2024",
                "DLL de retour": "30/04/2024",
            },
        ]
    ).to_excel(raw_path, index=False)

    report = entrainer_pipeline(
        raw_path=raw_path,
        output_path=model_path,
        session_factory=session_factory,
        run_history_path=history_path,
    )
    service = ProjectService(session_factory)
    projet = service.creer_projet("R116-ML-001", created_by_id=1)
    maquette = service.creer_maquette(
        projet_id=projet.id,
        silhouette_id=1,
        architecture_ee_id=1,
        fournisseur_id=1,
        composant_modifie="Prediction cible",
        type_homologation=TypeHomologation.MAQUETTE,
        modele="M1",
        date_creation=date(2026, 8, 12),
    )

    prediction = predire_dll_par_maquette_id(
        maquette.id,
        model_path=model_path,
        session_factory=session_factory,
    )

    with session_factory() as session:
        persisted = session.get(Prediction, prediction.id)

    assert model_path.exists()
    assert report.lignes_utilisables == 3
    assert persisted is not None
    assert persisted.maquette_id == maquette.id
    assert persisted.predicted_duration > 0
    assert persisted.input_snapshot["voisins"]
    assert persisted.input_snapshot["explanation"]["method"] == "LIME-like local perturbation"
    assert persisted.input_snapshot["explanation"]["contributions"]
    assert prediction.explanation["contributions"]
    history = read_run_history(path=history_path)
    assert history[0]["model_name"] == report.meilleur_modele
    assert history[0]["n_rows"] == 3
    assert history[0]["simulated"] is False
    assert history[0]["pipeline"] == "dll"
    assert history[0]["is_low_volume"] is True
    assert "baseline_residu_median" in report.mae
    assert "ridge" in report.mae
    assert "kneighbors" in report.mae
    assert report.couverture_feature_historique == "non utilisee"


def test_simulation_dataset_is_explicitly_labelled(tmp_path):
    path = generer_dataset_simulation(n_rows=25, output_path=tmp_path / "simulation.xlsx")
    dataset = pd.read_excel(path)

    assert len(dataset) == 25
    assert set(dataset["DONNEES_SIMULEES"]) == {"OUI"}
    assert {"Pro", "Mot", "Silh hom.", "CMDE", "DLL de retour"}.issubset(dataset.columns)


def test_ml_eda_documents_feature_availability_and_historical_aggregate():
    table = {row["feature"]: row["disponible_prediction"] for row in disponibilite_features()}

    assert table["silhouette_id"] == "OUI"
    assert table["architecture_ee_id"] == "OUI"
    assert table["date_cmde"] == "NON"
    assert table["date_retour_reel"] == "NON"

    maquette = SimpleNamespace(silhouette_id=1, architecture_ee_id=1)
    current = SimpleNamespace(
        maquette=maquette,
        date_cmde=date(2024, 1, 1),
        date_retour_reel=date(2024, 2, 10),
    )
    other = SimpleNamespace(
        maquette=maquette,
        date_cmde=date(2024, 3, 1),
        date_retour_reel=date(2024, 4, 20),
    )

    assert duree_moyenne_historique(1, 1, []) is None
    assert duree_moyenne_historique(1, 1, [other]) == 50
    assert duree_moyenne_historique(1, 1, [current, other]) == 45


def test_ml_gabarit_baseline_artifact_is_loadable(
    session_factory,
    tmp_path,
):
    raw_path = tmp_path / "suivi_gabarit.xlsx"
    model_path = tmp_path / "deadline_pipeline_gabarit.joblib"
    pd.DataFrame(
        [
            {
                "Pro": "X1",
                "Mot": "M1",
                "Silh hom.": "P18",
                "Sujet": "P3",
                "CMDE": "01/01/2024",
                "DLL de retour": "19/08/2024",
            },
            {
                "Pro": "X2",
                "Mot": "M2",
                "Silh hom.": "P21",
                "Sujet": "P6",
                "CMDE": "01/02/2024",
                "DLL de retour": "19/09/2024",
            },
            {
                "Pro": "X3",
                "Mot": "M3",
                "Silh hom.": "Y18",
                "Sujet": "P7",
                "CMDE": "01/03/2024",
                "DLL de retour": "18/10/2024",
            },
        ]
    ).to_excel(raw_path, index=False)

    report = entrainer_pipeline(
        raw_path=raw_path,
        output_path=model_path,
        session_factory=session_factory,
    )
    service = ProjectService(session_factory)
    projet = service.creer_projet("R116-ML-GABARIT", created_by_id=1)
    maquette = service.creer_maquette(
        projet_id=projet.id,
        silhouette_id=1,
        architecture_ee_id=1,
        fournisseur_id=1,
        composant_modifie="Prediction gabarit",
        type_homologation=TypeHomologation.MAQUETTE,
        modele="M1",
        date_creation=date(2026, 8, 16),
    )

    prediction = predire_dll_par_maquette_id(
        maquette.id,
        model_path=model_path,
        session_factory=session_factory,
    )

    assert report.meilleur_modele == "baseline_residu_median"
    assert prediction.predicted_duration == 231
    assert prediction.predicted_dll == date(2026, 8, 16) + timedelta(days=231 + DUREE_CDC_CMDE)


def test_generer_planning_theorique_matches_real_x9_line():
    etapes = generer_planning_theorique(date(2022, 8, 1), residu_predit=18)

    assert [(etape.libelle, etape.date_fin_estimee) for etape in etapes] == [
        ("Cahier des charges", date(2022, 9, 19)),
        ("Commande", date(2022, 9, 19)),
        ("Montage", date(2022, 12, 26)),
        ("Validation fonctionnelle", date(2023, 1, 30)),
        ("Deadline avec buffer", date(2023, 3, 27)),
        ("Deadline contractuelle", date(2023, 4, 14)),
        ("Retour estime", date(2023, 5, 26)),
    ]


def test_creer_maquette_can_generate_theoretical_planning(
    session_factory,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.application.project.services.predire_residu_dll_par_maquette_id",
        lambda *_, **__: SimpleNamespace(predicted_residual=0),
    )
    service = ProjectService(session_factory)
    projet = service.creer_projet(
        "R116-PLAN-AUTO",
        created_by_id=1,
        date_creation=date(2026, 8, 23),
    )

    maquette = service.creer_maquette(
        projet_id=projet.id,
        silhouette_id=1,
        architecture_ee_id=1,
        fournisseur_id=1,
        composant_modifie="Planning auto",
        type_homologation=TypeHomologation.MAQUETTE,
        modele="M1",
        date_creation=date(2026, 8, 23),
        generer_planning=True,
    )

    with session_factory() as session:
        planning = session.scalar(
            select(models.PlanningConstruction).where(
                models.PlanningConstruction.maquette_id == maquette.id
            )
        )
        etapes = list(
            session.scalars(
                select(models.EtapeConstruction)
                .where(models.EtapeConstruction.planning_id == planning.id)
                .order_by(models.EtapeConstruction.ordre)
            )
        )

    assert planning is not None
    assert len(etapes) == 7
    assert etapes[0].libelle == "Cahier des charges"
    assert etapes[0].date_debut == date(2026, 8, 23)
    assert etapes[0].date_fin == date(2026, 8, 23) + timedelta(days=DUREE_CDC_CMDE)
    assert etapes[1].libelle == "Commande"
    assert etapes[-1].libelle == "Retour estime"


def test_planning_workflow_rejects_duplicate_planning_and_tracks_steps(
    session_factory,
    project_and_maquette,
):
    _, maquette = project_and_maquette
    service = PlanningService(session_factory)

    planning = service.creer_planning(maquette.id, priorite_score=2.5)
    etape = service.ajouter_etape(planning.id, ordre=1, libelle="CDC")
    updated = service.changer_statut_planning(planning.id, StatutAvancement.EN_COURS)

    with pytest.raises(RessourceDejaExistante):
        service.creer_planning(maquette.id)

    assert planning.priorite_score == 2.5
    assert etape.libelle == "CDC"
    assert service.lister_etapes(planning.id)[0].id == etape.id
    assert updated.statut_avancement == StatutAvancement.EN_COURS


def test_planning_reorders_from_real_homologation_deadline(
    session_factory,
    project_and_maquette,
):
    _, first_maquette = project_and_maquette
    project_service = ProjectService(session_factory)
    second_project = project_service.creer_projet(
        "R116-PLAN-002",
        created_by_id=1,
        date_creation=date(2026, 8, 11),
    )
    second_maquette = project_service.creer_maquette(
        projet_id=second_project.id,
        silhouette_id=2,
        architecture_ee_id=1,
        fournisseur_id=1,
        composant_modifie="Planning urgent",
        type_homologation=TypeHomologation.MAQUETTE,
        modele="M2",
        date_creation=date(2026, 8, 11),
    )
    event_bus = EventBus()
    planning_service = PlanningService(session_factory)
    event_bus.subscribe(
        DateDeadlineChangee,
        lambda event: handle_date_deadline_changee(
            event,
            planning_service,
            aujourdhui=date(2026, 8, 17),
        ),
    )
    first_planning = planning_service.creer_planning(first_maquette.id)
    second_planning = planning_service.creer_planning(second_maquette.id)
    homologation_service = HomologationService(session_factory, event_bus=event_bus)
    first_homologation = homologation_service.creer_homologation(first_maquette.id)
    second_homologation = homologation_service.creer_homologation(second_maquette.id)

    homologation_service.renseigner_dates(
        first_homologation.id,
        date_deadline=date(2026, 9, 30),
    )
    homologation_service.renseigner_dates(
        second_homologation.id,
        date_deadline=date(2026, 8, 20),
    )

    ordered = planning_service.lister_plannings()

    assert PlanningService.calculer_urgence(date(2026, 8, 20), date(2026, 8, 17)) > (
        PlanningService.calculer_urgence(date(2026, 9, 30), date(2026, 8, 17))
    )
    assert ordered[0].id == second_planning.id
    assert ordered[1].id == first_planning.id
    assert ordered[0].priorite_score > ordered[1].priorite_score


def test_retard_detecte_event_reorders_planning_without_manual_click(
    session_factory,
    project_and_maquette,
):
    _, first_maquette = project_and_maquette
    project_service = ProjectService(session_factory)
    second_project = project_service.creer_projet(
        "R116-RETARD-PLAN-002",
        created_by_id=1,
        date_creation=date(2026, 8, 11),
    )
    second_maquette = project_service.creer_maquette(
        projet_id=second_project.id,
        silhouette_id=2,
        architecture_ee_id=1,
        fournisseur_id=1,
        composant_modifie="Planning retard",
        type_homologation=TypeHomologation.MAQUETTE,
        modele="M2",
        date_creation=date(2026, 8, 11),
    )
    event_bus = EventBus()
    planning_service = PlanningService(session_factory)
    notification_service = NotificationService(session_factory)
    event_bus.subscribe(
        RetardDetecte,
        lambda event: handle_retard_detecte(event, notification_service),
    )
    event_bus.subscribe(
        RetardDetecte,
        lambda event: on_reordonnancement_necessaire(
            event,
            planning_service,
            aujourdhui=date(2026, 8, 17),
        ),
    )
    first_planning = planning_service.creer_planning(first_maquette.id)
    second_planning = planning_service.creer_planning(second_maquette.id)
    homologation_service = HomologationService(session_factory, event_bus=event_bus)
    first_homologation = homologation_service.creer_homologation(first_maquette.id)
    second_homologation = homologation_service.creer_homologation(second_maquette.id)
    homologation_service.changer_statut(first_homologation.id, StatutHomologation.EN_COURS)
    homologation_service.changer_statut(second_homologation.id, StatutHomologation.EN_COURS)
    homologation_service.renseigner_dates(
        first_homologation.id,
        date_deadline=date(2026, 10, 1),
    )
    homologation_service.renseigner_dates(
        second_homologation.id,
        date_deadline=date(2026, 8, 10),
    )

    published = homologation_service.detecter_retards(
        utilisateur_id=1,
        aujourdhui=date(2026, 8, 17),
    )
    ordered = planning_service.lister_plannings()

    assert published == 1
    assert ordered[0].id == second_planning.id
    assert ordered[1].id == first_planning.id
    assert ordered[0].priorite_score > ordered[1].priorite_score


def test_gantt_bar_width_is_proportional_to_duration():
    start = date(2026, 1, 1)

    _, width_30 = calculer_position_barre(
        date_debut_item=start,
        date_fin_item=date(2026, 1, 31),
        date_debut_vue=start,
    )
    _, width_300 = calculer_position_barre(
        date_debut_item=start,
        date_fin_item=date(2026, 10, 28),
        date_debut_vue=start,
    )

    assert width_300 == width_30 * 10


def test_gantt_step_status_detects_late_and_future_steps():
    assert (
        statut_etape_affichage(
            {
                "libelle": "Montage",
                "debut": date(2026, 8, 1),
                "fin": date(2026, 8, 10),
                "statut": "EN_COURS",
            },
            aujourdhui=date(2026, 8, 17),
        )
        == "EN_RETARD"
    )
    assert (
        statut_etape_affichage(
            {
                "libelle": "Validation",
                "debut": date(2026, 8, 20),
                "fin": date(2026, 8, 30),
                "statut": "A_VENIR",
            },
            aujourdhui=date(2026, 8, 17),
        )
        == "A_VENIR"
    )
    assert (
        statut_etape_affichage(
            {
                "libelle": "Commande",
                "debut": date(2026, 8, 1),
                "fin": date(2026, 8, 10),
                "statut": "TERMINEE",
            },
            aujourdhui=date(2026, 8, 17),
        )
        == "TERMINEE"
    )


def test_gantt_today_line_offset_changes_with_zoom():
    start = date(2026, 8, 1)
    today = date(2026, 8, 11)

    assert calculer_offset_date(today, start, jour_largeur_px=20) == 200
    assert calculer_offset_date(today, start, jour_largeur_px=6) == 60
    assert calculer_offset_date(today, start, jour_largeur_px=2) == 20


def test_gantt_default_dimensions_keep_steps_readable():
    assert ZOOM_JOUR_LARGEUR_PX["mois"] >= 8
    assert ROW_HEIGHT_PX >= 64
    assert BAR_HEIGHT_PX >= 38
    assert VIEWPORT_HEIGHT_PX >= 500


def test_gantt_short_segments_keep_min_width_and_hide_overflow_label():
    offset, width, show_label = calculer_segment_etape(
        date_debut_item=date(2026, 8, 1),
        date_fin_item=date(2026, 8, 2),
        date_debut_vue=date(2026, 8, 1),
        libelle="Validation fonctionnelle",
        jour_largeur_px=3,
    )

    assert offset == 0
    assert width == LARGEUR_MIN_PX
    assert show_label is False


def test_gantt_uses_permanent_horizontal_scroll_and_navigation_buttons():
    control = construire_gantt(
        [
            {
                "maquette_id": 1,
                "label": "R116-GANTT-TEST - Y18",
                "rang": 1,
                "priorite_score": 42,
                "etapes": [
                    {
                        "libelle": "Montage",
                        "debut": date(2026, 8, 1),
                        "fin": date(2026, 8, 31),
                        "statut": "EN_COURS",
                    }
                ],
                "jalons": [{"libelle": "Deadline", "date": date(2026, 9, 15)}],
            }
        ],
        date_debut_vue=date(2026, 8, 1),
        nb_jours_vue=120,
    )

    rows_with_scroll = []
    icon_buttons = []

    def walk(node):
        if isinstance(node, ft.Row) and node.scroll == ft.ScrollMode.ALWAYS:
            rows_with_scroll.append(node)
        if isinstance(node, ft.IconButton):
            icon_buttons.append(node)
        for child in getattr(node, "controls", []) or []:
            walk(child)
        content = getattr(node, "content", None)
        if content is not None:
            walk(content)

    walk(control)

    assert rows_with_scroll
    assert any(button.icon == ft.icons.CHEVRON_LEFT for button in icon_buttons)
    assert any(button.icon == ft.icons.CHEVRON_RIGHT for button in icon_buttons)


def test_gantt_items_are_sorted_like_kanban_priority(session_factory, project_and_maquette):
    _, first_maquette = project_and_maquette
    project_service = ProjectService(session_factory)
    second_project = project_service.creer_projet("R116-GANTT-PRIO", created_by_id=1)
    second_maquette = project_service.creer_maquette(
        projet_id=second_project.id,
        silhouette_id=2,
        architecture_ee_id=1,
        fournisseur_id=1,
        composant_modifie="Gantt priority",
        type_homologation=TypeHomologation.MAQUETTE,
        modele="M2",
    )
    planning_service = PlanningService(session_factory)
    first_planning = planning_service.creer_planning(first_maquette.id, priorite_score=10.0)
    second_planning = planning_service.creer_planning(second_maquette.id, priorite_score=500.0)
    planning_service.ajouter_etape(
        first_planning.id,
        ordre=1,
        libelle="Low",
        date_debut=date(2026, 8, 1),
        date_fin=date(2026, 8, 31),
    )
    planning_service.ajouter_etape(
        second_planning.id,
        ordre=1,
        libelle="High",
        date_debut=date(2026, 8, 1),
        date_fin=date(2026, 8, 31),
    )

    items = _gantt_items(session_factory)

    assert items[0]["maquette_id"] == second_maquette.id
    assert items[0]["rang"] == 1
    assert items[1]["maquette_id"] == first_maquette.id


def test_notification_workflow_sends_filters_and_marks_read(session_factory):
    service = NotificationService(session_factory)

    notification = service.envoyer(
        utilisateur_id=1,
        type_notification=TypeNotification.CHANGEMENT_STATUT,
        message="Projet mis a jour",
    )
    unread = service.lister(utilisateur_id=1, lu=False)
    read = service.marquer_lue(notification.id)

    assert unread[0].id == notification.id
    assert read.lu is True
    assert service.lister(utilisateur_id=1, lu=False) == []


def test_reporting_dashboard_counts_workflow_entities(
    session_factory,
    project_and_maquette,
):
    _, maquette = project_and_maquette
    HomologationService(session_factory).creer_homologation(maquette.id)
    PlanningService(session_factory).creer_planning(maquette.id, priorite_score=1.0)
    NotificationService(session_factory).envoyer(
        utilisateur_id=1,
        type_notification=TypeNotification.CHANGEMENT_STATUT,
        message="Workflow cree",
    )

    dashboard = ReportingService(session_factory).tableau_bord()

    assert dashboard.projets == 1
    assert dashboard.maquettes == 1
    assert dashboard.homologations == 1
    assert dashboard.plannings == 1
    assert dashboard.notifications_non_lues == 1


def test_project_summary_pdf_is_generated_in_downloads(
    session_factory,
    project_and_maquette,
    tmp_path,
    monkeypatch,
):
    projet, _ = project_and_maquette
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    report = ReportingService(session_factory).generer_resume_projet_pdf(projet.id)

    assert report.chemin.parent == downloads
    assert report.chemin.exists()
    assert report.chemin.name.startswith(f"resume_projet_{projet.id}_")
