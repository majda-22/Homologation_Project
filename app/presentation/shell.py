"""Shell commun de navigation Flet."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import flet as ft


@dataclass(frozen=True)
class ShellUser:
    username: str
    role: str


NAV_ITEMS = [
    ("dashboard", "Dashboard", ft.icons.DASHBOARD_OUTLINED),
    ("projects", "Projets", ft.icons.FOLDER_OUTLINED),
    ("planning", "Planning", ft.icons.VIEW_KANBAN_OUTLINED),
    ("prediction", "Prediction DLL", ft.icons.AUTO_GRAPH_OUTLINED),
    ("ml_history", "Historique ML", ft.icons.INSIGHTS_OUTLINED),
    ("cdc", "CDC", ft.icons.DESCRIPTION_OUTLINED),
    ("notifications", "Notifications", ft.icons.NOTIFICATIONS_OUTLINED),
    ("settings", "Parametres", ft.icons.SETTINGS_OUTLINED),
]


def build_shell(
    user: ShellUser,
    active_page: str,
    unread_notifications: int,
    on_nav: Callable[[str], None],
    content: ft.Control,
) -> ft.Control:
    rail = ft.NavigationRail(
        selected_index=_selected_index(active_page),
        label_type=ft.NavigationRailLabelType.ALL,
        min_width=92,
        min_extended_width=180,
        destinations=[
            ft.NavigationRailDestination(icon=icon, label=label)
            for _, label, icon in NAV_ITEMS
        ],
        on_change=lambda event: on_nav(NAV_ITEMS[event.control.selected_index][0]),
    )

    topbar = ft.Container(
        padding=ft.padding.symmetric(horizontal=18, vertical=10),
        border=ft.border.only(bottom=ft.BorderSide(1, ft.colors.BLUE_GREY_100)),
        content=ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                ft.Text(_active_label(active_page), size=20, weight=ft.FontWeight.BOLD),
                ft.Row(
                    spacing=14,
                    controls=[
                        ft.Stack(
                            controls=[
                                ft.Icon(ft.icons.NOTIFICATIONS_OUTLINED),
                                ft.Container(
                                    visible=unread_notifications > 0,
                                    right=0,
                                    top=0,
                                    padding=ft.padding.symmetric(horizontal=4, vertical=1),
                                    bgcolor=ft.colors.RED_600,
                                    border_radius=8,
                                    content=ft.Text(
                                        str(unread_notifications),
                                        size=10,
                                        color=ft.colors.WHITE,
                                    ),
                                ),
                            ]
                        ),
                        ft.Text(f"{user.username} | {user.role}", size=12),
                    ],
                ),
            ],
        ),
    )

    return ft.Row(
        expand=True,
        spacing=0,
        controls=[
            ft.Container(
                width=116,
                bgcolor=ft.colors.BLUE_GREY_50,
                content=rail,
            ),
            ft.VerticalDivider(width=1),
            ft.Column(
                expand=True,
                spacing=0,
                controls=[
                    topbar,
                    ft.Container(
                        expand=True,
                        padding=18,
                        content=content,
                    ),
                ],
            ),
        ],
    )


def _selected_index(active_page: str) -> int:
    for index, (page_id, _, _) in enumerate(NAV_ITEMS):
        if page_id == active_page:
            return index
    return 0


def _active_label(active_page: str) -> str:
    for page_id, label, _ in NAV_ITEMS:
        if page_id == active_page:
            return label
    return "Dashboard"
