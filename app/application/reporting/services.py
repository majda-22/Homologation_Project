"""Services applicatifs Reporting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.domain.reporting.entities import RapportGenere
from app.infrastructure.database.database import SessionLocal
from app.infrastructure.database.repositories.reporting_repositories import (
    SQLAlchemyReportingReadRepository,
)
from app.shared.exceptions import RessourceIntrouvable
from app.shared.paths import chemin_unique_downloads


@dataclass(frozen=True)
class TableauBordDTO:
    projets: int
    maquettes: int
    homologations: int
    plannings: int
    notifications_non_lues: int


class ReportingService:
    def __init__(self, session_factory: Callable[[], Session] = SessionLocal) -> None:
        self.session_factory = session_factory

    def tableau_bord(self) -> TableauBordDTO:
        with self.session_factory() as session:
            data = SQLAlchemyReportingReadRepository(session).tableau_bord()
            return TableauBordDTO(**data)

    def generer_resume_projet_pdf(self, projet_id: int) -> RapportGenere:
        settings.ensure_directories()
        with self.session_factory() as session:
            data = SQLAlchemyReportingReadRepository(session).resume_projet(projet_id)
            if not data:
                raise RessourceIntrouvable(f"Projet introuvable: {projet_id}")

        generated_at = datetime.now()
        filename = f"resume_projet_{projet_id}_{generated_at:%Y%m%d_%H%M%S}.pdf"
        output_path = chemin_unique_downloads(filename, suffix_timestamp=generated_at)
        self._write_project_summary_pdf(output_path, data, generated_at)
        return RapportGenere(
            chemin=output_path,
            type_rapport="RESUME_PROJET",
            genere_le=generated_at,
        )

    def _write_project_summary_pdf(
        self,
        output_path: Path,
        data: dict,
        generated_at: datetime,
    ) -> None:
        pdf = canvas.Canvas(str(output_path), pagesize=A4)
        width, height = A4
        y = height - 64

        pdf.setFont("Helvetica-Bold", 18)
        pdf.drawString(48, y, "Resume projet R116")
        y -= 32

        pdf.setFont("Helvetica", 10)
        pdf.drawString(48, y, f"Genere le : {generated_at:%Y-%m-%d %H:%M:%S}")
        y -= 32

        pdf.setFont("Helvetica", 12)
        for label, value in (
            ("Reference", data["reference"]),
            ("Statut", data["statut"]),
            ("Date creation", data["date_creation"]),
            ("Nombre de maquettes", data["maquettes"]),
            ("Nombre d'homologations", data["homologations"]),
        ):
            pdf.drawString(48, y, f"{label} : {value}")
            y -= 22

        pdf.line(48, y - 8, width - 48, y - 8)
        pdf.save()
