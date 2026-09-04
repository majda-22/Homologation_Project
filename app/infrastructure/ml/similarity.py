from __future__ import annotations

from typing import Optional

from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import OneHotEncoder


def construire_features(maquette) -> dict:
    """Un seul point de verite pour l'encodage, reutilise plus tard pour la DLL."""
    return {
        "silhouette_id": maquette.silhouette_id,
        "architecture_ee_id": maquette.architecture_ee_id,
        "fournisseur_id": maquette.fournisseur_id,
        "type_homologation": maquette.type_homologation.value,
    }


def construire_feature_row(maquette) -> list:
    """Representation tabulaire unique des features ML."""
    return list(construire_features(maquette).values())


def trouver_maquette_similaire(
    nouvelle_maquette,
    maquettes_existantes: list,
) -> Optional[object]:
    """k=1 uniquement : une nomenclature CDC ne doit pas etre moyennee."""
    if not maquettes_existantes:
        return None
    encoder = OneHotEncoder(handle_unknown="ignore")
    features = [construire_features(maquette) for maquette in maquettes_existantes]
    X = encoder.fit_transform([list(feature.values()) for feature in features])
    nn = NearestNeighbors(n_neighbors=1).fit(X)
    x_nouveau = encoder.transform(
        [list(construire_features(nouvelle_maquette).values())]
    )
    _, index = nn.kneighbors(x_nouveau)
    return maquettes_existantes[index[0][0]]
