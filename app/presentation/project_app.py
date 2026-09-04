"""Application Flet multi-pages R116."""

from __future__ import annotations

from datetime import date, timedelta

import flet as ft
from sqlalchemy import func, select

from app.application.auth.services import AuthService
from app.application.homologation.services import HomologationService
from app.application.notification.services import NotificationService
from app.application.planning.services import PlanningService
from app.application.project.services import ProjectService
from app.domain.planning.gabarit_service import (
    generer_planning_theorique,
)
from app.infrastructure.database import models
from app.infrastructure.database.database import SessionLocal
from app.infrastructure.ml.coverage_dataset import charger_dataset_couverture
from app.infrastructure.ml.coverage_training import COVERAGE_PIPELINE_PATH, entrainer_couverture
from app.infrastructure.ml.predict_coverage import predire_couverture
from app.infrastructure.ml.predict import predire_dll_par_maquette_id
from app.infrastructure.ml.run_history import read_run_history
from app.infrastructure.ml.simulation import SIMULATION_DATASET_PATH, generer_dataset_simulation
from app.infrastructure.ml.training import PIPELINE_PATH, entrainer_pipeline
from app.presentation.components.gantt_view import construire_gantt
from app.presentation.shell import ShellUser, build_shell
from app.shared.enums import (
    OrigineSuggestion,
    StatutAvancement,
    StatutEtape,
    StatutHomologation,
    StatutProjet,
    TypeHomologation,
    TypeNotification,
)
from app.shared.events import EventBus
from app.shared.subject_parser import parser_sujets


def _message(page: ft.Page, text: str, is_error: bool = False) -> None:
    page.snack_bar = ft.SnackBar(
        content=ft.Text(text),
        bgcolor=ft.colors.RED_700 if is_error else ft.colors.GREEN_700,
    )
    page.snack_bar.open = True
    page.update()


def _first_launch_admin_message(password_file) -> ft.Control:
    if password_file is None:
        return ft.Container(visible=False)
    return ft.Container(
        padding=12,
        border_radius=6,
        bgcolor=ft.colors.ORANGE_50,
        border=ft.border.all(1, ft.colors.ORANGE_700),
        content=ft.Column(
            spacing=4,
            controls=[
                ft.Text("Premier lancement", weight=ft.FontWeight.BOLD, color=ft.colors.ORANGE_900),
                ft.Text(
                    "Le mot de passe administrateur a ete genere et enregistre "
                    "dans votre dossier Telechargements.",
                    size=12,
                    color=ft.colors.ORANGE_900,
                ),
                ft.Text(str(password_file), size=11, color=ft.colors.BLUE_GREY_700),
            ],
        ),
    )


def build_project_app(
    page: ft.Page,
    event_bus: EventBus | None = None,
    first_launch_admin_password_file=None,
) -> None:
    page.title = "R116 Platform"
    page.window_width = 1220
    page.window_height = 800
    page.padding = 0
    page.theme_mode = ft.ThemeMode.LIGHT
    _render_login(page, event_bus, first_launch_admin_password_file)


def _render_login(
    page: ft.Page,
    event_bus: EventBus | None,
    first_launch_admin_password_file=None,
) -> None:
    auth_service = AuthService()
    username_input = ft.TextField(label="Username", dense=True, width=280)
    password_input = ft.TextField(
        label="Password",
        dense=True,
        width=280,
        password=True,
        can_reveal_password=True,
    )

    def login(_: ft.ControlEvent) -> None:
        utilisateur = auth_service.authentifier(
            username_input.value or "",
            password_input.value or "",
        )
        if utilisateur is None:
            _message(page, "Identifiants invalides ou compte inactif", is_error=True)
            return
        page.session.set("current_user_id", utilisateur.id)
        page.session.set("current_username", utilisateur.username)
        page.session.set("current_role", utilisateur.role)
        _render_page(page, event_bus, "dashboard")

    page.controls.clear()
    page.add(
        ft.Container(
            expand=True,
            alignment=ft.alignment.center,
            content=ft.Column(
                width=320,
                spacing=14,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Text("R116 Platform", size=24, weight=ft.FontWeight.BOLD),
                    _first_launch_admin_message(first_launch_admin_password_file),
                    username_input,
                    password_input,
                    ft.ElevatedButton(
                        "Se connecter",
                        icon=ft.icons.LOGIN,
                        on_click=login,
                    ),
                ],
            ),
        )
    )
    page.update()


def _render_page(page: ft.Page, event_bus: EventBus | None, active_page: str) -> None:
    user_id = int(page.session.get("current_user_id"))
    username = page.session.get("current_username") or "user"
    role = page.session.get("current_role") or "-"
    unread = len(NotificationService().lister(user_id, lu=False))

    def nav(target: str) -> None:
        _render_page(page, event_bus, target)

    content = _page_content(page, event_bus, active_page, user_id)
    page.controls.clear()
    page.add(
        build_shell(
            user=ShellUser(username=username, role=role),
            active_page=active_page,
            unread_notifications=unread,
            on_nav=nav,
            content=content,
        )
    )
    page.update()


def _page_content(
    page: ft.Page,
    event_bus: EventBus | None,
    active_page: str,
    user_id: int,
) -> ft.Control:
    if active_page == "dashboard":
        return _dashboard_page(page, event_bus, user_id)
    if active_page == "projects":
        return _projects_page(page, event_bus, user_id)
    if active_page == "homologations":
        page.session.set("active_page", "projects")
        return _projects_page(page, event_bus, user_id)
    if active_page == "planning":
        return _planning_page(page, event_bus, user_id)
    if active_page == "prediction":
        return _prediction_page(page, event_bus)
    if active_page == "ml_history":
        return _ml_history_page(page, event_bus)
    if active_page == "coverage":
        page.session.set("active_page", "projects")
        return _projects_page(page, event_bus, user_id)
    if active_page == "cdc":
        return _cdc_page(page, event_bus, user_id)
    if active_page == "notifications":
        return _notifications_page(page, event_bus, user_id)
    return _settings_page()


def _dashboard_page(page: ft.Page, event_bus: EventBus | None, user_id: int) -> ft.Control:
    retards = HomologationService(event_bus=event_bus).detecter_retards(utilisateur_id=user_id)
    if retards:
        page.session.set(
            "planning_auto_reorder_message",
            "Planning reordonne automatiquement suite a un retard detecte",
        )
    data = _dashboard_data()
    cards = ft.Row(
        wrap=True,
        controls=[
            _kpi_card("Projets actifs", str(data["projets_actifs"])),
            _kpi_card("Homologations evitees", f"{data['homologations_evitees']}%"),
            _kpi_card("Deadlines < 7 jours", str(data["deadlines_7j"])),
            _kpi_card("DLL predite vs reelle", "Non disponible"),
        ],
    )

    recent_rows = [
        ft.DataRow(
            cells=[
                ft.DataCell(ft.Text(row["reference"])),
                ft.DataCell(ft.Text(row["silhouette"] or "-")),
                ft.DataCell(ft.Text(row["statut"])),
                ft.DataCell(ft.Text(row["deadline"] or "Non disponible")),
            ],
            on_select_changed=lambda _, pid=row["id"]: _render_page(
                page, event_bus, "projects"
            ),
        )
        for row in data["projets_recents"]
    ]

    suggestion_text = data["suggestion_couverture"] or "Aucune suggestion disponible"
    return ft.Column(
        expand=True,
        scroll=ft.ScrollMode.AUTO,
        spacing=18,
        controls=[
            cards,
            ft.Text("Projets recents", size=16, weight=ft.FontWeight.BOLD),
            ft.DataTable(
                columns=[
                    ft.DataColumn(ft.Text("Reference")),
                    ft.DataColumn(ft.Text("Silhouette")),
                    ft.DataColumn(ft.Text("Statut")),
                    ft.DataColumn(ft.Text("Deadline")),
                ],
                rows=recent_rows,
            ),
            ft.Container(
                padding=12,
                border=ft.border.all(1, ft.colors.BLUE_GREY_100),
                border_radius=6,
                content=ft.Column(
                    controls=[
                        ft.Text("Suggestion de couverture", weight=ft.FontWeight.BOLD),
                        ft.Text(suggestion_text),
                        ft.OutlinedButton(
                            "Voir projets",
                            icon=ft.icons.FOLDER_OUTLINED,
                            on_click=lambda _: _render_page(page, event_bus, "projects"),
                        ),
                    ]
                ),
            ),
            ft.Text("Graphique homologations evitees : Non disponible"),
        ],
    )


def _projects_page(page: ft.Page, event_bus: EventBus | None, user_id: int) -> ft.Control:
    service = ProjectService(event_bus=event_bus)
    refs = service.charger_referentiels()
    search = ft.TextField(label="Search reference", dense=True, width=220)
    status_filter = ft.Dropdown(
        label="Status",
        dense=True,
        width=170,
        value="ALL",
        options=[
            ft.dropdown.Option("ALL", "Tous"),
            *[ft.dropdown.Option(statut.value, statut.value) for statut in StatutProjet],
        ],
    )
    silhouette_filter = _filter_dropdown("Silhouette", refs.silhouettes)
    architecture_filter = _filter_dropdown("Architecture EE", refs.architectures)
    fournisseur_filter = _filter_dropdown("Supplier", refs.fournisseurs)
    type_filter = ft.Dropdown(
        label="Homologation type",
        dense=True,
        width=190,
        value="ALL",
        options=[
            ft.dropdown.Option("ALL", "Tous"),
            *[ft.dropdown.Option(item.value, item.value) for item in TypeHomologation],
        ],
    )
    form_visible = {"value": False}
    edit_project = {"id": None}
    reference = ft.TextField(label="Reference *", width=260)
    composant = ft.TextField(label="Modified component *", width=280)
    modele = ft.TextField(label="Model", width=150)
    sujets = ft.TextField(label="Sujets", hint_text="Ex: P12 / P16", width=220)
    silhouette = _dropdown("Silhouette *", refs.silhouettes)
    architecture = _dropdown("Architecture EE *", refs.architectures)
    fournisseur = _dropdown("Supplier *", refs.fournisseurs)
    type_homologation = ft.Dropdown(
        label="Homologation type *",
        width=190,
        value=TypeHomologation.MAQUETTE.value,
        options=[ft.dropdown.Option(item.value, item.value) for item in TypeHomologation],
    )
    edit_reference = ft.TextField(label="Reference *", width=260)
    edit_status = ft.Dropdown(
        label="Status *",
        width=190,
        options=[ft.dropdown.Option(statut.value, statut.value) for statut in StatutProjet],
    )
    rows = ft.Column(spacing=6, expand=True, scroll=ft.ScrollMode.AUTO)
    form_panel = ft.Container(visible=False)
    edit_panel = ft.Container(visible=False)

    def clear_errors(*controls) -> None:
        for control in controls:
            control.error_text = None

    def open_create(_: ft.ControlEvent) -> None:
        form_visible["value"] = True
        form_panel.visible = True
        edit_panel.visible = False
        clear_errors(reference, composant, silhouette, architecture, fournisseur, type_homologation)
        page.update()

    def close_forms(_: ft.ControlEvent | None = None) -> None:
        form_visible["value"] = False
        form_panel.visible = False
        edit_panel.visible = False
        edit_project["id"] = None
        page.update()

    def open_modify(projet) -> None:
        edit_project["id"] = projet.id
        edit_reference.value = projet.reference
        edit_status.value = projet.statut.value
        clear_errors(edit_reference, edit_status)
        edit_panel.visible = True
        form_panel.visible = False
        page.update()

    def update_project(_: ft.ControlEvent) -> None:
        clear_errors(edit_reference, edit_status)
        if not (edit_reference.value or "").strip():
            edit_reference.error_text = "Required"
            page.update()
            return
        try:
            service.modifier_projet(
                int(edit_project["id"]),
                reference=edit_reference.value,
                statut=StatutProjet(edit_status.value),
                utilisateur_id=user_id,
            )
            _render_page(page, event_bus, "projects")
        except Exception as exc:
            _message(page, str(exc), is_error=True)

    def delete_project(projet_id: int) -> None:
        try:
            service.supprimer_projet(projet_id)
            _render_page(page, event_bus, "projects")
        except Exception as exc:
            _message(page, str(exc), is_error=True)

    def predict_project(projet_id: int) -> None:
        maquettes = service.lister_maquettes(projet_id=projet_id)
        if not maquettes:
            _message(page, "No maquette linked to this project", is_error=True)
            return
        try:
            prediction = predire_dll_par_maquette_id(maquettes[0].id)
            _message(
                page,
                f"Predicted DLL for maquette #{maquettes[0].id}: {prediction.predicted_dll}",
            )
        except Exception as exc:
            _message(page, str(exc), is_error=True)

    def refresh() -> None:
        selected = None if status_filter.value == "ALL" else StatutProjet(status_filter.value)
        query = (search.value or "").strip().upper()
        selected_silhouette = _optional_int(silhouette_filter.value)
        selected_architecture = _optional_int(architecture_filter.value)
        selected_fournisseur = _optional_int(fournisseur_filter.value)
        selected_type = None if type_filter.value == "ALL" else TypeHomologation(type_filter.value)
        rows.controls.clear()
        for projet in service.lister_projets(selected):
            if query and query not in projet.reference:
                continue
            maquettes = service.lister_maquettes(
                projet_id=projet.id,
                silhouette_id=selected_silhouette,
                architecture_ee_id=selected_architecture,
                fournisseur_id=selected_fournisseur,
                type_homologation=selected_type,
            )
            if any(
                [
                    selected_silhouette,
                    selected_architecture,
                    selected_fournisseur,
                    selected_type,
                ]
            ) and not maquettes:
                continue
            rows.controls.append(
                ft.Container(
                    padding=10,
                    border=ft.border.all(1, ft.colors.BLUE_GREY_100),
                    border_radius=6,
                    content=ft.Column(
                        controls=[
                            ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                controls=[
                                    ft.Text(projet.reference, weight=ft.FontWeight.BOLD),
                                    _status_badge(projet.statut.value),
                                ],
                            ),
                            ft.Text(
                                "Maquettes: "
                                + (", ".join(f"#{m.id} {m.composant_modifie}" for m in maquettes) or "-"),
                                size=12,
                            ),
                            ft.Row(
                                controls=[
                                    ft.OutlinedButton(
                                        "Modify",
                                        icon=ft.icons.EDIT_OUTLINED,
                                        on_click=lambda _, p=projet: open_modify(p),
                                    ),
                                    ft.OutlinedButton(
                                        "Delete",
                                        icon=ft.icons.DELETE_OUTLINE,
                                        on_click=lambda _, pid=projet.id: delete_project(pid),
                                    ),
                                    ft.ElevatedButton(
                                        "Predict Deadline",
                                        icon=ft.icons.AUTO_GRAPH_OUTLINED,
                                        on_click=lambda _, pid=projet.id: predict_project(pid),
                                    ),
                                ],
                                wrap=True,
                            ),
                        ],
                    ),
                )
            )

    def create(_: ft.ControlEvent) -> None:
        clear_errors(reference, composant, silhouette, architecture, fournisseur, type_homologation)
        has_error = False
        for control in [reference, composant, silhouette, architecture, fournisseur, type_homologation]:
            if not control.value:
                control.error_text = "Required"
                has_error = True
        if has_error:
            page.update()
            return
        try:
            projet = service.creer_projet(reference.value or "", created_by_id=user_id)
            maquette = service.creer_maquette(
                projet_id=projet.id,
                silhouette_id=int(silhouette.value),
                architecture_ee_id=int(architecture.value),
                fournisseur_id=int(fournisseur.value),
                composant_modifie=composant.value or "",
                type_homologation=TypeHomologation(type_homologation.value),
                modele=modele.value,
                sujet_codes=parser_sujets(sujets.value),
                generer_planning=True,
            )
            lignes_cdc = service.lister_lignes_cdc(maquette.id)
            if lignes_cdc:
                cdc_path = service.generer_cdc_automatique_si_possible(maquette.id)
                page.session.set(
                    "cdc_auto_feedback",
                    f"CDC genere automatiquement avec {len(lignes_cdc)} lignes : {cdc_path.name if cdc_path else 'PDF non genere'}",
                )
            else:
                page.session.set(
                    "cdc_auto_feedback",
                    "Aucune suggestion CDC disponible, saisie manuelle requise.",
                )
            page.session.set("selected_maquette_id", str(maquette.id))
            _render_page(page, event_bus, "cdc")
        except Exception as exc:
            _message(page, str(exc), is_error=True)

    refresh()
    form_panel.content = _form_card(
        "New Project",
        [
            ft.Row([reference, silhouette, architecture], wrap=True),
            ft.Row([fournisseur, type_homologation, composant, modele, sujets], wrap=True),
            ft.Row(
                [
                    ft.ElevatedButton("Create Project", icon=ft.icons.ADD, on_click=create),
                    ft.OutlinedButton("Cancel", on_click=close_forms),
                ],
                wrap=True,
            ),
        ],
    )
    edit_panel.content = _form_card(
        "Modify Project",
        [
            ft.Row([edit_reference, edit_status], wrap=True),
            ft.Row(
                [
                    ft.ElevatedButton("Save Changes", icon=ft.icons.SAVE_OUTLINED, on_click=update_project),
                    ft.OutlinedButton("Cancel", on_click=close_forms),
                ],
                wrap=True,
            ),
        ],
    )
    return ft.Column(
        expand=True,
        spacing=12,
        controls=[
            _section_header(
                "Projects",
                ft.ElevatedButton("New Project", icon=ft.icons.ADD, on_click=open_create),
            ),
            ft.Row(
                [
                    search,
                    status_filter,
                    silhouette_filter,
                    architecture_filter,
                    fournisseur_filter,
                    type_filter,
                    ft.OutlinedButton("Apply Filters", icon=ft.icons.FILTER_ALT_OUTLINED, on_click=lambda _: (refresh(), page.update())),
                ],
                wrap=True,
            ),
            form_panel,
            edit_panel,
            rows,
        ],
    )


def _homologations_page(page: ft.Page, event_bus: EventBus | None, user_id: int) -> ft.Control:
    project_service = ProjectService(event_bus=event_bus)
    homologation_service = HomologationService(event_bus=event_bus)
    refs = project_service.charger_referentiels()
    maquettes = project_service.lister_maquettes()
    maquette_filter = ft.Dropdown(
        label="Filter by maquette",
        dense=True,
        options=[
            ft.dropdown.Option("ALL", "All maquettes"),
            *[
                ft.dropdown.Option(str(m.id), f"#{m.id} {m.composant_modifie}")
                for m in maquettes
            ],
        ],
        value="ALL",
        expand=True,
    )
    maquette_select = ft.Dropdown(
        label="Maquette *",
        options=[
            ft.dropdown.Option(str(m.id), f"#{m.id} {m.composant_modifie}") for m in maquettes
        ],
        value=str(maquettes[0].id) if maquettes else None,
        expand=True,
    )
    hom_rows = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO, height=260)
    result = ft.Column(spacing=8, controls=[ft.Text("Couverture non verifiee")])
    covered_rows = ft.Column(spacing=4, scroll=ft.ScrollMode.AUTO, height=120)
    silhouette_select = _dropdown("Silhouette couverte", refs.silhouettes)
    covered_select = ft.Dropdown(label="Silhouette a retirer", dense=True, width=220)
    selected_homologation = {"id": None, "suggestion": None}
    deadline_input = ft.TextField(
        label="Deadline YYYY-MM-DD *",
        width=180,
    )
    status_input = ft.Dropdown(
        label="Status *",
        width=190,
        options=[ft.dropdown.Option(statut.value, statut.value) for statut in StatutHomologation],
    )
    new_form = ft.Container(visible=False)
    edit_form = ft.Container(visible=False)

    def selected_maquette() -> int:
        if not maquette_select.value:
            raise ValueError("Selectionne une maquette")
        return int(maquette_select.value)

    def refresh() -> None:
        hom_rows.controls.clear()
        filter_maquette_id = None if maquette_filter.value == "ALL" else int(maquette_filter.value)
        for homologation in homologation_service.lister_homologations(filter_maquette_id):
            selected_homologation["id"] = selected_homologation["id"] or homologation.id
            hom_rows.controls.append(
                ft.Container(
                    padding=10,
                    border=ft.border.all(1, ft.colors.BLUE_GREY_100),
                    border_radius=6,
                    content=ft.Column(
                        spacing=8,
                        controls=[
                            ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                controls=[
                                    ft.Text(
                                        f"Homologation #{homologation.id} | Maquette #{homologation.maquette_id}",
                                        weight=ft.FontWeight.BOLD,
                                    ),
                                    ft.Row([_status_badge(homologation.statut.value), _deadline_badge(homologation.date_deadline)]),
                                ],
                            ),
                            ft.Row(
                                controls=[
                                    ft.OutlinedButton(
                                        "Modify",
                                        icon=ft.icons.EDIT_OUTLINED,
                                        on_click=lambda _, h=homologation: open_edit_homologation(h),
                                    ),
                                    ft.OutlinedButton(
                                        "Delete",
                                        icon=ft.icons.DELETE_OUTLINE,
                                        on_click=lambda _, hid=homologation.id: delete_homologation(hid),
                                    ),
                                    ft.ElevatedButton(
                                        "Verify Coverage",
                                        icon=ft.icons.FACT_CHECK_OUTLINED,
                                        on_click=lambda _, hid=homologation.id: verify(hid),
                                    ),
                                    ft.OutlinedButton(
                                        "Start",
                                        icon=ft.icons.PLAY_ARROW_OUTLINED,
                                        on_click=lambda _, hid=homologation.id: (
                                            homologation_service.demarrer(hid, utilisateur_id=user_id),
                                            _render_page(page, event_bus, "homologations"),
                                        ),
                                    ),
                                ],
                                wrap=True,
                            ),
                        ],
                    ),
                )
            )
        refresh_covered()

    def open_new_homologation(_: ft.ControlEvent) -> None:
        new_form.visible = True
        edit_form.visible = False
        maquette_select.error_text = None
        page.update()

    def create(_: ft.ControlEvent) -> None:
        maquette_select.error_text = None
        if not maquette_select.value:
            maquette_select.error_text = "Required"
            page.update()
            return
        try:
            homologation_service.creer_homologation(selected_maquette())
            _render_page(page, event_bus, "homologations")
        except Exception as exc:
            _message(page, str(exc), is_error=True)

    def open_edit_homologation(homologation) -> None:
        selected_homologation["id"] = homologation.id
        deadline_input.value = str(homologation.date_deadline or "")
        status_input.value = homologation.statut.value
        deadline_input.error_text = None
        status_input.error_text = None
        edit_form.visible = True
        new_form.visible = False
        refresh_covered()
        page.update()

    def save_homologation(_: ft.ControlEvent) -> None:
        deadline_input.error_text = None
        status_input.error_text = None
        if not status_input.value:
            status_input.error_text = "Required"
            page.update()
            return
        try:
            hid = int(selected_homologation["id"])
            homologation_service.changer_statut(hid, StatutHomologation(status_input.value))
            if deadline_input.value:
                homologation_service.renseigner_dates(
                    hid,
                    date_deadline=date.fromisoformat(deadline_input.value.strip()),
                )
            _render_page(page, event_bus, "homologations")
        except Exception as exc:
            _message(page, str(exc), is_error=True)

    def delete_homologation(homologation_id: int) -> None:
        try:
            homologation_service.supprimer_homologation(homologation_id)
            _render_page(page, event_bus, "homologations")
        except Exception as exc:
            _message(page, str(exc), is_error=True)

    def verify(homologation_id: int) -> None:
        suggestion = homologation_service.verifier_couverture(homologation_id)
        ml_result = None
        try:
            with SessionLocal() as session:
                homologation_row = session.get(models.Homologation, homologation_id)
                if homologation_row is not None:
                    maquette_row = session.get(models.Maquette, homologation_row.maquette_id)
                    if maquette_row is not None:
                        ml_result = predire_couverture(maquette_row)
        except Exception as exc:
            ml_error = str(exc)
        else:
            ml_error = None
        selected_homologation["id"] = homologation_id
        selected_homologation["suggestion"] = suggestion
        status = "couvert" if suggestion.est_couverte else "non couvert"
        silhouettes = ", ".join(
            item.libelle for item in suggestion.silhouettes_suggerees
        ) or "-"
        projets_couvrants = ", ".join(
            f"{item.reference} (H#{item.homologation_id})"
            for item in suggestion.projets_couvrants
        ) or "-"
        result.controls.clear()
        result.controls.extend(
            [
                ft.Text(f"Homologation #{homologation_id}", weight=ft.FontWeight.BOLD),
                ft.Row(
                    controls=[
                        _comparison_panel(
                            "Rule Engine",
                            [
                                ft.Text(f"Result: {status}"),
                                ft.Text(f"Covering project: {suggestion.projet_couvrant_reference or '-'}"),
                                ft.Text(f"All covering projects: {projets_couvrants}"),
                                ft.Text(f"Suggested silhouettes: {silhouettes}"),
                            ],
                        ),
                        _comparison_panel(
                            "ML Classifier",
                            [
                                ft.Text(
                                    "Result: "
                                    + (
                                        "couvert"
                                        if ml_result and ml_result.est_couverte
                                        else "non couvert"
                                        if ml_result
                                        else "non disponible"
                                    )
                                ),
                                ft.Text(f"Confidence: {ml_result.confiance}" if ml_result else f"Error: {ml_error or '-'}"),
                                ft.Text(f"Model: {ml_result.model_name}" if ml_result else "Model: -"),
                                ft.Text(
                                    "Circularity: "
                                    + (
                                        "yes" if ml_result and ml_result.circularite_detectee else "no"
                                    )
                                ),
                            ],
                        ),
                    ],
                    wrap=True,
                ),
                ft.Row(
                    controls=[
                        ft.ElevatedButton(
                            "Valider la suggestion",
                            icon=ft.icons.CHECK,
                            on_click=lambda _: save_decision(validate=True),
                        ),
                        ft.OutlinedButton(
                            "Modifier",
                            icon=ft.icons.EDIT,
                            on_click=lambda _: save_decision(validate=False),
                        ),
                    ],
                    wrap=True,
                ),
            ]
        )
        refresh_covered()
        page.update()

    def save_decision(validate: bool) -> None:
        suggestion = selected_homologation["suggestion"]
        if suggestion is None:
            _message(page, "Verifie la couverture avant de decider", is_error=True)
            return
        try:
            homologation_service.enregistrer_decision_couverture(
                homologation_id=suggestion.homologation_id,
                est_couverte=suggestion.est_couverte if validate else False,
                projet_couvrant_id=suggestion.projet_couvrant_id if validate else None,
                justification=suggestion.justification
                if validate
                else "Suggestion modifiee manuellement par l'ingenieur.",
                utilisateur_id=user_id,
            )
            _message(page, "Decision de couverture enregistree")
        except Exception as exc:
            _message(page, str(exc), is_error=True)

    def update_deadline(homologation_id: int) -> None:
        try:
            if not deadline_input.value:
                raise ValueError("Renseigne une deadline au format YYYY-MM-DD")
            homologation_service.renseigner_dates(
                homologation_id,
                date_deadline=date.fromisoformat(deadline_input.value.strip()),
            )
            _render_page(page, event_bus, "homologations")
        except Exception as exc:
            _message(page, str(exc), is_error=True)

    def refresh_covered() -> None:
        covered_rows.controls.clear()
        covered_select.options.clear()
        homologation_id = selected_homologation["id"]
        if homologation_id is None:
            return
        for row in homologation_service.lister_silhouettes_couvertes(homologation_id):
            label = f"{row.silhouette_libelle} | {row.origine.value}"
            covered_select.options.append(ft.dropdown.Option(str(row.id), label))
            covered_rows.controls.append(ft.Text(f"#{row.id} | {label}", size=12))
        if covered_select.options:
            covered_select.value = covered_select.options[0].key

    def add_covered(_: ft.ControlEvent) -> None:
        homologation_id = selected_homologation["id"]
        if homologation_id is None:
            _message(page, "Selectionne une homologation", is_error=True)
            return
        try:
            homologation_service.ajouter_silhouette_couverte_manuelle(
                homologation_id,
                int(silhouette_select.value),
            )
            _render_page(page, event_bus, "homologations")
        except Exception as exc:
            _message(page, str(exc), is_error=True)

    def remove_covered(_: ft.ControlEvent) -> None:
        if not covered_select.value:
            return
        try:
            homologation_service.retirer_silhouette_couverte(int(covered_select.value))
            _render_page(page, event_bus, "homologations")
        except Exception as exc:
            _message(page, str(exc), is_error=True)

    refresh()
    new_form.content = _form_card(
        "New Homologation",
        [
            maquette_select,
            ft.Row(
                [
                    ft.ElevatedButton("Create Homologation", icon=ft.icons.ADD, on_click=create),
                    ft.OutlinedButton("Cancel", on_click=lambda _: (setattr(new_form, "visible", False), page.update())),
                ],
                wrap=True,
            ),
        ],
    )
    edit_form.content = _form_card(
        "Modify Homologation",
        [
            ft.Row([status_input, deadline_input], wrap=True),
            ft.Row(
                [
                    ft.ElevatedButton("Save Changes", icon=ft.icons.SAVE_OUTLINED, on_click=save_homologation),
                    ft.OutlinedButton("Cancel", on_click=lambda _: (setattr(edit_form, "visible", False), page.update())),
                ],
                wrap=True,
            ),
        ],
    )
    return ft.Column(
        expand=True,
        spacing=12,
        controls=[
            _section_header(
                "Homologations",
                ft.ElevatedButton("New Homologation", icon=ft.icons.ADD, on_click=open_new_homologation),
            ),
            ft.Row(
                [
                    maquette_filter,
                    ft.OutlinedButton(
                        "Apply Filter",
                        icon=ft.icons.FILTER_ALT_OUTLINED,
                        on_click=lambda _: (refresh(), page.update()),
                    ),
                ],
                wrap=True,
            ),
            new_form,
            edit_form,
            hom_rows,
            result,
            ft.Text("Silhouettes couvertes", size=16, weight=ft.FontWeight.BOLD),
            ft.Row(
                [
                    silhouette_select,
                    ft.OutlinedButton("Add Silhouette", icon=ft.icons.ADD, on_click=add_covered),
                    covered_select,
                    ft.OutlinedButton(
                        "Remove Silhouette",
                        icon=ft.icons.DELETE_OUTLINE,
                        on_click=remove_covered,
                    ),
                ],
                wrap=True,
            ),
            covered_rows,
        ],
    )


def _planning_page(page: ft.Page, event_bus: EventBus | None, user_id: int) -> ft.Control:
    planning_service = PlanningService()
    project_service = ProjectService(event_bus=event_bus)
    auto_message = page.session.get("planning_auto_reorder_message")
    if auto_message:
        page.session.set("planning_auto_reorder_message", "")
        _message(page, auto_message)
    planning_service.reordonnancer_toutes_les_maquettes_actives()
    plannings = planning_service.lister_plannings()
    maquettes = project_service.lister_maquettes()
    maquette_lookup = {maquette.id: maquette for maquette in maquettes}
    current_view = page.session.get("planning_view") or "kanban"
    current_zoom = page.session.get("planning_gantt_zoom") or "mois"
    kanban_board_height = 560
    kanban_column_width = 360
    view_switch = ft.SegmentedButton(
        selected={current_view},
        segments=[
            ft.Segment(value="kanban", label=ft.Text("Vue Kanban"), icon=ft.Icon(ft.icons.VIEW_KANBAN_OUTLINED)),
            ft.Segment(value="gantt", label=ft.Text("Vue Gantt"), icon=ft.Icon(ft.icons.VIEW_TIMELINE_OUTLINED)),
        ],
    )
    maquette_select = ft.Dropdown(
        label="Maquette",
        dense=True,
        width=260,
        options=[
            ft.dropdown.Option(str(m.id), f"#{m.id} {m.composant_modifie}")
            for m in maquettes
        ],
        value=str(maquettes[0].id) if maquettes else None,
    )
    planning_select = ft.Dropdown(
        label="Planning",
        dense=True,
        width=220,
        options=[
            ft.dropdown.Option(str(p.id), f"Planning #{p.id} - M#{p.maquette_id}")
            for p in plannings
        ],
        value=str(plannings[0].id) if plannings else None,
    )
    ordre_input = ft.TextField(label="Ordre", dense=True, width=90, value="1")
    libelle_input = ft.TextField(label="Etape", dense=True, width=220)
    debut_input = ft.TextField(label="Debut YYYY-MM-DD", dense=True, width=170)
    fin_input = ft.TextField(label="Fin YYYY-MM-DD", dense=True, width=170)
    steps_rows = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO, height=190)
    selected_step_details = ft.Container(
        padding=12,
        border=ft.border.all(1, ft.colors.BLUE_GREY_100),
        border_radius=6,
        bgcolor=ft.colors.BLUE_GREY_50,
        content=ft.Text("Selectionne une etape pour afficher ses details."),
    )

    def move(planning_id: int, statut: StatutAvancement) -> None:
        planning_service.changer_statut_planning(planning_id, statut)
        _render_page(page, event_bus, "planning")

    def accept_drop(event, statut: StatutAvancement) -> None:
        source = page.get_control(event.src_id)
        move(int(source.data), statut)

    def create_planning(_: ft.ControlEvent) -> None:
        try:
            if not maquette_select.value:
                raise ValueError("Selectionne une maquette")
            planning_service.creer_planning(int(maquette_select.value))
            _render_page(page, event_bus, "planning")
        except Exception as exc:
            _message(page, str(exc), is_error=True)

    def reorder(_: ft.ControlEvent) -> None:
        try:
            planning_service.reordonnancer_toutes_les_maquettes_actives()
            _message(page, "Planning reordered by real homologation deadlines")
            _render_page(page, event_bus, "planning")
        except Exception as exc:
            _message(page, str(exc), is_error=True)

    def change_view(event: ft.ControlEvent) -> None:
        selected = next(iter(event.control.selected), "kanban")
        page.session.set("planning_view", selected)
        _render_page(page, event_bus, "planning")

    def change_zoom(zoom: str) -> None:
        page.session.set("planning_gantt_zoom", zoom)
        page.session.set("planning_view", "gantt")
        _render_page(page, event_bus, "planning")

    def open_maquette_from_gantt(item: dict) -> None:
        page.session.set("selected_maquette_id", str(item["maquette_id"]))
        _message(page, f"Maquette #{item['maquette_id']} selectionnee dans le Gantt")
        _render_page(page, event_bus, "cdc")

    def show_gantt_step(step: dict) -> None:
        selected_step_details.content = ft.Column(
            spacing=8,
            controls=[
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Text(step["libelle"], size=16, weight=ft.FontWeight.BOLD),
                        _status_badge(step["statut_affichage"]),
                    ],
                ),
                ft.Text(f"Maquette #{step['maquette_id']}"),
                ft.Text(f"Debut : {step['debut']}"),
                ft.Text(f"Fin : {step['fin']}"),
            ],
        )
        page.update()

    def selected_planning_id() -> int:
        if not planning_select.value:
            raise ValueError("Selectionne un planning")
        return int(planning_select.value)

    def add_step(_: ft.ControlEvent) -> None:
        try:
            planning_service.ajouter_etape(
                planning_id=selected_planning_id(),
                ordre=int(ordre_input.value or "1"),
                libelle=libelle_input.value or "",
                date_debut=_parse_optional_date(debut_input.value),
                date_fin=_parse_optional_date(fin_input.value),
            )
            _render_page(page, event_bus, "planning")
        except Exception as exc:
            _message(page, str(exc), is_error=True)

    def change_step_status(etape_id: int, statut: StatutEtape) -> None:
        try:
            planning_service.changer_statut_etape(etape_id, statut)
            _render_page(page, event_bus, "planning")
        except Exception as exc:
            _message(page, str(exc), is_error=True)

    def refresh_steps() -> None:
        steps_rows.controls.clear()
        if not planning_select.value:
            steps_rows.controls.append(ft.Text("Aucun planning selectionne", size=12))
            return
        for etape in planning_service.lister_etapes(selected_planning_id()):
            steps_rows.controls.append(
                ft.Container(
                    padding=8,
                    border=ft.border.all(1, ft.colors.BLUE_GREY_100),
                    border_radius=6,
                    content=ft.Row(
                        controls=[
                            ft.Text(str(etape.ordre), width=34, weight=ft.FontWeight.BOLD),
                            ft.Text(etape.libelle, expand=True),
                            ft.Text(etape.statut.value, width=100),
                            ft.Text(str(etape.date_debut or "-"), width=95),
                            ft.Text(str(etape.date_fin or "-"), width=95),
                            ft.Row(
                                tight=True,
                                controls=[
                                    ft.IconButton(
                                        icon=ft.icons.RADIO_BUTTON_UNCHECKED,
                                        tooltip=target.value,
                                        on_click=lambda _, eid=etape.id, st=target: change_step_status(eid, st),
                                    )
                                    for target in StatutEtape
                                    if target != etape.statut
                                ],
                            ),
                        ],
                    ),
                )
            )

    status_meta = {
        StatutAvancement.PLANIFIEE: {
            "title": "Planifiees",
            "hint": "Travail pret, pas encore lance",
            "icon": ft.icons.EVENT_AVAILABLE,
        },
        StatutAvancement.EN_COURS: {
            "title": "En cours",
            "hint": "Construction ou validation active",
            "icon": ft.icons.PLAY_CIRCLE_OUTLINE,
        },
        StatutAvancement.TERMINEE: {
            "title": "Terminees",
            "hint": "Planning cloture",
            "icon": ft.icons.CHECK_CIRCLE_OUTLINE,
        },
    }
    columns = []
    for statut in StatutAvancement:
        cards = []
        for planning in [p for p in plannings if p.statut_avancement == statut]:
            maquette = maquette_lookup.get(planning.maquette_id)
            etapes = planning_service.lister_etapes(planning.id)
            done_steps = sum(1 for etape in etapes if etape.statut == StatutEtape.TERMINEE)
            active_step = next((etape for etape in etapes if etape.statut == StatutEtape.EN_COURS), None)
            next_step = active_step or next((etape for etape in etapes if etape.statut != StatutEtape.TERMINEE), None)
            card = ft.Container(
                padding=12,
                border=ft.border.all(1, ft.colors.BLUE_GREY_100),
                border_radius=6,
                bgcolor=ft.colors.WHITE,
                content=ft.Column(
                    spacing=10,
                    controls=[
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Column(
                                    spacing=2,
                                    expand=True,
                                    controls=[
                                        ft.Text(
                                            f"Maquette #{planning.maquette_id}",
                                            weight=ft.FontWeight.BOLD,
                                            size=14,
                                        ),
                                        ft.Text(
                                            maquette.composant_modifie if maquette else "-",
                                            size=12,
                                            color=ft.colors.BLUE_GREY_700,
                                            no_wrap=True,
                                        ),
                                    ],
                                ),
                                _priority_badge(planning.priorite_score),
                            ],
                        ),
                        ft.Row(
                            spacing=8,
                            controls=[
                                _pill(
                                    f"{done_steps}/{len(etapes)} etapes",
                                    ft.colors.BLUE_700,
                                    ft.colors.BLUE_50,
                                ),
                                _status_badge(statut.value),
                            ],
                        ),
                        ft.Container(
                            padding=8,
                            border_radius=6,
                            bgcolor=ft.colors.BLUE_GREY_50,
                            content=ft.Column(
                                spacing=3,
                                controls=[
                                    ft.Text("Prochaine etape", size=11, color=ft.colors.BLUE_GREY_600),
                                    ft.Text(
                                        f"{next_step.ordre}. {next_step.libelle}" if next_step else "Toutes les etapes sont terminees",
                                        size=12,
                                        weight=ft.FontWeight.BOLD,
                                    ),
                                    ft.Text(
                                        (
                                            f"{next_step.date_debut or '-'} -> {next_step.date_fin or '-'}"
                                            if next_step
                                            else "-"
                                        ),
                                        size=11,
                                        color=ft.colors.BLUE_GREY_700,
                                    ),
                                ],
                            ),
                        ),
                        ft.Row(
                            controls=[
                                ft.OutlinedButton(
                                    _kanban_action_label(target),
                                    icon=_kanban_action_icon(target),
                                    on_click=lambda _, pid=planning.id, st=target: move(pid, st),
                                )
                                for target in StatutAvancement
                                if target != statut
                            ],
                            wrap=True,
                        ),
                    ]
                ),
            )
            cards.append(
                ft.Draggable(
                    group="planning",
                    data=str(planning.id),
                    content=card,
                    content_feedback=ft.Container(
                        width=220,
                        padding=10,
                        bgcolor=ft.colors.BLUE_GREY_100,
                        border_radius=6,
                        content=ft.Text(f"Planning #{planning.id}"),
                    ),
                )
            )
        column_header = ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                ft.Row(
                    tight=True,
                    spacing=8,
                    controls=[
                        ft.Icon(status_meta[statut]["icon"], size=20, color=ft.colors.BLUE_GREY_700),
                        ft.Column(
                            spacing=1,
                            controls=[
                                ft.Text(status_meta[statut]["title"], weight=ft.FontWeight.BOLD),
                                ft.Text(status_meta[statut]["hint"], size=11, color=ft.colors.BLUE_GREY_700),
                            ],
                        ),
                    ],
                ),
                _pill(str(len(cards)), ft.colors.BLUE_GREY_700, ft.colors.WHITE),
            ],
        )
        column_content = ft.Container(
            width=kanban_column_width,
            height=kanban_board_height,
            padding=12,
            border=ft.border.all(1, ft.colors.BLUE_GREY_100),
            border_radius=6,
            bgcolor=ft.colors.BLUE_GREY_50,
            content=ft.Column(
                spacing=10,
                controls=[
                    column_header,
                    ft.ListView(
                        expand=True,
                        spacing=10,
                        controls=cards
                        or [
                            ft.Container(
                                padding=16,
                                border_radius=6,
                                bgcolor=ft.colors.WHITE,
                                content=ft.Text(
                                    "Aucune maquette dans cette colonne",
                                    size=12,
                                    color=ft.colors.BLUE_GREY_600,
                                ),
                            )
                        ],
                    ),
                ],
            ),
        )
        columns.append(
            ft.DragTarget(
                group="planning",
                on_accept=lambda event, st=statut: accept_drop(event, st),
                content=column_content,
            )
        )
    planning_select.on_change = lambda _: (refresh_steps(), page.update())
    view_switch.on_change = change_view
    refresh_steps()
    gantt_items = _gantt_items()
    date_debut_vue = (
        min(
            etape["debut"]
            for item in gantt_items
            for etape in item.get("etapes", [])
        )
        if gantt_items
        else date.today()
    )
    gantt_view = construire_gantt(
        gantt_items,
        date_debut_vue=date_debut_vue,
        nb_jours_vue=360,
        on_item_click=open_maquette_from_gantt,
        on_step_click=show_gantt_step,
        zoom=current_zoom,
    )
    zoom_controls = ft.Row(
        spacing=6,
        controls=[
            ft.OutlinedButton(
                label,
                icon=ft.icons.ZOOM_IN if zoom == "semaine" else ft.icons.CALENDAR_VIEW_MONTH,
                on_click=lambda _, z=zoom: change_zoom(z),
                disabled=current_zoom == zoom,
            )
            for zoom, label in [
                ("semaine", "Semaine"),
                ("mois", "Mois"),
                ("trimestre", "Trimestre"),
            ]
        ],
    )
    total_steps = sum(len(item.get("etapes", [])) for item in gantt_items)
    gantt_overview = ft.Row(
        wrap=True,
        controls=[
            _kpi_card("Maquettes planifiees", str(len(gantt_items))),
            _kpi_card("Etapes visibles", str(total_steps)),
            _kpi_card("Echelle active", current_zoom.capitalize()),
        ],
    )
    kanban_overview = ft.Row(
        wrap=True,
        controls=[
            _kpi_card("Maquettes planifiees", str(len(plannings))),
            _kpi_card(
                "En cours",
                str(sum(1 for planning in plannings if planning.statut_avancement == StatutAvancement.EN_COURS)),
            ),
            _kpi_card(
                "Terminees",
                str(sum(1 for planning in plannings if planning.statut_avancement == StatutAvancement.TERMINEE)),
            ),
        ],
    )
    kanban_editor = ft.Column(
        spacing=12,
        controls=[
            ft.Container(
                padding=12,
                border=ft.border.all(1, ft.colors.BLUE_GREY_100),
                border_radius=6,
                bgcolor=ft.colors.WHITE,
                content=ft.Column(
                    spacing=10,
                    controls=[
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Text("Vue d'ensemble", size=16, weight=ft.FontWeight.BOLD),
                                ft.Text(
                                    "Priorites recalculees depuis les vraies deadlines homologation",
                                    size=12,
                                    color=ft.colors.BLUE_GREY_700,
                                ),
                            ],
                        ),
                        kanban_overview,
                    ],
                ),
            ),
            ft.Container(
                padding=12,
                border=ft.border.all(1, ft.colors.BLUE_GREY_100),
                border_radius=6,
                bgcolor=ft.colors.WHITE,
                content=ft.Column(
                    spacing=10,
                    controls=[
                        ft.Text("Actions planning", size=16, weight=ft.FontWeight.BOLD),
                        ft.Text(
                            "Choisis une maquette pour creer son planning, puis selectionne un planning existant pour ajouter ou modifier ses etapes en bas de page.",
                            size=12,
                            color=ft.colors.BLUE_GREY_700,
                        ),
                        ft.Row(
                            [
                                maquette_select,
                                ft.ElevatedButton(
                                    "New Planning",
                                    icon=ft.icons.ADD_TASK,
                                    on_click=create_planning,
                                ),
                                planning_select,
                            ],
                            wrap=True,
                        ),
                    ],
                ),
            ),
            ft.Container(
                padding=12,
                border=ft.border.all(1, ft.colors.BLUE_GREY_100),
                border_radius=6,
                bgcolor=ft.colors.WHITE,
                content=ft.Column(
                    spacing=10,
                    controls=[
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Text("Kanban de construction", size=16, weight=ft.FontWeight.BOLD),
                                ft.Text(
                                    "Glisse une carte ou utilise les boutons de statut.",
                                    size=12,
                                    color=ft.colors.BLUE_GREY_700,
                                ),
                            ],
                        ),
                        ft.Row(
                            height=kanban_board_height,
                            scroll=ft.ScrollMode.ALWAYS,
                            controls=columns,
                        ),
                    ],
                ),
            ),
            ft.Container(
                padding=12,
                border=ft.border.all(1, ft.colors.BLUE_GREY_100),
                border_radius=6,
                bgcolor=ft.colors.WHITE,
                content=ft.Column(
                    spacing=10,
                    controls=[
                        ft.Text("Edition des etapes", size=16, weight=ft.FontWeight.BOLD),
                        ft.Row(
                            [
                                ordre_input,
                                libelle_input,
                                debut_input,
                                fin_input,
                                ft.ElevatedButton(
                                    "Add Step",
                                    icon=ft.icons.FORMAT_LIST_NUMBERED,
                                    on_click=add_step,
                                ),
                            ],
                            wrap=True,
                        ),
                        steps_rows,
                    ],
                ),
            ),
        ],
    )
    gantt_workspace = ft.Column(
        spacing=12,
        controls=[
            ft.Container(
                padding=12,
                border=ft.border.all(1, ft.colors.BLUE_GREY_100),
                border_radius=6,
                bgcolor=ft.colors.WHITE,
                content=ft.Column(
                    spacing=10,
                    controls=[
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Text("Vue d'ensemble", size=16, weight=ft.FontWeight.BOLD),
                                zoom_controls,
                            ],
                        ),
                        gantt_overview,
                    ],
                ),
            ),
            ft.Container(
                padding=12,
                border=ft.border.all(1, ft.colors.BLUE_GREY_100),
                border_radius=6,
                bgcolor=ft.colors.WHITE,
                content=ft.Column(
                    spacing=10,
                    controls=[
                        ft.Text("Gantt detaille par etape", size=16, weight=ft.FontWeight.BOLD),
                        ft.Text(
                            "Scroll horizontal: parcourir la timeline. Scroll vertical: parcourir les maquettes. Clique une etape pour lire son statut.",
                            size=12,
                            color=ft.colors.BLUE_GREY_700,
                        ),
                        gantt_view,
                    ],
                ),
            ),
            ft.Container(
                padding=12,
                border=ft.border.all(1, ft.colors.BLUE_GREY_100),
                border_radius=6,
                bgcolor=ft.colors.WHITE,
                content=ft.Column(
                    spacing=10,
                    controls=[
                        ft.Text("Details de l'etape selectionnee", size=16, weight=ft.FontWeight.BOLD),
                        selected_step_details,
                    ],
                ),
            ),
        ],
    )
    return ft.Column(
        expand=True,
        spacing=12,
        controls=[
            ft.Row(
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                controls=[
                    view_switch,
                    ft.ElevatedButton(
                        "Reorder by Urgency",
                        icon=ft.icons.SORT,
                        on_click=reorder,
                    ),
                ],
            ),
            gantt_workspace if current_view == "gantt" else kanban_editor,
        ],
    )


def _prediction_page(page: ft.Page, event_bus: EventBus | None) -> ft.Control:
    service = ProjectService(event_bus=event_bus)
    maquettes = service.lister_maquettes()
    prediction_rows = []
    result = ft.Column(
        spacing=8,
        controls=[
            ft.Container(
                padding=12,
                border_radius=6,
                bgcolor=ft.colors.BLUE_GREY_50,
                content=ft.Text(
                    "Lance une prediction pour afficher ici la DLL, la confiance, l'explication locale et les projets proches.",
                    size=12,
                    color=ft.colors.BLUE_GREY_700,
                ),
            )
        ],
    )
    maquette_select = ft.Dropdown(
        label="Maquette to predict *",
        options=[
            ft.dropdown.Option(str(m.id), f"#{m.id} | Project #{m.projet_id} | {m.composant_modifie}")
            for m in maquettes
        ],
        value=str(maquettes[0].id) if maquettes else None,
        expand=True,
    )
    with SessionLocal() as session:
        predictions = {
            row.maquette_id: row
            for row in session.scalars(
                select(models.Prediction).order_by(models.Prediction.created_at.desc())
            )
        }

    def predict(maquette_id: int) -> None:
        try:
            result.controls.clear()
            result.controls.append(
                ft.Container(
                    padding=12,
                    border_radius=6,
                    bgcolor=ft.colors.BLUE_50,
                    content=ft.Row(
                        spacing=8,
                        controls=[
                            ft.ProgressRing(width=18, height=18, stroke_width=2),
                            ft.Text("Prediction en cours...", weight=ft.FontWeight.BOLD),
                        ],
                    ),
                )
            )
            page.update()
            prediction = predire_dll_par_maquette_id(maquette_id)
            explanation = prediction.explanation
            selected_label = next(
                (
                    f"Maquette #{maquette.id} | Projet #{maquette.projet_id} | {maquette.composant_modifie}"
                    for maquette in maquettes
                    if maquette.id == maquette_id
                ),
                f"Maquette #{maquette_id}",
            )
            result.controls.clear()
            result.controls.extend(
                [
                    ft.Container(
                        padding=12,
                        border=ft.border.all(1, ft.colors.BLUE_GREY_100),
                        border_radius=6,
                        bgcolor=ft.colors.WHITE,
                        content=ft.Column(
                            spacing=10,
                            controls=[
                                ft.Text(selected_label, size=13, color=ft.colors.BLUE_GREY_700),
                                ft.Row(
                                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                    controls=[
                                        ft.Text(
                                            f"DLL predite: {prediction.predicted_dll} "
                                            f"({round(prediction.predicted_duration)} jours)",
                                            size=18,
                                            weight=ft.FontWeight.BOLD,
                                        ),
                                        _confidence_badge(prediction.confidence_level.value),
                                    ],
                                ),
                                ft.Text(
                                    f"Modele: {prediction.model_name} {prediction.model_version}",
                                    size=12,
                                    color=ft.colors.BLUE_GREY_700,
                                ),
                            ],
                        ),
                    ),
                    _prediction_steps_panel(prediction, maquette_id, maquettes),
                    _prediction_explanation_panel(explanation),
                    _prediction_neighbors_panel(prediction.voisins),
                ]
            )
            page.update()
        except Exception as exc:
            result.controls.clear()
            result.controls.append(
                ft.Container(
                    padding=12,
                    border_radius=6,
                    bgcolor=ft.colors.RED_50,
                    border=ft.border.all(1, ft.colors.RED_700),
                    content=ft.Text(str(exc), color=ft.colors.RED_700, weight=ft.FontWeight.BOLD),
                )
            )
            page.update()
            _message(page, str(exc), is_error=True)

    def predict_selected(_: ft.ControlEvent) -> None:
        maquette_select.error_text = None
        if not maquette_select.value:
            maquette_select.error_text = "Required"
            page.update()
            return
        predict(int(maquette_select.value))

    for maquette in maquettes:
        prediction = predictions.get(maquette.id)
        prediction_rows.append(
            ft.Container(
                padding=10,
                border=ft.border.only(bottom=ft.BorderSide(1, ft.colors.BLUE_GREY_100)),
                content=ft.Row(
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Text(str(maquette.id), width=70),
                        ft.Text(str(maquette.projet_id), width=80),
                        ft.Text(maquette.composant_modifie, width=300, no_wrap=True),
                        ft.Text(
                            str(prediction.predicted_dll) if prediction else "Non disponible",
                            width=180,
                        ),
                        ft.ElevatedButton(
                            "Predict Deadline",
                            icon=ft.icons.PLAY_ARROW,
                            on_click=lambda _, mid=maquette.id: predict(mid),
                            width=230,
                        ),
                    ],
                ),
            )
        )
    maquettes_panel = ft.Container(
        padding=12,
        border=ft.border.all(1, ft.colors.BLUE_GREY_100),
        border_radius=6,
        bgcolor=ft.colors.WHITE,
        content=ft.Column(
            spacing=10,
            controls=[
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Text("Maquettes a predire", size=16, weight=ft.FontWeight.BOLD),
                        _pill(f"{len(maquettes)} maquettes", ft.colors.BLUE_700, ft.colors.BLUE_50),
                    ],
                ),
                ft.Container(
                    padding=ft.padding.symmetric(horizontal=10, vertical=6),
                    bgcolor=ft.colors.BLUE_GREY_50,
                    border_radius=6,
                    content=ft.Row(
                        controls=[
                            ft.Text("Maquette", width=70, weight=ft.FontWeight.BOLD),
                            ft.Text("Projet", width=80, weight=ft.FontWeight.BOLD),
                            ft.Text("Composant", width=300, weight=ft.FontWeight.BOLD),
                            ft.Text("Derniere DLL", width=180, weight=ft.FontWeight.BOLD),
                            ft.Text("Action", width=230, weight=ft.FontWeight.BOLD),
                        ],
                    ),
                ),
                ft.Container(
                    height=360,
                    content=ft.ListView(
                        spacing=0,
                        controls=prediction_rows,
                    ),
                ),
            ],
        ),
    )
    return ft.Column(
        expand=True,
        spacing=12,
        scroll=ft.ScrollMode.ALWAYS,
        controls=[
            _section_header("DLL Prediction", ft.Container()),
            _form_card(
                "Run DLL Prediction",
                [
                    maquette_select,
                    ft.ElevatedButton(
                        "Run Prediction",
                        icon=ft.icons.AUTO_GRAPH_OUTLINED,
                        on_click=predict_selected,
                    ),
                ],
            ),
            ft.Container(
                padding=12,
                border=ft.border.all(1, ft.colors.BLUE_GREY_100),
                border_radius=6,
                bgcolor=ft.colors.WHITE,
                content=ft.Column(
                    spacing=10,
                    controls=[
                        ft.Text("Resultat et explicabilite", size=16, weight=ft.FontWeight.BOLD),
                        result,
                    ],
                ),
            ),
            maquettes_panel,
        ],
    )


def _ml_history_page(page: ft.Page, event_bus: EventBus | None) -> ft.Control:
    status = ft.Text(size=12)

    def train_real(_: ft.ControlEvent) -> None:
        try:
            status.value = "Entrainement production en cours..."
            page.update()
            report = entrainer_pipeline(output_path=PIPELINE_PATH, simulated=False)
            status.value = f"Run production ajoute : {report.meilleur_modele} | n={report.lignes_utilisables}"
            _message(page, "Historique ML mis a jour")
            _render_page(page, event_bus, "ml_history")
        except Exception as exc:
            status.value = str(exc)
            _message(page, str(exc), is_error=True)
            page.update()

    def simulate(_: ft.ControlEvent) -> None:
        try:
            status.value = "Generation simulation 500 projets en cours..."
            page.update()
            dataset_path = generer_dataset_simulation(n_rows=500)
            simulated_pipeline = SIMULATION_DATASET_PATH.with_name("simulated_deadline_pipeline.joblib")
            report = entrainer_pipeline(
                raw_path=dataset_path,
                output_path=simulated_pipeline,
                simulated=True,
            )
            status.value = (
                f"Simulation ajoutee : {dataset_path.name} | {report.meilleur_modele} | "
                f"n={report.lignes_utilisables}"
            )
            _message(page, "Simulation ML generee dans ml_models/")
            _render_page(page, event_bus, "ml_history")
        except Exception as exc:
            status.value = str(exc)
            _message(page, str(exc), is_error=True)
            page.update()

    runs = [run for run in read_run_history(limit=50) if run.get("pipeline") == "dll"]
    rows = []
    for run in runs:
        retained_mae = _run_retained_mae(run)
        rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(str(run.get("timestamp", "-"))[:16])),
                    ft.DataCell(ft.Text(str(run.get("model_name", "-")))),
                    ft.DataCell(_run_type_badge(run)),
                    ft.DataCell(ft.Text(str(run.get("n_rows", "-")))),
                    ft.DataCell(ft.Text(f"{retained_mae:.2f} j" if retained_mae is not None else "-")),
                    ft.DataCell(
                        ft.IconButton(
                            icon=ft.icons.VISIBILITY_OUTLINED,
                            tooltip="Voir le detail du run",
                            on_click=lambda _, selected=run: _open_run_detail(page, selected),
                        )
                    ),
                ]
            )
        )

    return ft.Column(
        expand=True,
        spacing=12,
        scroll=ft.ScrollMode.ALWAYS,
        controls=[
            _section_header("Historique ML", ft.Container()),
            ft.Container(
                padding=12,
                border_radius=6,
                bgcolor=ft.colors.RED_50,
                border=ft.border.all(1, ft.colors.RED_700),
                content=ft.Text(
                    "DONNEES SIMULEES - NE PAS UTILISER POUR DES DECISIONS REELLES. "
                    "Les runs simules servent uniquement a demontrer le comportement a 500 projets.",
                    color=ft.colors.RED_700,
                    weight=ft.FontWeight.BOLD,
                ),
            ),
            ft.Row(
                wrap=True,
                controls=[
                    ft.ElevatedButton("Entrainer modele reel", icon=ft.icons.MODEL_TRAINING, on_click=train_real),
                    ft.OutlinedButton(
                        "Mode simulation - donnees synthetiques",
                        icon=ft.icons.SCIENCE_OUTLINED,
                        on_click=simulate,
                    ),
                ],
            ),
            status,
            _ml_interpretation_panel(runs),
            _ml_history_chart(runs),
            ft.DataTable(
                columns=[
                    ft.DataColumn(ft.Text("Timestamp")),
                    ft.DataColumn(ft.Text("Modele")),
                    ft.DataColumn(ft.Text("Type")),
                    ft.DataColumn(ft.Text("N")),
                    ft.DataColumn(ft.Text("MAE retenu")),
                    ft.DataColumn(ft.Text("Detail")),
                ],
                rows=rows,
            ),
        ],
    )


def _run_retained_mae(run: dict) -> float | None:
    mae = run.get("mae", {})
    model_name = run.get("model_name")
    value = mae.get(model_name)
    return float(value) if value is not None else None


def _run_type_badge(run: dict) -> ft.Control:
    if run.get("is_low_volume"):
        return _pill("REEL N<5", ft.colors.ORANGE_700, ft.colors.ORANGE_50)
    if run.get("simulated"):
        return _pill("SIMULE", ft.colors.RED_700, ft.colors.RED_50)
    return _pill("REEL", ft.colors.GREEN_700, ft.colors.GREEN_50)


def _open_run_detail(page: ft.Page, run: dict) -> None:
    mae_rows = [
        ft.DataRow(
            cells=[
                ft.DataCell(ft.Text(str(name))),
                ft.DataCell(ft.Text(f"{float(value):.2f} j")),
            ]
        )
        for name, value in run.get("mae", {}).items()
    ]
    warning = ft.Container(
        visible=bool(run.get("is_low_volume")),
        padding=10,
        border_radius=6,
        bgcolor=ft.colors.ORANGE_50,
        content=ft.Text(
            "Run reel a tres faible volume : ce resultat est un artefact de test/demonstration, "
            "pas une preuve de performance production.",
            size=12,
            color=ft.colors.ORANGE_900,
        ),
    )
    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Detail du run"),
        content=ft.Column(
            tight=True,
            spacing=8,
            width=760,
            controls=[
                ft.Text(f"Run du {run.get('timestamp', '-')}", weight=ft.FontWeight.BOLD, size=16),
                ft.Row([_run_type_badge(run), _pill(str(run.get("pipeline", "dll")).upper(), ft.colors.BLUE_700, ft.colors.BLUE_50)]),
                warning,
                ft.Divider(),
                ft.Text("Comparaison des modeles (MAE en jours)", weight=ft.FontWeight.BOLD),
                ft.DataTable(
                    columns=[ft.DataColumn(ft.Text("Modele")), ft.DataColumn(ft.Text("MAE"))],
                    rows=mae_rows,
                ),
                ft.Divider(),
                ft.Text(f"Modele retenu : {run.get('model_name', '-')}", weight=ft.FontWeight.BOLD),
                ft.Text(f"Features utilisees : {', '.join(run.get('feature_set', []))}", size=12, color=ft.colors.BLUE_GREY_700),
                ft.Text(f"Volume de donnees : {run.get('n_rows', '-')} lignes", size=12, color=ft.colors.BLUE_GREY_700),
            ],
        ),
        actions=[ft.TextButton("Fermer", on_click=lambda _: _close_dialog(page))],
    )
    page.dialog = dialog
    dialog.open = True
    page.update()


def _close_dialog(page: ft.Page) -> None:
    if page.dialog:
        page.dialog.open = False
        page.update()


def _ml_interpretation_panel(runs: list[dict]) -> ft.Control:
    real_runs = [run for run in runs if not run.get("simulated") and not run.get("is_low_volume") and _run_retained_mae(run) is not None]
    simulated_runs = [run for run in runs if run.get("simulated") and _run_retained_mae(run) is not None]
    if not real_runs or not simulated_runs:
        text = "Lance au moins un entrainement reel valide et une simulation pour afficher une interpretation comparative."
    else:
        dernier_reel = max(real_runs, key=lambda item: item.get("timestamp", ""))
        dernier_simule = max(simulated_runs, key=lambda item: item.get("timestamp", ""))
        mae_reel = _run_retained_mae(dernier_reel) or 0.0
        mae_simule = _run_retained_mae(dernier_simule) or 0.0
        variation = ((mae_simule - mae_reel) / mae_reel) * 100 if mae_reel else 0.0
        direction = "baisse" if variation < 0 else "monte"
        text = (
            f"Avec {dernier_reel['n_rows']} projets reels, le MAE retenu est de {mae_reel:.1f} jours. "
            f"En simulant {dernier_simule['n_rows']} projets respectant la meme structure de donnees, "
            f"le MAE {direction} a {mae_simule:.1f} jours ({variation:+.0f}%). "
            "Ceci illustre une capacite de demonstration a plus grand volume ; ce n'est pas une mesure "
            "de performance actuelle en production."
        )
    return ft.Container(
        padding=12,
        border=ft.border.all(1, ft.colors.BLUE_GREY_100),
        border_radius=6,
        bgcolor=ft.colors.WHITE,
        content=ft.Text(text, size=12, color=ft.colors.BLUE_GREY_800),
    )


def _ml_history_chart(runs: list[dict]) -> ft.Control:
    real_runs = [run for run in runs if not run.get("simulated") and not run.get("is_low_volume")]
    simulated_runs = [run for run in runs if run.get("simulated")]
    if not real_runs or not simulated_runs:
        return ft.Container()
    real = max(real_runs, key=lambda item: item.get("timestamp", ""))
    simulated = max(simulated_runs, key=lambda item: item.get("timestamp", ""))
    models = ["baseline_residu_median", "ridge", "kneighbors"]
    values = [
        float(run.get("mae", {}).get(model) or 0)
        for run in [real, simulated]
        for model in models
    ]
    max_value = max(values) if values else 1.0
    return ft.Container(
        padding=12,
        border=ft.border.all(1, ft.colors.BLUE_GREY_100),
        border_radius=6,
        bgcolor=ft.colors.WHITE,
        content=ft.Column(
            spacing=8,
            controls=[
                ft.Text("Comparaison visuelle des MAE", size=16, weight=ft.FontWeight.BOLD),
                ft.Row(
                    spacing=18,
                    vertical_alignment=ft.CrossAxisAlignment.END,
                    controls=[
                        _mae_group_bars(f"Reel N={real.get('n_rows')}", real, models, max_value, ft.colors.BLUE_700),
                        _mae_group_bars(f"Simule N={simulated.get('n_rows')}", simulated, models, max_value, ft.colors.RED_700),
                    ],
                ),
            ],
        ),
    )


def _mae_group_bars(label: str, run: dict, models: list[str], max_value: float, color: str) -> ft.Control:
    return ft.Column(
        spacing=8,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Text(label, weight=ft.FontWeight.BOLD, size=12),
            ft.Row(
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.END,
                controls=[
                    _mae_bar(model, float(run.get("mae", {}).get(model) or 0), max_value, color)
                    for model in models
                ],
            ),
        ],
    )


def _mae_bar(model: str, value: float, max_value: float, color: str) -> ft.Control:
    label = {
        "baseline_residu_median": "Baseline",
        "ridge": "Ridge",
        "kneighbors": "k-NN",
    }.get(model, model)
    height = max(8, int((value / max(max_value, 1.0)) * 160))
    return ft.Column(
        spacing=4,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Text(f"{value:.1f}j", size=11),
            ft.Container(width=54, height=height, bgcolor=color, border_radius=4),
            ft.Text(label, size=11),
        ],
    )


def _coverage_page(page: ft.Page, event_bus: EventBus | None, user_id: int) -> ft.Control:
    project_service = ProjectService(event_bus=event_bus)
    homologation_service = HomologationService(event_bus=event_bus)
    maquettes = project_service.lister_maquettes()
    result = ft.Column(spacing=8, controls=[ft.Text("Selectionne une homologation puis lance la verification.")])
    homologation_options = []
    with SessionLocal() as session:
        homologations = list(
            session.scalars(
                select(models.Homologation).order_by(models.Homologation.id.desc())
            )
        )
        maquette_labels = {
            maquette.id: f"M#{maquette.id} | {maquette.composant_modifie}"
            for maquette in maquettes
        }
        for homologation in homologations:
            homologation_options.append(
                ft.dropdown.Option(
                    str(homologation.id),
                    f"H#{homologation.id} | {maquette_labels.get(homologation.maquette_id, 'Maquette inconnue')}",
                )
            )
        decisions = list(
            session.scalars(
                select(models.DecisionCouverture)
                .order_by(models.DecisionCouverture.date_decision.desc())
                .limit(12)
            )
        )
    dataset = charger_dataset_couverture()
    try:
        coverage_report = entrainer_couverture(output_path=COVERAGE_PIPELINE_PATH)
    except Exception as exc:
        coverage_report = None
        coverage_error = str(exc)
    else:
        coverage_error = None

    homologation_select = ft.Dropdown(
        label="Homologation a verifier",
        options=homologation_options,
        value=homologation_options[0].key if homologation_options else None,
        expand=True,
    )

    def verify(_: ft.ControlEvent) -> None:
        if not homologation_select.value:
            _message(page, "Aucune homologation disponible", is_error=True)
            return
        homologation_id = int(homologation_select.value)
        suggestion = homologation_service.verifier_couverture(homologation_id)
        ml_result = None
        ml_error = None
        try:
            with SessionLocal() as session:
                homologation = session.get(models.Homologation, homologation_id)
                maquette = session.get(models.Maquette, homologation.maquette_id) if homologation else None
                if maquette is not None:
                    ml_result = predire_couverture(maquette)
        except Exception as exc:
            ml_error = str(exc)
        status = "couvert" if suggestion.est_couverte else "non couvert"
        result.controls.clear()
        result.controls.extend(
            [
                ft.Row(
                    wrap=True,
                    controls=[
                        _comparison_panel(
                            "Moteur de regles",
                            [
                                ft.Text(f"Resultat: {status}"),
                                ft.Text(f"Projet couvrant: {suggestion.projet_couvrant_reference or '-'}"),
                                ft.Text(f"Justification: {suggestion.justification}"),
                            ],
                        ),
                        _comparison_panel(
                            "Classifieur ML",
                            [
                                ft.Text(
                                    "Resultat: "
                                    + (
                                        "couvert"
                                        if ml_result and ml_result.est_couverte
                                        else "non couvert"
                                        if ml_result
                                        else "non disponible"
                                    )
                                ),
                                ft.Text(f"Confiance: {ml_result.confiance}" if ml_result else f"Erreur: {ml_error or '-'}"),
                                ft.Text(f"Modele: {ml_result.model_name}" if ml_result else "Modele: -"),
                                ft.Text(f"Circularite: {'oui' if ml_result and ml_result.circularite_detectee else 'non'}"),
                            ],
                        ),
                    ],
                ),
                ft.Row(
                    wrap=True,
                    controls=[
                        ft.ElevatedButton(
                            "Valider la suggestion",
                            icon=ft.icons.CHECK,
                            on_click=lambda _: _save_coverage_decision(
                                page,
                                event_bus,
                                user_id,
                                suggestion,
                                validate=True,
                            ),
                        ),
                        ft.OutlinedButton(
                            "Modifier / refuser",
                            icon=ft.icons.EDIT,
                            on_click=lambda _: _save_coverage_decision(
                                page,
                                event_bus,
                                user_id,
                                suggestion,
                                validate=False,
                            ),
                        ),
                    ],
                ),
            ]
        )
        page.update()

    decision_cards = []
    with SessionLocal() as session:
        for decision in decisions:
            homologation = session.get(models.Homologation, decision.homologation_id)
            maquette = session.get(models.Maquette, homologation.maquette_id) if homologation else None
            projet = session.get(models.Projet, maquette.projet_id) if maquette else None
            decision_cards.append(
                ft.Container(
                    padding=10,
                    border=ft.border.all(1, ft.colors.BLUE_GREY_100),
                    border_radius=6,
                    bgcolor=ft.colors.WHITE,
                    content=ft.Column(
                        spacing=4,
                        controls=[
                            ft.Row(
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                                controls=[
                                    ft.Text(f"Decision #{decision.id} | H#{decision.homologation_id}", weight=ft.FontWeight.BOLD),
                                    _pill("couvert" if decision.est_couverte else "non couvert", ft.colors.GREEN_700 if decision.est_couverte else ft.colors.RED_700, ft.colors.GREEN_50 if decision.est_couverte else ft.colors.RED_50),
                                ],
                            ),
                            ft.Text(f"Projet: {projet.reference if projet else '-'}", size=12),
                            ft.Text(decision.justification, size=12, color=ft.colors.BLUE_GREY_700),
                        ],
                    ),
                )
            )

    return ft.Column(
        expand=True,
        spacing=12,
        scroll=ft.ScrollMode.ALWAYS,
        controls=[
            _section_header("Couverture", ft.Container()),
            ft.Container(
                padding=12,
                border=ft.border.all(1, ft.colors.BLUE_GREY_100),
                border_radius=6,
                bgcolor=ft.colors.WHITE,
                content=ft.Column(
                    spacing=8,
                    controls=[
                        ft.Text("Diagnostic ML couverture", size=16, weight=ft.FontWeight.BOLD),
                        ft.Text(
                            (
                                f"n={len(dataset)}, circularite={coverage_report.circularite_detectee}, "
                                f"modele={coverage_report.meilleur_modele}. {coverage_report.conclusion}"
                                if coverage_report
                                else f"Diagnostic indisponible: {coverage_error}"
                            ),
                            size=12,
                            color=ft.colors.BLUE_GREY_700,
                        ),
                    ],
                ),
            ),
            ft.Container(
                padding=12,
                border=ft.border.all(1, ft.colors.BLUE_GREY_100),
                border_radius=6,
                bgcolor=ft.colors.WHITE,
                content=ft.Column(
                    spacing=10,
                    controls=[
                        ft.Text("Verifier une couverture", size=16, weight=ft.FontWeight.BOLD),
                        ft.Row([homologation_select, ft.ElevatedButton("Verifier", icon=ft.icons.FACT_CHECK_OUTLINED, on_click=verify)], wrap=True),
                        result,
                    ],
                ),
            ),
            ft.Container(
                padding=12,
                border=ft.border.all(1, ft.colors.BLUE_GREY_100),
                border_radius=6,
                bgcolor=ft.colors.WHITE,
                content=ft.Column(
                    spacing=10,
                    controls=[
                        ft.Text("Decisions recentes", size=16, weight=ft.FontWeight.BOLD),
                        ft.Column(spacing=8, controls=decision_cards or [ft.Text("Aucune decision de couverture.")]),
                    ],
                ),
            ),
        ],
    )


def _save_coverage_decision(page, event_bus, user_id: int, suggestion, validate: bool) -> None:
    try:
        HomologationService(event_bus=event_bus).enregistrer_decision_couverture(
            homologation_id=suggestion.homologation_id,
            est_couverte=suggestion.est_couverte if validate else False,
            projet_couvrant_id=suggestion.projet_couvrant_id if validate else None,
            justification=suggestion.justification if validate else "Suggestion modifiee/refusee manuellement.",
            utilisateur_id=user_id,
        )
        _message(page, "Decision de couverture enregistree")
        _render_page(page, event_bus, "coverage")
    except Exception as exc:
        _message(page, str(exc), is_error=True)


def _cdc_maquette_labels(session_factory=SessionLocal) -> dict[int, dict]:
    with session_factory() as session:
        rows = session.execute(
            select(
                models.Maquette.id,
                models.Projet.reference,
                models.Maquette.modele,
                models.Silhouette.libelle,
                models.Maquette.composant_modifie,
                func.count(models.LigneCDC.id),
            )
            .join(models.Projet, models.Projet.id == models.Maquette.projet_id)
            .join(models.Silhouette, models.Silhouette.id == models.Maquette.silhouette_id)
            .outerjoin(models.LigneCDC, models.LigneCDC.maquette_id == models.Maquette.id)
            .group_by(
                models.Maquette.id,
                models.Projet.reference,
                models.Maquette.modele,
                models.Silhouette.libelle,
                models.Maquette.composant_modifie,
            )
        )
        labels = {}
        for maquette_id, reference, modele, silhouette, composant, count in rows:
            prefix = "CDC reel" if str(reference).startswith(("HIST-CDC", "HIST-PIECES")) else "Suivi reel"
            labels[maquette_id] = {
                "reference": reference,
                "line_count": int(count or 0),
                "label": (
                    f"#{maquette_id} | {prefix} | {reference} | "
                    f"{modele or '-'} | {silhouette or '-'} | "
                    f"{int(count or 0)} lignes CDC | {composant}"
                ),
            }
        return labels


def _cdc_page(page: ft.Page, event_bus: EventBus | None, user_id: int) -> ft.Control:
    service = ProjectService(event_bus=event_bus)
    refs = service.charger_referentiels()
    auto_feedback = page.session.get("cdc_auto_feedback") or ""
    page.session.set("cdc_auto_feedback", "")
    maquette_labels = _cdc_maquette_labels()
    maquettes = sorted(
        service.lister_maquettes(),
        key=lambda item: (
            0 if maquette_labels.get(item.id, {}).get("line_count", 0) else 1,
            str(maquette_labels.get(item.id, {}).get("reference", "")),
            item.id,
        ),
    )
    selected_maquette_id = page.session.get("selected_maquette_id")
    available_maquette_ids = {str(maquette.id) for maquette in maquettes}
    initial_maquette = (
        selected_maquette_id
        if selected_maquette_id in available_maquette_ids
        else str(maquettes[0].id)
        if maquettes
        else None
    )
    maquette_select = ft.Dropdown(
        label="Maquette *",
        options=[
            ft.dropdown.Option(
                str(m.id),
                maquette_labels.get(m.id, {}).get(
                    "label",
                    f"#{m.id} | {m.composant_modifie}",
                ),
            )
            for m in maquettes
        ],
        value=initial_maquette,
        expand=True,
    )
    type_select = _dropdown("Type composant", refs.types_composants)
    qty = ft.TextField(label="HW quantity *", value="1", width=140)
    line_select = ft.Dropdown(label="CDC line to modify/delete", dense=True, expand=True)
    search_input = ft.TextField(
        label="Search component",
        hint_text="Ex: T1, T10...",
        dense=True,
        prefix_icon=ft.icons.SEARCH,
        width=260,
    )
    rows = ft.ListView(spacing=6, height=360)
    planning_rows = ft.Column(spacing=4, scroll=ft.ScrollMode.AUTO, height=190)
    output = ft.Text(size=12)

    def selected_maquette() -> int:
        if not maquette_select.value:
            raise ValueError("Selectionne une maquette")
        return int(maquette_select.value)

    def refresh() -> None:
        rows.controls.clear()
        line_select.options.clear()
        planning_rows.controls.clear()
        if not maquette_select.value:
            return
        cdc_lines = sorted(
            service.lister_lignes_cdc(selected_maquette()),
            key=lambda item: item.type_composant_code,
        )
        search_text = (search_input.value or "").strip().upper()
        if search_text:
            cdc_lines = [
                line
                for line in cdc_lines
                if search_text in line.type_composant_code.upper()
            ]
        print(f"{len(cdc_lines)} lignes CDC a afficher pour maquette #{selected_maquette()}")
        for line in cdc_lines:
            origin = "auto" if line.origine == OrigineSuggestion.SUGGESTION_AUTO else "manuel"
            source_label = line.suggestion_source or origin
            label = f"{line.type_composant_code} x{line.quantite_hw}"
            line_select.options.append(ft.dropdown.Option(str(line.id), label))
            rows.controls.append(
                ft.Container(
                    padding=10,
                    border=ft.border.all(1, ft.colors.BLUE_GREY_100),
                    border_radius=6,
                    bgcolor=ft.colors.WHITE,
                    content=ft.Row(
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        controls=[
                            ft.Row(
                                spacing=10,
                                controls=[
                                    ft.Text(f"#{line.id}", width=48, weight=ft.FontWeight.BOLD),
                                    ft.Text(line.type_composant_code, width=90, weight=ft.FontWeight.BOLD),
                                    ft.Text(f"Quantite HW: {line.quantite_hw}", width=150),
                                    _pill(source_label, ft.colors.BLUE_700, ft.colors.BLUE_50),
                                ],
                            ),
                            ft.Row(
                                tight=True,
                                spacing=6,
                                controls=[
                                    ft.OutlinedButton(
                                        "Modify",
                                        icon=ft.icons.EDIT_OUTLINED,
                                        on_click=lambda _, lid=line.id: select_line(lid),
                                    ),
                                    ft.OutlinedButton(
                                        "Delete",
                                        icon=ft.icons.DELETE_OUTLINE,
                                        on_click=lambda _, lid=line.id: delete_line(lid),
                                    ),
                                ],
                            ),
                        ],
                        wrap=True,
                    ),
                )
            )
        if not rows.controls:
            rows.controls.append(
                ft.Container(
                    padding=16,
                    border_radius=6,
                    bgcolor=ft.colors.BLUE_GREY_50,
                    content=ft.Text(
                        _cdc_empty_message(bool(search_text)),
                        color=ft.colors.BLUE_GREY_700,
                    ),
                )
            )
        if line_select.options:
            line_select.value = line_select.options[0].key
        with SessionLocal() as session:
            planning = session.scalar(
                select(models.PlanningConstruction).where(
                    models.PlanningConstruction.maquette_id == selected_maquette()
                )
            )
            if planning is None:
                planning_rows.controls.append(
                    ft.Text("Aucun planning theorique pour cette maquette.", size=12)
                )
            else:
                etapes = list(
                    session.scalars(
                        select(models.EtapeConstruction)
                        .where(models.EtapeConstruction.planning_id == planning.id)
                        .order_by(models.EtapeConstruction.ordre)
                    )
                )
                for etape in etapes:
                    planning_rows.controls.append(
                        ft.Container(
                            padding=8,
                            border=ft.border.all(1, ft.colors.BLUE_GREY_100),
                            border_radius=6,
                            content=ft.Row(
                                controls=[
                                    ft.Text(str(etape.ordre), width=32, weight=ft.FontWeight.BOLD),
                                    ft.Text(etape.libelle, expand=True),
                                    ft.Text(f"{etape.date_debut or '-'} -> {etape.date_fin or '-'}", width=210),
                                    _pill("estime", ft.colors.BLUE_700, ft.colors.BLUE_50),
                                ],
                                wrap=True,
                            ),
                        )
                    )

    def select_line(line_id: int) -> None:
        line_select.value = str(line_id)
        page.update()

    def delete_line(line_id: int) -> None:
        try:
            service.supprimer_ligne_cdc(line_id)
            _render_page(page, event_bus, "cdc")
        except Exception as exc:
            _message(page, str(exc), is_error=True)

    def add(_: ft.ControlEvent) -> None:
        try:
            if not type_select.value or not qty.value:
                raise ValueError("Type composant and quantity are required")
            service.ajouter_ligne_cdc(selected_maquette(), int(type_select.value), int(qty.value or "1"))
            _render_page(page, event_bus, "cdc")
        except Exception as exc:
            _message(page, str(exc), is_error=True)

    def update(_: ft.ControlEvent) -> None:
        try:
            if line_select.value:
                service.modifier_ligne_cdc(int(line_select.value), int(qty.value or "1"))
                _render_page(page, event_bus, "cdc")
        except Exception as exc:
            _message(page, str(exc), is_error=True)

    def delete(_: ft.ControlEvent) -> None:
        if line_select.value:
            delete_line(int(line_select.value))

    def pdf(_: ft.ControlEvent) -> None:
        try:
            output.value = "Generation CDC en cours..."
            page.update()
            path = service.generer_cdc(selected_maquette())
            output.value = f"CDC genere : {path}"
            _message(page, f"CDC genere : {path.name}")
            page.update()
        except Exception as exc:
            output.value = f"Erreur generation CDC : {exc}"
            _message(page, str(exc), is_error=True)
            page.update()

    maquette_select.on_change = lambda _: (refresh(), page.update())
    search_input.on_change = lambda _: (refresh(), page.update())
    refresh()
    return ft.Column(
        expand=True,
        spacing=12,
        scroll=ft.ScrollMode.ALWAYS,
        controls=[
            _section_header(
                "Nomenclature CDC",
                ft.ElevatedButton("Generate CDC PDF", icon=ft.icons.PICTURE_AS_PDF, on_click=pdf),
            ),
            _cdc_auto_feedback_banner(auto_feedback),
            maquette_select,
            ft.Container(
                padding=10,
                border_radius=6,
                bgcolor=ft.colors.BLUE_GREY_50,
                content=ft.Row(
                    spacing=8,
                    controls=[
                        ft.Icon(ft.icons.INFO_OUTLINE, size=16, color=ft.colors.BLUE_GREY_700),
                        ft.Text(
                            "Le bouton genere le fichier PDF CDC dans le dossier Downloads de l'utilisateur.",
                            size=12,
                            color=ft.colors.BLUE_GREY_700,
                        ),
                    ],
                ),
            ),
            _form_card("Add / Modify CDC Line", [ft.Row([type_select, qty], wrap=True), line_select]),
            ft.Row(
                [
                    ft.ElevatedButton("Add Line", icon=ft.icons.ADD, on_click=add),
                    ft.OutlinedButton("Modify Selected Line", icon=ft.icons.EDIT_OUTLINED, on_click=update),
                    ft.OutlinedButton("Delete Selected Line", icon=ft.icons.DELETE_OUTLINE, on_click=delete),
                ],
                wrap=True,
            ),
            output,
            ft.Container(
                padding=12,
                border=ft.border.all(1, ft.colors.BLUE_GREY_100),
                border_radius=6,
                bgcolor=ft.colors.WHITE,
                content=ft.Column(
                    spacing=10,
                    controls=[
                        ft.Row(
                            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            controls=[
                                ft.Text("Lignes CDC", size=16, weight=ft.FontWeight.BOLD),
                                search_input,
                            ],
                        ),
                        ft.Container(
                            padding=ft.padding.symmetric(horizontal=10, vertical=6),
                            border_radius=6,
                            bgcolor=ft.colors.BLUE_GREY_50,
                            content=ft.Row(
                                controls=[
                                    ft.Text("ID", width=48, weight=ft.FontWeight.BOLD),
                                    ft.Text("Type", width=90, weight=ft.FontWeight.BOLD),
                                    ft.Text("Quantite", width=150, weight=ft.FontWeight.BOLD),
                                    ft.Text("Source", width=120, weight=ft.FontWeight.BOLD),
                                    ft.Text("Actions", expand=True, weight=ft.FontWeight.BOLD),
                                ],
                            ),
                        ),
                        rows,
                    ],
                ),
            ),
            ft.Text("Planning theorique de la maquette", size=16, weight=ft.FontWeight.BOLD),
            planning_rows,
        ],
    )


def _notifications_page(page: ft.Page, event_bus: EventBus | None, user_id: int) -> ft.Control:
    service = NotificationService()
    selected_filter = ft.Tabs(
        selected_index=0,
        tabs=[
            ft.Tab(text="Toutes"),
            ft.Tab(text="Deadlines"),
            ft.Tab(text="Changements"),
            ft.Tab(text="Systeme"),
        ],
    )
    rows = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO, expand=True)

    def refresh() -> None:
        rows.controls.clear()
        notifications = service.lister(user_id)
        for notification in notifications:
            if selected_filter.selected_index == 1 and notification.type != TypeNotification.ALERTE_RETARD:
                continue
            if selected_filter.selected_index == 2 and notification.type != TypeNotification.CHANGEMENT_STATUT:
                continue
            if selected_filter.selected_index == 3 and notification.type in {
                TypeNotification.ALERTE_RETARD,
                TypeNotification.CHANGEMENT_STATUT,
            }:
                continue
            color = ft.colors.RED_700 if notification.type == TypeNotification.ALERTE_RETARD else ft.colors.BLUE_700
            rows.controls.append(
                ft.Container(
                    padding=10,
                    border=ft.border.all(1, ft.colors.BLUE_GREY_100),
                    border_radius=6,
                    content=ft.Row(
                        controls=[
                            ft.Icon(ft.icons.CIRCLE, color=color, size=12),
                            ft.Text(notification.message, expand=True),
                            _read_badge(notification.lu),
                        ]
                    ),
                    on_click=lambda _, nid=notification.id: (
                        service.marquer_lue(nid),
                        _render_page(page, event_bus, "notifications"),
                    ),
                )
            )

    selected_filter.on_change = lambda _: (refresh(), page.update())
    refresh()
    return ft.Column(expand=True, controls=[selected_filter, rows])


def _settings_page() -> ft.Control:
    return ft.Column(
        controls=[
            ft.Text("Parametres", size=18, weight=ft.FontWeight.BOLD),
            ft.Text("Non disponible"),
        ]
    )


def _cdc_empty_message(has_filter: bool) -> str:
    if has_filter:
        return "Aucune ligne CDC trouvee pour ce filtre."
    return "Aucune suggestion disponible, saisie manuelle requise."


def _cdc_auto_feedback_banner(message: str) -> ft.Control:
    if not message:
        return ft.Container(visible=False)
    is_missing = "Aucune suggestion" in message
    color = ft.colors.ORANGE_700 if is_missing else ft.colors.GREEN_700
    bgcolor = ft.colors.ORANGE_50 if is_missing else ft.colors.GREEN_50
    icon = ft.icons.WARNING_AMBER_OUTLINED if is_missing else ft.icons.CHECK_CIRCLE_OUTLINE
    return ft.Container(
        padding=12,
        border=ft.border.all(1, color),
        border_radius=6,
        bgcolor=bgcolor,
        content=ft.Row(
            spacing=8,
            controls=[
                ft.Icon(icon, color=color, size=20),
                ft.Text(message, color=color, weight=ft.FontWeight.BOLD),
            ],
        ),
    )


def _dashboard_data() -> dict:
    today = date.today()
    soon = today + timedelta(days=7)
    with SessionLocal() as session:
        projets_actifs = session.scalar(
            select(func.count(models.Projet.id)).where(
                models.Projet.statut != StatutProjet.TERMINEE
            )
        ) or 0
        total_decisions = session.scalar(select(func.count(models.DecisionCouverture.id))) or 0
        covered_decisions = session.scalar(
            select(func.count(models.DecisionCouverture.id)).where(
                models.DecisionCouverture.est_couverte == True
            )
        ) or 0
        deadlines = session.scalar(
            select(func.count(models.Homologation.id))
            .where(models.Homologation.date_deadline.is_not(None))
            .where(models.Homologation.date_deadline >= today)
            .where(models.Homologation.date_deadline <= soon)
        ) or 0
        recent_projects = list(
            session.scalars(
                select(models.Projet).order_by(models.Projet.date_creation.desc()).limit(5)
            )
        )
        rows = []
        for projet in recent_projects:
            maquette = session.scalar(
                select(models.Maquette).where(models.Maquette.projet_id == projet.id).limit(1)
            )
            silhouette = session.get(models.Silhouette, maquette.silhouette_id) if maquette else None
            homologation = session.scalar(
                select(models.Homologation)
                .where(models.Homologation.maquette_id == maquette.id)
                .order_by(models.Homologation.id.desc())
                .limit(1)
            ) if maquette else None
            rows.append(
                {
                    "id": projet.id,
                    "reference": projet.reference,
                    "silhouette": silhouette.libelle if silhouette else None,
                    "statut": projet.statut.value,
                    "deadline": str(homologation.date_deadline) if homologation and homologation.date_deadline else None,
                }
            )
        suggestion = _last_coverage_suggestion(session)
    percent = round((covered_decisions / total_decisions) * 100) if total_decisions else 0
    return {
        "projets_actifs": projets_actifs,
        "homologations_evitees": percent,
        "deadlines_7j": deadlines,
        "projets_recents": rows,
        "suggestion_couverture": suggestion,
    }


def _last_coverage_suggestion(session) -> str | None:
    homologation = session.scalar(
        select(models.Homologation)
        .outerjoin(models.DecisionCouverture)
        .where(models.DecisionCouverture.id.is_(None))
        .order_by(models.Homologation.id.desc())
        .limit(1)
    )
    if homologation is None:
        return None
    try:
        suggestion = HomologationService().verifier_couverture(homologation.id)
    except Exception:
        return None
    status = "couvert" if suggestion.est_couverte else "non couvert"
    return f"Homologation #{homologation.id}: {status}"


def _gantt_items(session_factory=SessionLocal) -> list[dict]:
    items: list[dict] = []
    with session_factory() as session:
        plannings = list(
            session.scalars(
                select(models.PlanningConstruction).order_by(
                    models.PlanningConstruction.priorite_score.desc().nullslast(),
                    models.PlanningConstruction.id.desc(),
                )
            )
        )
        for index, planning in enumerate(plannings, start=1):
            maquette = session.get(models.Maquette, planning.maquette_id)
            if maquette is None:
                continue
            projet = session.get(models.Projet, maquette.projet_id)
            homologation = session.scalar(
                select(models.Homologation)
                .where(models.Homologation.maquette_id == maquette.id)
                .order_by(models.Homologation.id.desc())
                .limit(1)
            )
            db_steps = list(
                session.scalars(
                    select(models.EtapeConstruction)
                    .where(models.EtapeConstruction.planning_id == planning.id)
                    .order_by(models.EtapeConstruction.ordre)
                )
            )
            etapes = [
                {
                    "libelle": etape.libelle,
                    "debut": etape.date_debut or maquette.date_creation,
                    "fin": etape.date_fin or etape.date_debut or maquette.date_creation + timedelta(days=1),
                    "statut": etape.statut.value,
                }
                for etape in db_steps
            ]
            if not etapes:
                debut = (
                    homologation.date_cmde
                    if homologation and homologation.date_cmde
                    else maquette.date_creation
                )
                fin = (
                    homologation.date_deadline
                    if homologation and homologation.date_deadline
                    else max(date.today(), debut + timedelta(days=1))
                )
                etapes = [
                    {
                        "libelle": "Planning global",
                        "debut": debut,
                        "fin": max(fin, debut + timedelta(days=1)),
                        "statut": "A_VENIR",
                    }
                ]
            for etape in etapes:
                if etape["fin"] < etape["debut"]:
                    etape["fin"] = etape["debut"] + timedelta(days=1)
            jalons = []
            if homologation and homologation.date_livraison_cdc:
                jalons.append(
                    {
                        "libelle": "Livraison CDC",
                        "date": homologation.date_livraison_cdc,
                        "couleur": ft.colors.BLUE_700,
                    }
                )
            if homologation and homologation.date_deadline:
                jalons.append(
                    {
                        "libelle": "Dead Line contractuelle",
                        "date": homologation.date_deadline,
                        "couleur": ft.colors.RED_700,
                    }
                )
            items.append(
                {
                    "maquette_id": maquette.id,
                    "label": f"{projet.reference if projet else 'Projet ?'} - M#{maquette.id}",
                    "rang": index,
                    "priorite_score": planning.priorite_score,
                    "etapes": etapes,
                    "jalons": jalons,
                }
            )
    return items


def _gantt_status_style(session, homologation, today: date) -> tuple[str, str]:
    if homologation is None:
        return ft.colors.AMBER_700, ft.icons.HOURGLASS_EMPTY
    if (
        homologation.date_deadline is not None
        and homologation.date_deadline < today
        and homologation.statut != StatutHomologation.TERMINEE
    ):
        return ft.colors.RED_700, ft.icons.WARNING_AMBER_OUTLINED
    decision_couverte = session.scalar(
        select(models.DecisionCouverture.id)
        .where(models.DecisionCouverture.homologation_id == homologation.id)
        .where(models.DecisionCouverture.est_couverte == True)
        .limit(1)
    )
    if decision_couverte is not None or homologation.statut == StatutHomologation.TERMINEE:
        return ft.colors.GREEN_700, ft.icons.CHECK_CIRCLE_OUTLINE
    if homologation.statut == StatutHomologation.EN_ATTENTE or homologation.date_deadline is None:
        return ft.colors.AMBER_700, ft.icons.HOURGLASS_EMPTY
    return ft.colors.GREEN_700, ft.icons.CHECK_CIRCLE_OUTLINE


def _kpi_card(title: str, value: str) -> ft.Control:
    return ft.Container(
        width=210,
        padding=14,
        border=ft.border.all(1, ft.colors.BLUE_GREY_100),
        border_radius=6,
        content=ft.Column(
            spacing=4,
            controls=[
                ft.Text(title, size=12, color=ft.colors.BLUE_GREY_600),
                ft.Text(value, size=22, weight=ft.FontWeight.BOLD),
            ],
        ),
    )


def _section_header(title: str, action: ft.Control) -> ft.Control:
    return ft.Row(
        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        controls=[
            ft.Text(title, size=20, weight=ft.FontWeight.BOLD),
            action,
        ],
    )


def _form_card(title: str, controls: list[ft.Control]) -> ft.Control:
    return ft.Container(
        padding=14,
        border=ft.border.all(1, ft.colors.BLUE_GREY_100),
        border_radius=6,
        bgcolor=ft.colors.WHITE,
        content=ft.Column(
            spacing=12,
            controls=[
                ft.Text(title, size=16, weight=ft.FontWeight.BOLD),
                *controls,
            ],
        ),
    )


def _comparison_panel(title: str, controls: list[ft.Control]) -> ft.Control:
    return ft.Container(
        width=360,
        padding=12,
        border=ft.border.all(1, ft.colors.BLUE_GREY_100),
        border_radius=6,
        bgcolor=ft.colors.BLUE_GREY_50,
        content=ft.Column(
            spacing=6,
            controls=[
                ft.Text(title, weight=ft.FontWeight.BOLD),
                *controls,
            ],
        ),
    )


def _dropdown(label: str, items) -> ft.Dropdown:
    options = [ft.dropdown.Option(str(item.id), item.label) for item in items]
    return ft.Dropdown(
        label=label,
        dense=True,
        width=190,
        options=options,
        value=options[0].key if options else None,
    )


def _filter_dropdown(label: str, items) -> ft.Dropdown:
    return ft.Dropdown(
        label=label,
        dense=True,
        width=190,
        options=[
            ft.dropdown.Option("ALL", "Tous"),
            *[ft.dropdown.Option(str(item.id), item.label) for item in items],
        ],
        value="ALL",
    )


def _optional_int(value) -> int | None:
    if value in {None, "", "ALL"}:
        return None
    return int(value)


def _parse_optional_date(value: str | None) -> date | None:
    text = (value or "").strip()
    if not text:
        return None
    return date.fromisoformat(text)


def _confidence_badge(level: str) -> ft.Control:
    styles = {
        "HIGH": (ft.colors.GREEN_700, ft.colors.GREEN_50, "Haute"),
        "MEDIUM": (ft.colors.ORANGE_700, ft.colors.ORANGE_50, "Moyenne"),
        "LOW": (ft.colors.RED_700, ft.colors.RED_50, "Basse"),
    }
    color, bgcolor, label = styles.get(
        level,
        (ft.colors.BLUE_GREY_700, ft.colors.BLUE_GREY_50, level),
    )
    return ft.Container(
        padding=ft.padding.symmetric(horizontal=10, vertical=6),
        border_radius=6,
        bgcolor=bgcolor,
        border=ft.border.all(1, color),
        content=ft.Row(
            tight=True,
            spacing=6,
            controls=[
                ft.Icon(ft.icons.VERIFIED_OUTLINED, size=16, color=color),
                ft.Text(f"Confiance: {label}", color=color, weight=ft.FontWeight.BOLD),
            ],
        ),
    )


def _prediction_explanation_panel(explanation: dict) -> ft.Control:
    if str(explanation.get("model_name", "")).startswith("baseline"):
        return ft.Container(
            padding=12,
            border=ft.border.all(1, ft.colors.BLUE_GREY_100),
            border_radius=6,
            bgcolor=ft.colors.ORANGE_50,
            content=ft.Column(
                spacing=8,
                controls=[
                    ft.Text("Explication locale", size=15, weight=ft.FontWeight.BOLD),
                    ft.Text(
                        "Ce resultat utilise le modele baseline mediane. "
                        "La baseline ne lit pas les variables une par une, donc aucune "
                        "explication LIME/SHAP par variable n'est applicable.",
                        size=12,
                        color=ft.colors.ORANGE_900,
                    ),
                ],
            ),
        )
    contributions = explanation.get("contributions", [])
    has_signal = any(abs(item.get("impact_jours", 0)) > 0 for item in contributions)
    return ft.Container(
        padding=12,
        border=ft.border.all(1, ft.colors.BLUE_GREY_100),
        border_radius=6,
        bgcolor=ft.colors.BLUE_GREY_50,
        content=ft.Column(
            spacing=10,
            controls=[
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Text("Explication locale", size=15, weight=ft.FontWeight.BOLD),
                        _pill(explanation.get("method", "LIME-like"), ft.colors.BLUE_700, ft.colors.BLUE_50),
                    ],
                ),
                ft.Text(explanation.get("note", ""), size=12, color=ft.colors.BLUE_GREY_700),
                ft.Container(
                    visible=not has_signal,
                    padding=10,
                    border_radius=6,
                    bgcolor=ft.colors.ORANGE_50,
                    content=ft.Text(
                        "Le modele retenu reagit peu ou pas aux variables pour cette prediction. "
                        "C'est attendu si la baseline mediane a gagne pendant l'entrainement.",
                        size=12,
                        color=ft.colors.ORANGE_900,
                    ),
                ),
                ft.Column(
                    spacing=6,
                    controls=[_feature_impact_row(item) for item in contributions],
                ),
            ],
        ),
    )


def _prediction_steps_panel(prediction, maquette_id: int, maquettes: list) -> ft.Control:
    maquette = next((item for item in maquettes if item.id == maquette_id), None)
    date_depart = maquette.date_creation if maquette is not None else date.today()
    residu = round(prediction.predicted_duration) - 231
    etapes = generer_planning_theorique(date_depart, residu_predit=residu)
    total = sum(max((etape.date_fin_estimee - etape.date_debut_estimee).days, 0) for etape in etapes)

    rows = []
    for index, etape in enumerate(etapes, start=1):
        duree = max((etape.date_fin_estimee - etape.date_debut_estimee).days, 0)
        rows.append(
            ft.DataRow(
                cells=[
                    ft.DataCell(ft.Text(str(index))),
                    ft.DataCell(ft.Text(etape.libelle, weight=ft.FontWeight.BOLD)),
                    ft.DataCell(ft.Text(str(etape.date_debut_estimee))),
                    ft.DataCell(ft.Text(str(etape.date_fin_estimee))),
                    ft.DataCell(_pill(f"{duree} j", ft.colors.BLUE_700, ft.colors.BLUE_50)),
                ]
            )
        )

    return ft.Container(
        padding=12,
        border=ft.border.all(1, ft.colors.BLUE_GREY_100),
        border_radius=6,
        bgcolor=ft.colors.WHITE,
        content=ft.Column(
            spacing=10,
            controls=[
                ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Text("Detail previsionnel par etape", size=15, weight=ft.FontWeight.BOLD),
                        _pill(f"Total depuis CDC {total} j", ft.colors.GREEN_700, ft.colors.GREEN_50),
                    ],
                ),
                ft.Text(
                    "Le planning demarre a la phase Cahier des charges, puis applique le gabarit R116 et le residu predit.",
                    size=12,
                    color=ft.colors.BLUE_GREY_700,
                ),
                ft.DataTable(
                    columns=[
                        ft.DataColumn(ft.Text("#")),
                        ft.DataColumn(ft.Text("Etape")),
                        ft.DataColumn(ft.Text("Debut")),
                        ft.DataColumn(ft.Text("Fin")),
                        ft.DataColumn(ft.Text("Duree")),
                    ],
                    rows=rows,
                ),
            ],
        ),
    )


def _feature_impact_row(item: dict) -> ft.Control:
    impact = float(item.get("impact_jours") or 0)
    color = ft.colors.RED_700 if impact > 0 else ft.colors.GREEN_700 if impact < 0 else ft.colors.BLUE_GREY_700
    bgcolor = ft.colors.RED_50 if impact > 0 else ft.colors.GREEN_50 if impact < 0 else ft.colors.BLUE_GREY_50
    return ft.Container(
        padding=8,
        border=ft.border.all(1, ft.colors.BLUE_GREY_100),
        border_radius=6,
        bgcolor=ft.colors.WHITE,
        content=ft.Row(
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            controls=[
                ft.Column(
                    spacing=2,
                    expand=True,
                    controls=[
                        ft.Text(str(item.get("feature")), weight=ft.FontWeight.BOLD),
                        ft.Text(
                            f"Valeur: {item.get('valeur')} | Reference: {item.get('reference')}",
                            size=12,
                            color=ft.colors.BLUE_GREY_700,
                        ),
                    ],
                ),
                _pill(f"{impact:+.2f} j", color, bgcolor),
            ],
        ),
    )


def _prediction_neighbors_panel(voisins: list[dict]) -> ft.Control:
    return ft.Container(
        padding=12,
        border=ft.border.all(1, ft.colors.BLUE_GREY_100),
        border_radius=6,
        bgcolor=ft.colors.WHITE,
        content=ft.Column(
            spacing=8,
            controls=[
                ft.Text("Projets historiques proches", size=15, weight=ft.FontWeight.BOLD),
                *[
                    ft.Text(
                        f"{voisin['reference']} {voisin['modele']} {voisin['silhouette']} | "
                        f"duree {voisin['duree_reelle']}j | distance {voisin['distance']}",
                        size=12,
                    )
                    for voisin in voisins
                ],
            ],
        ),
    )


def _status_badge(status: str) -> ft.Control:
    styles = {
        "PLANIFIEE": (ft.colors.BLUE_700, ft.colors.BLUE_50, "Planifiee"),
        "EN_ATTENTE": (ft.colors.BLUE_GREY_700, ft.colors.BLUE_GREY_50, "En attente"),
        "EN_COURS": (ft.colors.ORANGE_700, ft.colors.ORANGE_50, "En cours"),
        "TERMINEE": (ft.colors.GREEN_700, ft.colors.GREEN_50, "Terminee"),
        "A_FAIRE": (ft.colors.BLUE_GREY_700, ft.colors.BLUE_GREY_50, "A faire"),
        "A_VENIR": (ft.colors.BLUE_GREY_700, ft.colors.BLUE_GREY_50, "A venir"),
        "EN_RETARD": (ft.colors.RED_700, ft.colors.RED_50, "En retard"),
    }
    color, bgcolor, label = styles.get(
        status,
        (ft.colors.BLUE_GREY_700, ft.colors.BLUE_GREY_50, status),
    )
    return _pill(label, color, bgcolor)


def _deadline_badge(deadline: date | None) -> ft.Control:
    if deadline is None:
        return _pill("Deadline -", ft.colors.BLUE_GREY_700, ft.colors.BLUE_GREY_50)
    today = date.today()
    if deadline < today:
        return _pill(f"Retard {deadline}", ft.colors.RED_700, ft.colors.RED_50)
    if deadline <= today + timedelta(days=7):
        return _pill(f"Urgent {deadline}", ft.colors.ORANGE_700, ft.colors.ORANGE_50)
    return _pill(str(deadline), ft.colors.GREEN_700, ft.colors.GREEN_50)


def _priority_badge(score: float | None) -> ft.Control:
    value = round(score or 0, 2)
    if value >= 10_000:
        return _pill(f"Priorite {value}", ft.colors.RED_700, ft.colors.RED_50)
    if value >= 990:
        return _pill(f"Priorite {value}", ft.colors.ORANGE_700, ft.colors.ORANGE_50)
    if value > 0:
        return _pill(f"Priorite {value}", ft.colors.BLUE_700, ft.colors.BLUE_50)
    return _pill("Priorite -", ft.colors.BLUE_GREY_700, ft.colors.BLUE_GREY_50)


def _kanban_action_label(statut: StatutAvancement) -> str:
    labels = {
        StatutAvancement.PLANIFIEE: "Planifier",
        StatutAvancement.EN_COURS: "Demarrer",
        StatutAvancement.TERMINEE: "Terminer",
    }
    return labels[statut]


def _kanban_action_icon(statut: StatutAvancement) -> str:
    icons = {
        StatutAvancement.PLANIFIEE: ft.icons.EVENT_AVAILABLE,
        StatutAvancement.EN_COURS: ft.icons.PLAY_ARROW,
        StatutAvancement.TERMINEE: ft.icons.CHECK,
    }
    return icons[statut]


def _read_badge(is_read: bool) -> ft.Control:
    if is_read:
        return _pill("Lue", ft.colors.GREEN_700, ft.colors.GREEN_50)
    return _pill("Non lue", ft.colors.ORANGE_700, ft.colors.ORANGE_50)


def _pill(label: str, color: str, bgcolor: str) -> ft.Control:
    return ft.Container(
        padding=ft.padding.symmetric(horizontal=9, vertical=5),
        border_radius=6,
        bgcolor=bgcolor,
        border=ft.border.all(1, color),
        content=ft.Text(label, size=12, color=color, weight=ft.FontWeight.BOLD),
    )
