"""Referentiel officiel des codes composants CDC."""

TYPE_COMPOSANT_CODES_OFFICIELS = [
    "Affectation",
    *[f"T{index}" for index in range(1, 47)],
    *[f"P{index}" for index in range(2, 25)],
]
