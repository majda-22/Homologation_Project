"""Composant Gantt detaille par etapes."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Callable

import flet as ft

JOUR_LARGEUR_PX = 6
ZOOM_JOUR_LARGEUR_PX = {
    "semaine": 20,
    "mois": 8,
    "trimestre": 3,
}
COULEURS_ETAPE = {
    "TERMINEE": "#4CAF50",
    "EN_COURS": "#1F3864",
    "A_VENIR": "#CFD8DC",
    "EN_RETARD": "#D32F2F",
}
LABEL_WIDTH_PX = 280
ROW_HEIGHT_PX = 68
BAR_HEIGHT_PX = 40
HEADER_HEIGHT_PX = 42
VIEWPORT_HEIGHT_PX = 520
LARGEUR_MIN_PX = 24
LABEL_CHAR_WIDTH_PX = 7


def construire_gantt(
    maquettes_avec_dates: list[dict],
    date_debut_vue: date,
    nb_jours_vue: int = 180,
    on_item_click: Callable[[dict], None] | None = None,
    on_step_click: Callable[[dict], None] | None = None,
    zoom: str = "mois",
    aujourdhui: date | None = None,
) -> ft.Control:
    """
    Structure attendue :
    {
        "maquette_id": int,
        "label": str,
        "rang": int,
        "priorite_score": float | None,
        "etapes": [
            {"libelle": str, "debut": date, "fin": date, "statut": str},
        ],
        "jalons": [{"libelle": str, "date": date}],
    }
    """

    today = aujourdhui or date.today()
    jour_largeur_px = ZOOM_JOUR_LARGEUR_PX.get(zoom, JOUR_LARGEUR_PX)
    largeur_totale = nb_jours_vue * jour_largeur_px
    largeur_table = LABEL_WIDTH_PX + largeur_totale
    horizontal_ref = ft.Ref[ft.Row]()

    def scroll_horizontal(delta: int) -> None:
        if horizontal_ref.current:
            horizontal_ref.current.scroll_to(delta=delta, duration=200)

    entete = _header(date_debut_vue, nb_jours_vue, jour_largeur_px)
    table_rows = [
        ft.Row(
            spacing=0,
            controls=[
                _label_row(item, on_item_click),
                _timeline_row(
                    item,
                    date_debut_vue,
                    largeur_totale,
                    jour_largeur_px,
                    today,
                    on_step_click,
                ),
            ],
        )
        for item in maquettes_avec_dates
    ]
    today_offset = calculer_offset_date(today, date_debut_vue, jour_largeur_px)
    today_line = _today_line(today_offset, largeur_totale, VIEWPORT_HEIGHT_PX - HEADER_HEIGHT_PX, today)
    table_header = ft.Row(
        spacing=0,
        controls=[
            ft.Container(
                width=LABEL_WIDTH_PX,
                height=HEADER_HEIGHT_PX,
                bgcolor=ft.colors.BLUE_GREY_50,
                padding=8,
                alignment=ft.alignment.center_left,
                content=ft.Text(
                    "Priorite / Maquette",
                    size=13,
                    weight=ft.FontWeight.BOLD,
                    color=ft.colors.BLUE_GREY_800,
                ),
            ),
            ft.Container(content=entete, width=largeur_totale, height=HEADER_HEIGHT_PX),
        ],
    )
    rows_layer = ft.ListView(
        height=VIEWPORT_HEIGHT_PX - HEADER_HEIGHT_PX,
        spacing=0,
        controls=table_rows,
    )
    gantt_table = ft.Container(
        width=largeur_table,
        height=VIEWPORT_HEIGHT_PX,
        content=ft.Column(
            width=largeur_table,
            spacing=0,
            controls=[
                table_header,
                ft.Stack(
                    width=largeur_table,
                    height=VIEWPORT_HEIGHT_PX - HEADER_HEIGHT_PX,
                    controls=[
                        rows_layer,
                        ft.Container(
                            left=LABEL_WIDTH_PX,
                            top=0,
                            width=largeur_totale,
                            height=VIEWPORT_HEIGHT_PX - HEADER_HEIGHT_PX,
                            content=ft.Stack(
                                width=largeur_totale,
                                height=VIEWPORT_HEIGHT_PX - HEADER_HEIGHT_PX,
                                controls=[today_line],
                            ),
                        ),
                    ],
                ),
            ],
        ),
    )

    timeline = ft.Container(
        border=ft.border.all(1, ft.colors.BLUE_GREY_100),
        border_radius=6,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        content=ft.Column(
            spacing=0,
            controls=[
                ft.Row(
                    spacing=8,
                    controls=[
                        ft.Text("Navigation timeline", size=13, weight=ft.FontWeight.BOLD),
                        ft.Row(
                            spacing=6,
                            controls=[
                                ft.IconButton(
                                    icon=ft.icons.CHEVRON_LEFT,
                                    tooltip="Reculer dans la timeline",
                                    on_click=lambda _: scroll_horizontal(-300),
                                ),
                                ft.IconButton(
                                    icon=ft.icons.CHEVRON_RIGHT,
                                    tooltip="Avancer dans la timeline",
                                    on_click=lambda _: scroll_horizontal(300),
                                ),
                            ],
                        ),
                    ],
                ),
                ft.Row(
                    spacing=0,
                    height=VIEWPORT_HEIGHT_PX,
                    controls=[
                        ft.Row(
                            ref=horizontal_ref,
                            expand=True,
                            scroll=ft.ScrollMode.ALWAYS,
                            controls=[gantt_table],
                        )
                    ],
                ),
            ],
        ),
    )

    return ft.Column(
        spacing=10,
        controls=[
            ft.Row(
                spacing=8,
                controls=[
                    ft.Text("Echelle", size=13, weight=ft.FontWeight.BOLD),
                    _zoom_hint("Semaine", zoom == "semaine"),
                    _zoom_hint("Mois", zoom == "mois"),
                    _zoom_hint("Trimestre", zoom == "trimestre"),
                ],
            ),
            timeline,
            ft.Container(
                visible=not maquettes_avec_dates,
                padding=16,
                content=ft.Text("Aucune maquette avec etapes a afficher dans le Gantt."),
            ),
            _legend(),
        ],
    )


def calculer_segment_etape(
    date_debut_item: date,
    date_fin_item: date,
    date_debut_vue: date,
    libelle: str,
    jour_largeur_px: int = JOUR_LARGEUR_PX,
) -> tuple[int, int, bool]:
    """Retourne offset, largeur lisible et visibilite du libelle."""

    offset, raw_width = calculer_position_barre(
        date_debut_item,
        date_fin_item,
        date_debut_vue,
        jour_largeur_px,
    )
    width = max(raw_width - 2, LARGEUR_MIN_PX)
    show_label = width > len(libelle) * LABEL_CHAR_WIDTH_PX
    return offset, width, show_label


def calculer_position_barre(
    date_debut_item: date,
    date_fin_item: date,
    date_debut_vue: date,
    jour_largeur_px: int = JOUR_LARGEUR_PX,
) -> tuple[int, int]:
    """Retourne offset et largeur en pixels pour une barre Gantt."""

    offset_jours = max((date_debut_item - date_debut_vue).days, 0)
    duree_jours = max((date_fin_item - date_debut_item).days, 1)
    return offset_jours * jour_largeur_px, duree_jours * jour_largeur_px


def calculer_offset_date(
    valeur: date,
    date_debut_vue: date,
    jour_largeur_px: int = JOUR_LARGEUR_PX,
) -> int:
    return (valeur - date_debut_vue).days * jour_largeur_px


def statut_etape_affichage(etape: dict, aujourdhui: date | None = None) -> str:
    today = aujourdhui or date.today()
    statut = str(etape.get("statut") or "A_VENIR")
    fin = etape.get("fin")
    if statut != "TERMINEE" and fin is not None and fin < today:
        return "EN_RETARD"
    if statut in COULEURS_ETAPE:
        return statut
    return "A_VENIR"


def _header(date_debut_vue: date, nb_jours_vue: int, jour_largeur_px: int) -> ft.Control:
    nb_mois = max(1, (nb_jours_vue + 29) // 30)
    return ft.Row(
        spacing=0,
        controls=[
            ft.Container(
                width=30 * jour_largeur_px,
                height=HEADER_HEIGHT_PX,
                content=ft.Text(
                    (date_debut_vue + timedelta(days=30 * index)).strftime("%b %Y"),
                    size=12,
                    weight=ft.FontWeight.BOLD,
                    color=ft.colors.WHITE,
                ),
                bgcolor="#1F3864",
                padding=8,
                alignment=ft.alignment.center,
            )
            for index in range(nb_mois)
        ],
    )


def _label_row(item: dict, on_item_click: Callable[[dict], None] | None) -> ft.Control:
    return ft.Container(
        height=ROW_HEIGHT_PX,
        width=LABEL_WIDTH_PX,
        padding=8,
        border=ft.border.only(bottom=ft.BorderSide(1, ft.colors.BLUE_GREY_100)),
        on_click=(lambda _: on_item_click(item)) if on_item_click else None,
        content=ft.Row(
            spacing=8,
            controls=[
                ft.Container(
                    width=44,
                    padding=ft.padding.symmetric(horizontal=8, vertical=6),
                    border_radius=6,
                    bgcolor=ft.colors.BLUE_50,
                    alignment=ft.alignment.center,
                    content=ft.Text(
                        f"#{item.get('rang', '-')}",
                        size=14,
                        weight=ft.FontWeight.BOLD,
                        color=ft.colors.BLUE_700,
                    ),
                ),
                ft.Column(
                    spacing=1,
                    expand=True,
                    controls=[
                        ft.Text(item["label"], size=12, weight=ft.FontWeight.BOLD, no_wrap=True),
                        ft.Text(
                            f"Priorite {round(item.get('priorite_score') or 0, 2)}",
                            size=12,
                            color=ft.colors.BLUE_GREY_600,
                        ),
                    ],
                ),
            ],
        ),
    )


def _timeline_row(
    item: dict,
    date_debut_vue: date,
    largeur_totale: int,
    jour_largeur_px: int,
    today: date,
    on_step_click: Callable[[dict], None] | None,
) -> ft.Control:
    controls: list[ft.Control] = []
    for etape in item.get("etapes", []):
        offset, width, show_label = calculer_segment_etape(
            etape["debut"],
            etape["fin"],
            date_debut_vue,
            etape["libelle"],
            jour_largeur_px,
        )
        display_status = statut_etape_affichage(etape, today)
        payload = {**etape, "maquette_id": item["maquette_id"], "statut_affichage": display_status}
        controls.append(
            ft.Container(
                left=offset,
                top=10,
                width=width,
                height=BAR_HEIGHT_PX,
                bgcolor=COULEURS_ETAPE[display_status],
                border_radius=5,
                padding=ft.padding.symmetric(horizontal=8),
                alignment=ft.alignment.center_left,
                tooltip=f"{etape['libelle']} | {etape['debut']} -> {etape['fin']} | {display_status}",
                on_click=(lambda _, step=payload: on_step_click(step)) if on_step_click else None,
                content=ft.Text(
                    etape["libelle"] if show_label else "",
                    size=13,
                    no_wrap=True,
                    color=ft.colors.WHITE if display_status in {"TERMINEE", "EN_COURS", "EN_RETARD"} else ft.colors.BLUE_GREY_800,
                    weight=ft.FontWeight.BOLD,
                ),
            )
        )
    for jalon in item.get("jalons", []):
        controls.append(_milestone(jalon, date_debut_vue, jour_largeur_px))
    return ft.Container(
        width=largeur_totale,
        height=ROW_HEIGHT_PX,
        bgcolor=ft.colors.GREY_50,
        border=ft.border.only(bottom=ft.BorderSide(1, ft.colors.BLUE_GREY_100)),
        content=ft.Stack(width=largeur_totale, height=ROW_HEIGHT_PX, controls=controls),
    )


def _milestone(jalon: dict, date_debut_vue: date, jour_largeur_px: int) -> ft.Control:
    offset = calculer_offset_date(jalon["date"], date_debut_vue, jour_largeur_px)
    return ft.Container(
        left=offset - 6,
        top=3,
        width=20,
        height=20,
        tooltip=f"{jalon['libelle']}: {jalon['date']}",
        content=ft.Icon(
            ft.icons.DIAMOND,
            size=14,
            color=jalon.get("couleur", ft.colors.ORANGE_700),
        ),
    )


def _today_line(offset: int, largeur_totale: int, height: int, today: date) -> ft.Control:
    return ft.Container(
        visible=0 <= offset <= largeur_totale,
        left=offset,
        top=0,
        width=2,
        height=height,
        bgcolor=ft.colors.RED_700,
        tooltip=f"Aujourd'hui: {today}",
    )


def _legend() -> ft.Control:
    return ft.Row(
        spacing=22,
        wrap=True,
        controls=[
            _legend_item(COULEURS_ETAPE["TERMINEE"], "Terminee"),
            _legend_item(COULEURS_ETAPE["EN_COURS"], "En cours"),
            _legend_item(COULEURS_ETAPE["A_VENIR"], "A venir"),
            _legend_item(COULEURS_ETAPE["EN_RETARD"], "Retard"),
            ft.Row(
                tight=True,
                spacing=6,
                controls=[
                    ft.Icon(ft.icons.DIAMOND, size=12, color=ft.colors.ORANGE_700),
                    ft.Text("Jalon CDC / deadline", size=12),
                ],
            ),
            ft.Row(
                tight=True,
                spacing=6,
                controls=[
                    ft.Container(width=12, height=2, bgcolor=ft.colors.RED_700),
                    ft.Text("Aujourd'hui", size=12),
                ],
            ),
        ],
    )


def _legend_item(color: str, label: str) -> ft.Control:
    return ft.Row(
        tight=True,
        spacing=6,
        controls=[
            ft.Container(width=12, height=12, bgcolor=color, border_radius=3),
            ft.Text(label, size=13),
        ],
    )


def _zoom_hint(label: str, selected: bool) -> ft.Control:
    return ft.Container(
        padding=ft.padding.symmetric(horizontal=8, vertical=4),
        border_radius=6,
        bgcolor=ft.colors.BLUE_50 if selected else ft.colors.BLUE_GREY_50,
        border=ft.border.all(1, ft.colors.BLUE_700 if selected else ft.colors.BLUE_GREY_100),
        content=ft.Text(
            label,
            size=13,
            weight=ft.FontWeight.BOLD if selected else ft.FontWeight.NORMAL,
            color=ft.colors.BLUE_700 if selected else ft.colors.BLUE_GREY_700,
        ),
    )
