from __future__ import annotations

"""Tkinter UI for building Dota 2 Ability Draft console commands.

This module is responsible for all visible UI behavior:
- laying out the window;
- showing the offline hero icon grid;
- tracking the currently selected heroes;
- exposing timer controls;
- showing health/status checks for local hero data and cached icons;
- generating and copying the final console command.

All command-building and search ranking logic lives in ad_ui.logic.
All icon loading and image normalization lives in ad_ui.icons.
"""

import json
import os
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Dict, List

from .icons import IconManager
from .logic import (
    CLEAR_AD_COMMAND,
    DEFAULT_TIMERS,
    HERO_DATA,
    build_ad_command,
    get_site_slug,
    ranked_search_results,
)

# The AD roster uses 12 manual slots total: 5 Radiant, 5 Dire, then 2 Extra.
MAX_HEROES = 12

# Project-relative paths used by the UI.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
UPDATE_STATUS_PATH = PROJECT_ROOT / "cache" / "update_status.json"


class AbilityDraftApp:
    """Main Tkinter application object.

    The object owns all UI widgets and the mutable selection state.
    """

    def __init__(self, root: tk.Tk, version: str = ""):
        self.root = root
        self.version = version.strip()

        # Show the app name and, if available, the release version.
        title = "Dota 2 Ability Draft Command Builder"
        if self.version:
            title += f" v{self.version}"
        self.root.title(title)
        self.root.geometry("1260x860")
        self.root.minsize(1080, 740)

        # IconManager reads already-downloaded local files only.
        cache_dir = PROJECT_ROOT / "cache" / "icons"
        self.icon_manager = IconManager(cache_dir)

        # Ordered list of chosen heroes. Order matters because the first
        # 5 become Radiant and the next 5 become Dire.
        self.selected: List[Dict[str, object]] = []

        # Per-hero widget records used for re-filtering and restyling the grid.
        self.hero_buttons: List[dict[str, object]] = []

        # Search box content. Whenever it changes, the grid is re-ranked.
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search_change)

        # Timer input boxes. These defaults match the current requested values.
        self.pre_time_var = tk.StringVar(value=str(DEFAULT_TIMERS["pre_time"]))
        self.per_player_var = tk.StringVar(value=str(DEFAULT_TIMERS["per_player_time"]))
        self.pre_round_var = tk.StringVar(value=str(DEFAULT_TIMERS["pre_round_time"]))
        for var in (self.pre_time_var, self.per_player_var, self.pre_round_var):
            var.trace_add("write", self._on_timer_change)

        # status_var is the small informational line near the top.
        self.status_var = tk.StringVar(value=self._default_status())

        # command_var is kept for completeness, even though the visible command
        # area is the Text widget below.
        self.command_var = tk.StringVar(value=self._build_current_command())

        # Health-check text and color for hero/icon consistency.
        self.check_var = tk.StringVar()
        self.check_color = "#008800"

        # Build the full UI, then populate it with data.
        self._build_layout()
        self.refresh_selected_view()
        self.populate_hero_grid()
        self.apply_filter("")
        self.refresh_hero_button_states()
        self.refresh_updater_check()
        self.update_command_text()

    def _build_layout(self) -> None:
        """Create and place all widgets in the window.

        The left side is the searchable hero grid.
        The right side contains selection state, command output, and checks.
        """
        self.root.columnconfigure(0, weight=7)
        self.root.columnconfigure(1, weight=4)
        self.root.rowconfigure(1, weight=1)

        # -------------------- Top bar: search + timer controls --------------------
        top = ttk.Frame(self.root, padding=10)
        top.grid(row=0, column=0, columnspan=2, sticky="nsew")
        top.columnconfigure(1, weight=1)
        top.columnconfigure(3, weight=0)

        ttk.Label(top, text="Search hero:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        search_entry = ttk.Entry(top, textvariable=self.search_var)
        search_entry.grid(row=0, column=1, sticky="ew")
        ttk.Button(top, text="Clear search", command=lambda: self.search_var.set("")).grid(
            row=0, column=2, padx=(8, 12)
        )

        timer_frame = ttk.LabelFrame(top, text="Draft timers", padding=(10, 8))
        timer_frame.grid(row=0, column=3, rowspan=2, sticky="e")
        for col in range(3):
            timer_frame.columnconfigure(col, weight=1)

        ttk.Label(timer_frame, text="Pre time (s)").grid(row=0, column=0, padx=4, sticky="w")
        ttk.Label(timer_frame, text="Per player (s)").grid(row=0, column=1, padx=4, sticky="w")
        ttk.Label(timer_frame, text="Pre round (s)").grid(row=0, column=2, padx=4, sticky="w")

        ttk.Spinbox(timer_frame, from_=0, to=999, width=8, textvariable=self.pre_time_var).grid(
            row=1, column=0, padx=4, pady=(2, 0)
        )
        ttk.Spinbox(timer_frame, from_=0, to=999, width=8, textvariable=self.per_player_var).grid(
            row=1, column=1, padx=4, pady=(2, 0)
        )
        ttk.Spinbox(timer_frame, from_=0, to=999, width=8, textvariable=self.pre_round_var).grid(
            row=1, column=2, padx=4, pady=(2, 0)
        )

        ttk.Label(top, textvariable=self.status_var).grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(8, 0)
        )

        # -------------------- Left side: scrollable hero grid --------------------
        left = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        left.grid(row=1, column=0, sticky="nsew")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(left, highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(left, orient="vertical", command=self.canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        # The actual buttons live inside a frame embedded in the canvas.
        self.grid_frame = ttk.Frame(self.canvas)
        self.grid_window = self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")
        self.grid_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        # -------------------- Right side: selection + output --------------------
        right = ttk.Frame(self.root, padding=(0, 0, 10, 10))
        right.grid(row=1, column=1, sticky="nsew")
        right.rowconfigure(4, weight=1)
        right.columnconfigure(0, weight=1)

        selected_card = ttk.LabelFrame(right, text="Selected heroes", padding=8)
        selected_card.grid(row=0, column=0, sticky="ew")
        selected_card.columnconfigure(0, weight=1)

        self.selected_frame = ttk.Frame(selected_card)
        self.selected_frame.grid(row=0, column=0, sticky="ew")
        self.selected_frame.columnconfigure(0, weight=1)

        action_bar = ttk.Frame(right)
        action_bar.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        action_bar.columnconfigure((0, 1, 2), weight=1)
        ttk.Button(action_bar, text="Undo last", command=self.undo_last).grid(
            row=0, column=0, sticky="ew", padx=(0, 4)
        )
        ttk.Button(action_bar, text="Clear all", command=self.clear_all).grid(
            row=0, column=1, sticky="ew", padx=4
        )
        ttk.Button(action_bar, text="Copy command", command=self.copy_command).grid(
            row=0, column=2, sticky="ew", padx=(4, 0)
        )

        check_card = ttk.LabelFrame(right, text="Hero count check", padding=8)
        check_card.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        self.check_label = tk.Label(
            check_card,
            textvariable=self.check_var,
            justify="left",
            anchor="w",
            wraplength=360,
            fg=self.check_color,
        )
        self.check_label.grid(row=0, column=0, sticky="ew")

        ttk.Label(right, text="Console command").grid(row=3, column=0, sticky="w", pady=(12, 6))
        self.command_text = tk.Text(right, height=10, wrap="word")
        self.command_text.grid(row=4, column=0, sticky="nsew")

        command_footer = ttk.Frame(right)
        command_footer.grid(row=5, column=0, sticky="ew", pady=(6, 0))
        command_footer.columnconfigure(0, weight=1)
        ttk.Button(command_footer, text="Refresh command", command=self.update_command_text).grid(
            row=0, column=1, sticky="e"
        )

        ttk.Label(right, text="Clear AD setup command").grid(row=6, column=0, sticky="w", pady=(12, 6))
        clear_box = ttk.Frame(right)
        clear_box.grid(row=7, column=0, sticky="ew")
        clear_box.columnconfigure(0, weight=1)
        self.clear_command_entry = ttk.Entry(clear_box)
        self.clear_command_entry.grid(row=0, column=0, sticky="ew")
        self.clear_command_entry.insert(0, CLEAR_AD_COMMAND)
        # Read-only keeps the text copyable, but prevents accidental edits.
        self.clear_command_entry.state(["readonly"])

        clear_footer = ttk.Frame(right)
        clear_footer.grid(row=8, column=0, sticky="ew", pady=(6, 0))
        clear_footer.columnconfigure(0, weight=1)
        ttk.Button(clear_footer, text="Copy clear command", command=self.copy_clear_command).grid(
            row=0, column=1, sticky="e"
        )

    def _on_mousewheel(self, event: tk.Event) -> None:
        """Scroll the hero grid with the mouse wheel."""
        if self.canvas.winfo_exists():
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_frame_configure(self, _event: tk.Event) -> None:
        """Update the canvas scroll region when the hero grid changes size."""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: tk.Event) -> None:
        """Make the embedded hero grid frame track the visible canvas width."""
        self.canvas.itemconfigure(self.grid_window, width=event.width)

    def _on_search_change(self, *_args: object) -> None:
        """Re-filter the hero grid whenever the search box changes."""
        self.apply_filter(self.search_var.get())

    def _on_timer_change(self, *_args: object) -> None:
        """Rebuild the generated command whenever any timer box changes."""
        self.update_command_text()

    def _default_status(self) -> str:
        """Return the default hint text shown near the top of the window."""
        return (
            f"Choose up to {MAX_HEROES} heroes. First 5 go to Radiant, next 5 go to Dire, last 2 go to Extra. "
            "Click a selected hero again to remove it."
        )

    def _show_hover_hero(self, hero: Dict[str, object]) -> None:
        """Show the currently hovered hero and its internal command name.

        This is suppressed while a search is active so search feedback is not overwritten.
        """
        if self.search_var.get().strip():
            return
        self.status_var.set(f"{hero['display']} -> {hero['internal']}")

    def _clear_hover_hero(self) -> None:
        """Restore the default status text after hover ends."""
        if self.search_var.get().strip():
            return
        self.status_var.set(self._default_status())

    def _parse_timer_var(self, var: tk.StringVar, default: int) -> int:
        """Safely read a timer entry box as a non-negative integer."""
        text = var.get().strip()
        if not text:
            return default
        try:
            value = int(text)
        except ValueError:
            return default
        return max(0, value)

    def _current_timer_values(self) -> dict[str, int]:
        """Return the three timer values currently shown in the UI."""
        return {
            "pre_time": self._parse_timer_var(self.pre_time_var, DEFAULT_TIMERS["pre_time"]),
            "per_player_time": self._parse_timer_var(self.per_player_var, DEFAULT_TIMERS["per_player_time"]),
            "pre_round_time": self._parse_timer_var(self.pre_round_var, DEFAULT_TIMERS["pre_round_time"]),
        }

    def _build_current_command(self) -> str:
        """Build the current AD console command from selection + timers."""
        timers = self._current_timer_values()
        return build_ad_command(
            self.selected,
            pre_time=timers["pre_time"],
            per_player_time=timers["per_player_time"],
            pre_round_time=timers["pre_round_time"],
        )

    def populate_hero_grid(self) -> None:
        """Create one button per hero in the local hero dataset.

        The grid is built once. After that, searching only hides/reorders existing
        widgets instead of rebuilding everything from scratch.
        """
        columns = 6
        for col in range(columns):
            self.grid_frame.columnconfigure(col, weight=1)

        for hero in HERO_DATA:
            display = str(hero["display"])
            internal = str(hero["internal"])

            # Each hero button sits inside a frame so the frame can provide a
            # stronger selected outline without reusing search-highlight colors.
            frame = tk.Frame(
                self.grid_frame,
                bd=1,
                relief="flat",
                highlightthickness=0,
                padx=3,
                pady=3,
                bg=self.root.cget("background"),
            )

            # Prefer offline icons. If an icon is missing, fall back to a text button.
            image = self.icon_manager.get([get_site_slug(hero), internal])
            if image is not None:
                button = tk.Button(
                    frame,
                    image=image,
                    width=104,
                    height=62,
                    padx=2,
                    pady=2,
                    relief="raised",
                    bd=2,
                    command=lambda hero=hero: self.toggle_hero(hero),
                )
            else:
                button = tk.Button(
                    frame,
                    text=display,
                    width=14,
                    height=4,
                    wraplength=90,
                    justify="center",
                    relief="raised",
                    bd=2,
                    command=lambda hero=hero: self.toggle_hero(hero),
                )
            button.pack(fill="both", expand=True)
            button.bind("<Enter>", lambda _event, hero=hero: self._show_hover_hero(hero))
            button.bind("<Leave>", lambda _event: self._clear_hover_hero())

            self.hero_buttons.append(
                {
                    "frame": frame,
                    "hero": hero,
                    "button": button,
                    "columns": columns,
                    "default_bg": button.cget("background"),
                    "default_relief": button.cget("relief"),
                    "default_bd": int(button.cget("bd")),
                }
            )

    def apply_filter(self, text: str) -> None:
        """Apply ranked search to the hero grid.

        The search function in ad_ui.logic returns heroes in relevance order.
        This method then hides non-matching heroes, highlights strong prefix
        matches, and repositions the visible buttons in ranked order.
        """
        raw = text.strip()

        if not raw:
            ordered = [(record["hero"], 0, False) for record in self.hero_buttons]
            self.status_var.set(self._default_status())
        else:
            ordered = ranked_search_results(raw)
            if ordered:
                very = [hero for hero, _score, very_relevant in ordered if very_relevant]
                if very:
                    names = ", ".join(str(hero["display"]) for hero in very[:5])
                    self.status_var.set(f"Very relevant prefix matches highlighted: {names}")
                else:
                    names = ", ".join(str(hero["display"]) for hero, _score, _very in ordered[:5])
                    self.status_var.set(f"Matches: {names}")
            else:
                self.status_var.set(f"No matches found for: {raw}")

        # Build a lookup table so each existing button can decide whether it stays visible.
        lookup = {str(item[0]["internal"]): item for item in ordered}
        visible_records: List[dict[str, object]] = []

        for record in self.hero_buttons:
            hero = record["hero"]
            info = lookup.get(str(hero["internal"]))
            if info is None:
                record["frame"].grid_remove()
                self._style_button(record, highlighted=False)
                continue
            visible_records.append(record)
            self._style_button(record, highlighted=bool(info[2]))

        # Keep visible heroes in score order while searching, otherwise by name.
        visible_records.sort(
            key=lambda rec: -lookup[str(rec["hero"]["internal"])][1]
            if raw
            else str(rec["hero"]["display"]).lower()
        )

        columns = 6
        for index, record in enumerate(visible_records):
            row = index // columns
            col = index % columns
            record["frame"].grid(row=row, column=col, sticky="nsew")

        self.refresh_hero_button_states()

    def _style_button(self, record: dict[str, object], *, highlighted: bool) -> None:
        """Apply search highlighting without interfering with selected-state styling."""
        button: tk.Button = record["button"]  # type: ignore[assignment]
        default_bg = record["default_bg"]
        if highlighted:
            button.configure(background="#fff0a6", activebackground="#ffe680")
        else:
            button.configure(background=default_bg, activebackground=default_bg)

    def _selected_internals(self) -> set[str]:
        """Return the set of currently selected hero internal names."""
        return {str(hero["internal"]) for hero in self.selected}

    def refresh_hero_button_states(self) -> None:
        """Update each hero button to reflect selected/disabled state.

        Selected heroes use a stronger sunken + outlined visual style.
        Once 12 heroes are selected, all remaining heroes are disabled.
        """
        selected = self._selected_internals()
        limit_reached = len(self.selected) >= MAX_HEROES

        for record in self.hero_buttons:
            hero = record["hero"]
            button: tk.Button = record["button"]  # type: ignore[assignment]
            frame: tk.Frame = record["frame"]  # type: ignore[assignment]
            internal = str(hero["internal"])
            if internal in selected:
                button.configure(state="normal", relief="sunken", bd=4)
                frame.configure(relief="ridge", bd=3, highlightthickness=2, highlightbackground="#4c4c4c")
            elif limit_reached:
                button.configure(state="disabled", relief=record["default_relief"], bd=record["default_bd"])
                frame.configure(relief="flat", bd=1, highlightthickness=0)
            else:
                button.configure(state="normal", relief=record["default_relief"], bd=record["default_bd"])
                frame.configure(relief="flat", bd=1, highlightthickness=0)

    def toggle_hero(self, hero: Dict[str, object]) -> None:
        """Toggle a hero on/off when its button is clicked."""
        internal = str(hero["internal"])
        for index, existing in enumerate(self.selected):
            if str(existing["internal"]) == internal:
                self.remove_hero(index)
                return

        if len(self.selected) >= MAX_HEROES:
            messagebox.showinfo("Limit reached", f"You can choose at most {MAX_HEROES} heroes.")
            return

        self.selected.append(hero)
        self.refresh_selected_view()
        self.refresh_hero_button_states()
        self.update_command_text()

    def remove_hero(self, index: int) -> None:
        """Remove one hero from the ordered selection by index."""
        if 0 <= index < len(self.selected):
            self.selected.pop(index)
            self.refresh_selected_view()
            self.refresh_hero_button_states()
            self.update_command_text()

    def undo_last(self) -> None:
        """Remove the most recently selected hero."""
        if self.selected:
            self.selected.pop()
            self.refresh_selected_view()
            self.refresh_hero_button_states()
            self.update_command_text()

    def clear_all(self) -> None:
        """Clear the entire 0-12 hero selection."""
        self.selected.clear()
        self.refresh_selected_view()
        self.refresh_hero_button_states()
        self.update_command_text()

    def refresh_selected_view(self) -> None:
        """Rebuild the selected-heroes panel on the right side."""
        for child in self.selected_frame.winfo_children():
            child.destroy()

        if not self.selected:
            ttk.Label(self.selected_frame, text="No heroes selected yet.").grid(row=0, column=0, sticky="w")
            return

        for i, hero in enumerate(self.selected):
            if i < 5:
                side = "Radiant"
            elif i < 10:
                side = "Dire"
            else:
                side = "Extra"
            label = f"{i + 1}. {hero['display']} ({side})"
            row = ttk.Frame(self.selected_frame)
            row.grid(row=i, column=0, sticky="ew", pady=2)
            row.columnconfigure(0, weight=1)
            ttk.Label(row, text=label).grid(row=0, column=0, sticky="w")
            ttk.Button(row, text="Remove", command=lambda idx=i: self.remove_hero(idx)).grid(
                row=0, column=1, padx=(8, 0)
            )

    def update_command_text(self) -> None:
        """Refresh the generated console command text area."""
        command = self._build_current_command()
        self.command_var.set(command)
        self.command_text.delete("1.0", "end")
        self.command_text.insert("1.0", command)

    def copy_command(self) -> None:
        """Copy the main generated command to the system clipboard."""
        command = self.command_text.get("1.0", "end-1c")
        self.root.clipboard_clear()
        self.root.clipboard_append(command)
        self.status_var.set("Command copied to clipboard.")

    def copy_clear_command(self) -> None:
        """Copy the standalone AD-clear command to the clipboard."""
        command = self.clear_command_entry.get()
        self.root.clipboard_clear()
        self.root.clipboard_append(command)
        self.status_var.set("Clear command copied to clipboard.")

    def refresh_updater_check(self) -> None:
        """Show hero/icon consistency checks in the health panel.

        Hero count mismatch is treated as a red error because heroes may be missing
        from the app entirely. Icon-only mismatch is orange because the app still
        functions, but some buttons may fall back to text.
        """
        hero_suggestion = (
            "Some heroes are missing, please run update_assets.py with admin permission to fix this."
        )
        icon_suggestion = (
            "Some icons are missing. To fix this, consider running update_assets.py with admin permission."
        )

        # Count actual PNG files currently stored on disk.
        live_icon_count = sum(1 for path in (PROJECT_ROOT / "cache" / "icons").glob("*.png") if path.is_file())
        expected_icon_count = len(HERO_DATA)
        icon_count_passed = live_icon_count == expected_icon_count

        official_count = None
        local_count = len(HERO_DATA)
        status_note = ""

        # Read updater-produced metadata if available.
        if UPDATE_STATUS_PATH.exists():
            try:
                data = json.loads(UPDATE_STATUS_PATH.read_text(encoding="utf-8"))
                official_count = data.get("official_count")
                local_count = data.get("local_count", local_count)
                status_note = str(data.get("message", "")).strip()
            except (OSError, json.JSONDecodeError):
                status_note = "Could not read updater status."
        else:
            status_note = "No updater status found."

        hero_count_passed = True
        if official_count is not None and local_count is not None:
            hero_count_passed = official_count == local_count

        lines: list[str] = []
        if official_count is not None and local_count is not None:
            lines.append(
                f"Hero count check {'passed' if hero_count_passed else 'failed'}: local {local_count}, official {official_count}."
            )
        elif status_note:
            lines.append(status_note)

        lines.append(
            f"Icon count check {'passed' if icon_count_passed else 'failed'}: stored {live_icon_count}, expected {expected_icon_count}."
        )

        lower_note = status_note.lower()
        if hero_count_passed and icon_count_passed:
            color = "#008800"
        elif not hero_count_passed:
            color = "#bb0000"
            lines.append(hero_suggestion)
        else:
            color = "#cc7a00"
            lines.append(icon_suggestion)

        # Preserve useful updater notes, but avoid duplicating the same information.
        if status_note and status_note not in lines and (
            (not hero_count_passed and "hero count check" not in lower_note)
            or (
                hero_count_passed
                and not icon_count_passed
                and "icon count check" not in lower_note
                and status_note != "No updater status found."
            )
        ):
            lines.insert(0, status_note)

        self.check_label.configure(fg=color)
        self.check_var.set("\n".join(lines))


# Setting an explicit Windows AppUserModelID helps the custom icon stick more
# reliably in the title bar / Alt-Tab view when the app is launched via pythonw.
APP_USER_MODEL_ID = "OpenAI.DotaAbilityDraft.CommandBuilder"


def _set_windows_app_id() -> None:
    """Apply a Windows AppUserModelID when running on Windows.

    This is ignored on other platforms.
    """
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        # Failure here is non-fatal; the app can still run without it.
        pass


def _set_app_icon(root: tk.Tk) -> None:
    """Load the app icon files from assets/ and apply them to the Tk window."""
    assets_dir = PROJECT_ROOT / "assets"
    png_path = assets_dir / "app_icon.png"
    ico_path = assets_dir / "app_icon.ico"

    # On Windows, ICO tends to work best for native window/task switching.
    if os.name == "nt":
        try:
            if ico_path.exists():
                root.iconbitmap(default=str(ico_path))
        except tk.TclError:
            pass

    # PNG iconphoto is useful across Tk platforms.
    try:
        if png_path.exists():
            icon_image = tk.PhotoImage(file=str(png_path))
            # Keep a Python reference so Tk does not garbage-collect the image.
            root._ad_app_icon = icon_image
            root.iconphoto(True, icon_image)
    except tk.TclError:
        pass


def main(version: str = "") -> None:
    """Create and run the Tk application."""
    _set_windows_app_id()
    root = tk.Tk()
    _set_app_icon(root)
    try:
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except tk.TclError:
        # Theme selection is cosmetic, so ignore failures.
        pass
    AbilityDraftApp(root, version=version)
    root.mainloop()
