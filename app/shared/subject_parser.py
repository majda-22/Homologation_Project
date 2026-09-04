"""Parsing tolerant des codes sujets R116."""

from __future__ import annotations

import re


def parser_sujets(texte_brut: str | None) -> list[str]:
    if not texte_brut:
        return []
    normalise = re.sub(r"[\n/+]+", "|", str(texte_brut).upper())
    codes = []
    for chunk in normalise.split("|"):
        for match in re.findall(r"\bP\d+[A-Z]?\b", chunk.strip()):
            if match not in codes:
                codes.append(match)
    return codes
