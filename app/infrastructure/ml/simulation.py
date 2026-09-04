"""Generation de donnees synthetiques pour les demonstrations ML.

Ces donnees sont fictives et ne doivent jamais etre utilisees pour une decision
metier reelle. Elles servent uniquement a montrer le comportement de l'outil a
plus grande echelle.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from app.config.settings import settings

SIMULATION_DATASET_PATH = settings.ml_models_dir / "simulated_r116_projects.xlsx"


def generer_dataset_simulation(
    n_rows: int = 500,
    output_path: Path = SIMULATION_DATASET_PATH,
    seed: int = 116,
) -> Path:
    settings.ensure_directories()
    rng = random.Random(seed)
    silhouettes = ["P18", "P21", "P22", "Y18"]
    architectures = ["X1", "X2", "X3", "X6", "Y8", "Y16"]
    motifs = ["M1", "M2", "M3", "M5"]
    sujets = ["T1", "T4", "T8", "T12", "T18", "T24", "T31"]
    start = date(2021, 1, 4)
    rows = []
    for index in range(n_rows):
        cmde = start + timedelta(days=index * 3 + rng.randint(0, 12))
        silhouette = rng.choice(silhouettes)
        architecture = rng.choice(architectures)
        motif = rng.choice(motifs)
        sujet = rng.choice(sujets)
        cdc = cmde - timedelta(days=49)
        montage = cmde + timedelta(days=98)
        validation = montage + timedelta(days=35)
        deadline_buffer = validation + timedelta(days=56)

        base_residu = 0
        if silhouette in {"P21", "P22"}:
            base_residu += rng.choice([0, 4, 8])
        if architecture in {"X6", "Y16"}:
            base_residu += rng.choice([0, 10, 18])
        if rng.random() < 0.08:
            base_residu += rng.choice([42, 98, 180, 247])

        deadline = deadline_buffer + timedelta(days=base_residu)
        retour = deadline + timedelta(days=42)
        rows.append(
            {
                "Pro": architecture,
                "Mot": motif,
                "Silh hom.": silhouette,
                "Sujet": sujet,
                "Livraison du CDC": cdc.strftime("%d/%m/%Y"),
                "CMDE": cmde.strftime("%d/%m/%Y"),
                "Montage": montage.strftime("%d/%m/%Y"),
                "Validation fonctionnelle": validation.strftime("%d/%m/%Y"),
                "Dead Line avec BUFFER": deadline_buffer.strftime("%d/%m/%Y"),
                "Dead Line": deadline.strftime("%d/%m/%Y"),
                "DLL de retour": retour.strftime("%d/%m/%Y"),
                "DONNEES_SIMULEES": "OUI",
            }
        )
    pd.DataFrame(rows).to_excel(output_path, index=False)
    return output_path
