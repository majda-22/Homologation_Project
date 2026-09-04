"""
Tests de la Phase 0 (Setup).

Objectif : vérifier que la configuration se charge correctement et que
les dossiers de travail peuvent être créés — rien de plus à ce stade,
la Phase 1 apportera les tests sur les modèles SQLAlchemy.
"""

from app.config.logging_config import configure_logging
from app.config.settings import settings
from app.shared.paths import chemin_unique_downloads, obtenir_dossier_downloads


def test_settings_expose_expected_attributes():
    assert settings.database_url.startswith("sqlite:///")
    assert settings.database_path.name == "r116.db"
    assert settings.app_env in {"development", "production", "test"}


def test_ensure_directories_creates_expected_folders():
    settings.ensure_directories()

    assert settings.database_path.parent.exists()
    assert settings.ml_models_dir.exists()
    assert settings.log_file.parent.exists()


def test_generated_documents_default_to_user_downloads(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
    downloads = tmp_path / "Downloads"
    downloads.mkdir()

    first = chemin_unique_downloads("cdc.pdf")
    first.write_text("existing")
    second = chemin_unique_downloads("cdc.pdf")

    assert obtenir_dossier_downloads() == downloads
    assert first.parent == downloads
    assert second.parent == downloads
    assert second.name.startswith("cdc_")


def test_downloads_fallback_is_home_not_internal_reports(tmp_path, monkeypatch):
    monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)

    assert obtenir_dossier_downloads() == tmp_path


def test_configure_logging_does_not_raise():
    # Ne doit pas lever d'exception, même appelé plusieurs fois
    # (cas des suites de tests qui importent le module plusieurs fois).
    configure_logging()
    configure_logging()
