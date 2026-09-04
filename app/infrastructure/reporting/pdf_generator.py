"""Generation PDF des cahiers des charges R116."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from app.config.settings import settings
from app.shared.paths import chemin_unique_downloads


@dataclass(frozen=True)
class CDCLigneData:
    type_composant: str
    quantite_hw: int


@dataclass(frozen=True)
class CDCData:
    projet_reference: str
    modele: str
    silhouette: str
    lignes: list[CDCLigneData]


def generer_cdc_pdf(data: CDCData, output_dir: Path | None = None) -> Path:
    settings.ensure_directories()
    filename = _cdc_filename(data)
    if output_dir is None:
        output_path = chemin_unique_downloads(filename)
    else:
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / filename

    pdf = canvas.Canvas(str(output_path), pagesize=A4)
    width, height = A4
    y = height - 56

    title = f"CdC {data.projet_reference} {data.modele} {data.silhouette}"
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(48, y, title)
    y -= 36

    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(48, y, "TYPE DE COMPOSANT")
    pdf.drawString(width - 140, y, "QTE HW")
    y -= 12
    pdf.line(48, y, width - 48, y)
    y -= 20

    pdf.setFont("Helvetica", 11)
    for ligne in data.lignes:
        if y < 72:
            pdf.showPage()
            y = height - 56
            pdf.setFont("Helvetica", 11)
        pdf.drawString(48, y, ligne.type_composant)
        pdf.drawRightString(width - 96, y, str(ligne.quantite_hw))
        y -= 20

    pdf.save()
    return output_path


def _cdc_filename(data: CDCData) -> str:
    raw = f"CdC {data.projet_reference} {data.modele} {data.silhouette}.pdf"
    return re.sub(r"[^A-Za-z0-9_. -]+", "_", raw).strip()
