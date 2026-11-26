"""Abas Macro e Perfis no estilo do driver original (XMLs em res/)."""
from __future__ import annotations

import base64
import json
import time
from pathlib import Path

import gi
gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from .config import (Button, Buttons, Lighting, MacroEvent, Macros, Profiles,
                     _HID_KEYS, _HID_KEYS_INV)
from .defaults import DEFAULT_BUTTONS
from .runtime import data_home

DELAY_MS = 10  # unidade exibida na GUI (o firmware usa 8 ms por unidade bruta)
MOUSE_NAMES = {0xF0: "L_Button", 0xF1: "R_Button", 0xF2: "M_Button",
               0xF3: "Backward", 0xF4: "Forward"}
MOUSE_NAMES_INV = {v: k for k, v in MOUSE_NAMES.items()}
KEY_ALIASES = {"Control_L": "ctrl", "Control_R": "ctrl", "Shift_L": "shift",
               "Shift_R": "shift", "Alt_L": "alt", "Alt_R": "alt",
               "Super_L": "win", "Super_R": "win", "Escape": "esc",
               "space": "space", "Return": "enter", "BackSpace": "backspace"}
_EXTRA_HID = {
    **{f"F{i}": 0x39 + i for i in range(1, 13)},
    "Home": 0x47, "Page_Up": 0x4B, "End": 0x4D, "Page_Down": 0x4E,
    "Left": 0x50, "Up": 0x51, "Right": 0x4F, "Down": 0x52,
    "Insert": 0x49, "Delete": 0x4C, "Caps_Lock": 0x39, "Tab": 0x2B,
}
_KEY_NAMES = {**_HID_KEYS_INV, **{v: k for k, v in _EXTRA_HID.items()}}


def _parse_hex(value: str) -> tuple[int, int, int]:
    value = value.strip().lstrip("#")
    if len(value) != 6:
        raise ValueError("cor deve ser RRGGBB")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


class MacroProfileUI:
    """Mixin com as abas Macro e Perfis. Requer App.notebook, App.mouse etc."""

    # ------------------------------ nomes ----------------------------------
    def _names_path(self) -> Path:
        path = data_home() / "macros" / "names.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _macro_names(self) -> list[str]:
        path = self._names_path()
        if path.exists():
            try:
                data = json.loads(path.read_text())
                return [str(data.get(str(i), f"Macro {i}")) for i in range(1, 10)]
            except (ValueError, OSError):
                pass
        return [f"Macro {i}" for i in range(1, 10)]

    def _save_macro_names(self) -> None:
        data = {str(i + 1): name for i, name in enumerate(self.macro_names)}
        self._names_path().write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")

    # ------------------------------- macro ---------------------------------
    def _build_macros_ui(self) -> None:
        page = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, border_width=12)
        self.notebook.append_page(page, Gtk.Label(label="Macro"))
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        left.set_size_request(330, -1)
        page.pack_start(left, True, True, 0)

        name_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        name_box.pack_start(Gtk.Label(label="Macro Name", xalign=0), False, True, 0)
        self.macro_combo = Gtk.ComboBoxText()
        self._macro_loading = True
        self._refresh_macro_combo()
        self.macro_combo.connect("changed", self._macro_combo_changed)
        name_box.pack_start(self.macro_combo, True, True, 0)
        left.pack_start(self._section("Macro Name", name_box), False, True, 0)

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for label, handler in (("Add", self._add_macro), ("Delete", self._delete_macro),
                               ("Menu", self._macro_menu)):
            btn = Gtk.Button(label=label)
            btn.connect("clicked", handler)
            bar.pack_start(btn, False, True, 0)
        left.pack_start(bar, False, True, 0)

        self.macro_rename = Gtk.Entry(placeholder_text="Rename Macro Name")
        self.macro_rename.connect("activate", self._rename_macro)
        left.pack_start(self.macro_rename, False, True, 0)

        self.macro_list = Gtk.ListStore(str)
        view = Gtk.TreeView(model=self.macro_list)
        view.append_column(Gtk.TreeViewColumn("Macro", Gtk.CellRendererText(), text=0))
        view.get_selection().connect("changed", self._macro_list_selected)
        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(110)
        scroll.add(view)
        left.pack_start(scroll, False, True, 0)

        delay = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.delay_min = Gtk.RadioButton(label="Min Delay(10MS)")
        self.delay_default = Gtk.RadioButton.new_from_widget(self.delay_min)
        self.delay_default.set_label("MS Default Delay")
        self.delay_record = Gtk.RadioButton.new_from_widget(self.delay_min)
        self.delay_record.set_label("Record Delay")
        self.delay_min.set_active(True)
        self.delay_entry = Gtk.Entry(text="10", width_chars=6)
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        row.pack_start(self.delay_default, False, True, 0)
        row.pack_start(self.delay_entry, False, True, 0)
        for w in (self.delay_min, row, self.delay_record):
            delay.pack_start(w, False, True, 0)
        self.record_btn = Gtk.CheckButton(label="Recording")
        self.record_btn.connect("toggled", self._toggle_record)
        delay.pack_start(self.record_btn, False, True, 0)
        left.pack_start(self._section("Delay", delay), False, True, 0)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        page.pack_start(right, True, True, 0)
        self.event_store = Gtk.ListStore(str, str, str)
        self.event_view = Gtk.TreeView(model=self.event_store)
        event_view = self.event_view
        for title in ("Key", "Action", "Delay(MS)"):
            event_view.append_column(Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=("Key", "Action", "Delay(MS)").index(title)))
        event_view.get_selection().connect("changed", self._event_selected)
        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(280)
        scroll.add(event_view)
        right.pack_start(scroll, True, True, 0)

        tools = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        tools.pack_start(Gtk.Label(label="Loop Times(1~255)"), False, True, 0)
        self.loop_entry = Gtk.Entry(text="1", width_chars=5)
        tools.pack_start(self.loop_entry, False, True, 0)
        for label, handler in (("Up", self._event_up), ("Down", self._event_down),
                               ("Delete", self._event_delete), ("Clear All", self._event_clear),
                               ("Move", self._event_move)):
            btn = Gtk.Button(label=label)
            btn.connect("clicked", handler)
            tools.pack_start(btn, False, True, 0)
        tools.pack_start(Gtk.Label(label="X"), False, True, 0)
        self.move_x = Gtk.Entry(text="0", width_chars=4)
        self.move_y = Gtk.Entry(text="0", width_chars=4)
        tools.pack_start(self.move_x, False, True, 0)
        tools.pack_start(Gtk.Label(label="Y"), False, True, 0)
        tools.pack_start(self.move_y, False, True, 0)
        right.pack_start(tools, False, True, 0)

        edit = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.edit_key = Gtk.Entry(editable=False, width_chars=12, placeholder_text="Key")
        self.edit_action = Gtk.ComboBoxText()
        for item in ("Pushed", "Release", "Delay(MS)", "Mouse Move"):
            self.edit_action.append_text(item)
        self.edit_action.set_active(0)
        self.edit_action.connect("changed", self._edit_action_changed)
        self.edit_value = Gtk.Entry(width_chars=8, placeholder_text="Delay")
        self.edit_action_combo = Gtk.ComboBoxText()
        for item in ("L_Button", "R_Button", "M_Button", "Backward", "Forward"):
            self.edit_action_combo.append_text(item)
        self.edit_action_combo.set_active(0)
        for w in (self.edit_key, self.edit_action, self.edit_value, self.edit_action_combo):
            edit.pack_start(w, False, True, 0)
        self.edit_apply = Gtk.Button(label="Apply Row")
        self.edit_apply.connect("clicked", self._event_apply)
        edit.pack_start(self.edit_apply, False, True, 0)
        right.pack_start(self._section("Edit", edit), False, True, 0)

        write = Gtk.Button(label="Gravar Macro")
        write.connect("clicked", self._write_macro_ui)
        right.pack_start(write, False, True, 0)
        self.macro_events = []
        self._macro_loading = False
        self._read_macro_ui()

    def _refresh_macro_combo(self) -> None:
        active = self.macro_combo.get_active() if hasattr(self, "macro_combo") else 0
        self.macro_combo.remove_all()
        for name in self._macro_names():
            self.macro_combo.append_text(name)
        self.macro_combo.set_active(max(0, min(active, 8)))
        if hasattr(self, "macro_list"):
            self.macro_list.clear()
            for name in self._macro_names():
                self.macro_list.append([name])

    def _selected_macro_page(self) -> int:
        return max(1, min(9, self.macro_combo.get_active() + 1))

    def _macro_combo_changed(self, _combo=None) -> None:
        if getattr(self, "_macro_loading", False):
            return
        self._read_macro_ui()

    def _macro_list_selected(self, selection) -> None:
        model, treeiter = selection.get_selected()
        if treeiter:
            self.macro_combo.set_active(self._macro_names().index(model[treeiter][0]))

    def _read_macro_ui(self) -> None:
        page = self._selected_macro_page()

        def work():
            with self.mouse() as m:
                events = Macros(m).read(page)
            cache = data_home() / "macros" / f"page-{page}.json"
            try:
                repeat = json.loads(cache.read_text()).get("repeat", 1) if cache.exists() else 1
            except (ValueError, OSError):
                repeat = 1
            self.macro_events = list(events)
            GLib.idle_add(self._render_macro)
            GLib.idle_add(self.loop_entry.set_text, str(repeat))
            GLib.idle_add(self.message, f"{len(events)} evento(s) - {self._macro_names()[page - 1]}")
        self.safe(work)

    def _render_macro(self) -> None:
        self.event_store.clear()
        for event in self.macro_events:
            if event.command == 0x01:
                key, action, delay = "WAIT", "Delay", str(event.wait * 2)
            elif event.command in (0xFA, 0xFE):
                key, action, delay = "Mouse", "Move", str(event.argument)
            else:
                key = MOUSE_NAMES.get(event.key) or _KEY_NAMES.get(event.key, f"{event.key:02X}")
                action = "Pushed" if event.press else "Release"
                delay = str(event.delay * DELAY_MS)
            self.event_store.append([key, action, delay])

    def _write_macro_ui(self, *_args) -> None:
        page = self._selected_macro_page()

        def work():
            repeat = max(1, min(255, int(self.loop_entry.get_text() or 1)))
            with self.mouse() as m:
                Macros(m).write(page, self.macro_events, repeat)
            self.message(f"{len(self.macro_events)} evento(s) gravados na página {page}")
        self.safe(work)

    def _add_macro(self, *_args) -> None:
        self.macro_names = self._macro_names()
        self.macro_names[self._selected_macro_page() - 1] = f"Macro {self._selected_macro_page()}"
        self._save_macro_names()
        self.macro_events = []
        self._render_macro()
        self._macro_loading = True
        self._refresh_macro_combo()
        self._macro_loading = False
        self.message("Macro adicionada")

    def _delete_macro(self, *_args) -> None:
        page = self._selected_macro_page()
        self.macro_events = []
        self._render_macro()
        cache = data_home() / "macros" / f"page-{page}.json"
        if cache.exists():
            cache.unlink()
        def work():
            with self.mouse() as m:
                Macros(m).write(page, [])
            self.message(f"Macro {page} apagada")
        self.safe(work)

    def _rename_macro(self, *_args) -> None:
        name = self.macro_rename.get_text().strip()
        if not name:
            return
        self.macro_names = self._macro_names()
        self.macro_names[self._selected_macro_page() - 1] = name
        self._save_macro_names()
        self._macro_loading = True
        self._refresh_macro_combo()
        self._macro_loading = False
        self.macro_rename.set_text("")
        self.message(f"Renomeado para {name}")

    def _macro_menu(self, button) -> None:
        menu = Gtk.Menu()
        for label, handler in (("Rename", lambda _w: self.macro_rename.grab_focus()),
                               ("Import", lambda _w: self._macro_import(False)),
                               ("Encrypted Import", lambda _w: self._macro_import(True)),
                               ("Export", lambda _w: self._macro_export(False)),
                               ("Encrypted Export", lambda _w: self._macro_export(True))):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", handler)
            menu.append(item)
        menu.attach_to_widget(button)
        menu.show_all()
        menu.popup_at_widget(button, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)

    def _macro_file(self, title: str, save: bool) -> Path | None:
        action = Gtk.FileChooserAction.SAVE if save else Gtk.FileChooserAction.OPEN
        dialog = Gtk.FileChooserDialog(title=title, parent=self, action=action)
        dialog.add_button("_Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("_Save" if save else "_Open", Gtk.ResponseType.ACCEPT)
        result = dialog.run()
        name = dialog.get_filename()
        dialog.destroy()
        return Path(name) if result == Gtk.ResponseType.ACCEPT and name else None

    def _macro_export(self, encrypted: bool) -> None:
        path = self._macro_file("Exportar macro", True)
        if not path:
            return
        payload = {"page": self._selected_macro_page(),
                   "repeat": int(self.loop_entry.get_text() or 1),
                   "events": [event.__dict__ for event in self.macro_events]}
        text = json.dumps(payload, indent=2, ensure_ascii=False)
        if encrypted:
            text = "SM809ENC1:" + base64.b64encode(text.encode()).decode()
        path.write_text(text + "\n")
        self.message(f"Macro exportada: {path}")

    def _macro_import(self, encrypted: bool) -> None:
        path = self._macro_file("Importar macro", False)
        if not path:
            return
        try:
            text = path.read_text().strip()
            if encrypted or text.startswith("SM809ENC1:"):
                text = base64.b64decode(text.split(":", 1)[1]).decode()
            data = json.loads(text)
            self.macro_events = [MacroEvent(**e) for e in data["events"]]
            self.loop_entry.set_text(str(data.get("repeat", 1)))
            self._render_macro()
            self.message(f"Macro importada: {path}")
        except Exception as exc:  # noqa: BLE001
            self.message(f"Falha ao importar: {exc}")

    def _delay_units(self) -> int:
        if self.delay_record.get_active():
            return 1
        if self.delay_default.get_active():
            raw = int(self.delay_entry.get_text() or 10)
            return max(1, min(127, raw // DELAY_MS))
        return 1

    def _toggle_record(self, button) -> None:
        if button.get_active():
            if not getattr(self, "_record_connected", False):
                self.connect("key-press-event", self._on_record_key)
                self.connect("key-release-event", self._on_record_key_release)
                self._record_connected = True
            self._last_record = time.monotonic()
            button.set_label("Recording... press Esc to stop")
            self.message("Gravando teclas...")
        else:
            button.set_label("Recording")
            self.message("Gravação encerrada")

    def _hid_for_key(self, event) -> int | None:
        name = Gdk.keyval_name(event.keyval) or ""
        name = KEY_ALIASES.get(name, name)
        key = _HID_KEYS.get(name.lower()) or _EXTRA_HID.get(name)
        return key

    def _on_record_key(self, _widget, event) -> None:
        if not self.record_btn.get_active():
            return
        name = Gdk.keyval_name(event.keyval) or ""
        if name == "Escape":
            self.record_btn.set_active(False)
            return True
        key = self._hid_for_key(event)
        if key is None:
            return False
        if self.delay_record.get_active():
            wait = max(1, int((time.monotonic() - self._last_record) * 500))
            self.macro_events.append(MacroEvent(0, command=0x01, wait=wait))
        self.macro_events.append(MacroEvent(key, press=True, delay=self._delay_units()))
        self._last_record = time.monotonic()
        self._render_macro()
        return True

    def _on_record_key_release(self, _widget, event) -> None:
        if not self.record_btn.get_active():
            return False
        key = self._hid_for_key(event)
        if key is None:
            return False
        self.macro_events.append(MacroEvent(key, press=False, delay=self._delay_units()))
        self._last_record = time.monotonic()
        self._render_macro()
        return True

    def _event_row(self):
        model, treeiter = self.event_view.get_selection().get_selected()
        return model, treeiter

    def _event_selected(self, selection) -> None:
        model, treeiter = selection.get_selected()
        if not treeiter:
            return
        index = model.get_path(treeiter).get_indices()[0]
        event = self.macro_events[index]
        self.edit_key.set_text(_KEY_NAMES.get(event.key, f"WAIT" if event.command else "Mouse"))
        if event.command == 0x01:
            self.edit_action.set_active(2)
            self.edit_value.set_text(str(event.wait * 2))
        elif event.command is not None:
            self.edit_action.set_active(3)
            self.edit_value.set_text(str(event.argument))
        else:
            self.edit_action.set_active(0 if event.press else 1)
            self.edit_value.set_text(str(event.delay * DELAY_MS))

    def _edit_action_changed(self, *_args) -> None:
        index = self.edit_action.get_active()
        self.edit_value.set_placeholder_text("Delay" if index < 3 else "Delta")
        self.edit_action_combo.set_sensitive(index in (0, 1))

    def _event_up(self, *_args) -> None:
        model, treeiter = self._event_row()
        if not treeiter:
            return
        index = model.get_path(treeiter).get_indices()[0]
        if index == 0:
            return
        self.macro_events[index - 1], self.macro_events[index] = (
            self.macro_events[index], self.macro_events[index - 1])
        self._render_macro()
        self.event_view.get_selection().select_path(Gtk.TreePath.new_from_indices([index - 1]))

    def _event_down(self, *_args) -> None:
        model, treeiter = self._event_row()
        if not treeiter:
            return
        index = model.get_path(treeiter).get_indices()[0]
        if index >= len(self.macro_events) - 1:
            return
        self.macro_events[index + 1], self.macro_events[index] = (
            self.macro_events[index], self.macro_events[index + 1])
        self._render_macro()
        self.event_view.get_selection().select_path(Gtk.TreePath.new_from_indices([index + 1]))

    def _event_delete(self, *_args) -> None:
        model, treeiter = self._event_row()
        if not treeiter:
            return
        index = model.get_path(treeiter).get_indices()[0]
        del self.macro_events[index]
        self._render_macro()

    def _event_clear(self, *_args) -> None:
        self.macro_events = []
        self._render_macro()
        self.message("Eventos limpos")

    def _event_move(self, *_args) -> None:
        model, treeiter = self._event_row()
        if not treeiter:
            return
        index = model.get_path(treeiter).get_indices()[0]
        try:
            delta = max(-127, min(127, int(self.move_x.get_text() or 0)))
        except ValueError:
            delta = 0
        self.macro_events[index] = MacroEvent(0, command=0xFA, argument=delta & 0xFF)
        self._render_macro()

    def _event_apply(self, *_args) -> None:
        model, treeiter = self._event_row()
        if not treeiter:
            return
        index = model.get_path(treeiter).get_indices()[0]
        action = self.edit_action.get_active()
        try:
            value = int(self.edit_value.get_text() or 0)
        except ValueError:
            value = 0
        if action in (0, 1):
            name = self.edit_action_combo.get_active_text() or "L_Button"
            key = MOUSE_NAMES_INV.get(name, _HID_KEYS.get(name.lower(), 0xF0))
            self.macro_events[index] = MacroEvent(
                key, press=(action == 0), delay=max(1, min(127, value or self._delay_units())))
        elif action == 2:
            self.macro_events[index] = MacroEvent(
                0, command=0x01, wait=max(1, min(65535, value // 2)))
        else:
            self.macro_events[index] = MacroEvent(
                0, command=0xFA, argument=max(-127, min(127, value)) & 0xFF)
        self._render_macro()

    # ------------------------------- perfis --------------------------------
    def _build_profiles_ui(self) -> None:
        page = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, border_width=12)
        self.notebook.append_page(page, Gtk.Label(label="Perfis"))
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        left.set_size_request(330, -1)
        page.pack_start(left, True, True, 0)

        name_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        name_box.pack_start(Gtk.Label(label="Profile Name", xalign=0), False, True, 0)
        self.profile_combo = Gtk.ComboBoxText()
        name_box.pack_start(self.profile_combo, True, True, 0)
        left.pack_start(self._section("Profile Name", name_box), False, True, 0)

        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for label, handler in (("Add", self._add_profile), ("Delete", self._delete_profile),
                               ("Menu", self._profile_menu)):
            btn = Gtk.Button(label=label)
            btn.connect("clicked", handler)
            bar.pack_start(btn, False, True, 0)
        left.pack_start(bar, False, True, 0)
        self.profile_rename = Gtk.Entry(placeholder_text="Rename Profile")
        self.profile_rename.connect("activate", self._rename_profile)
        left.pack_start(self.profile_rename, False, True, 0)

        flags = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        for label in ("Select", "Save LED", "Save Button", "Save Macro"):
            check = Gtk.CheckButton(label=label, active=True)
            setattr(self, "profile_" + label.lower().replace(" ", "_"), check)
            flags.pack_start(check, False, True, 0)
        left.pack_start(self._section("Options", flags), False, True, 0)

        self.profile_store = Gtk.ListStore(str)
        view = Gtk.TreeView(model=self.profile_store)
        view.append_column(Gtk.TreeViewColumn("Profile", Gtk.CellRendererText(), text=0))
        view.get_selection().connect("changed", self._profile_selected)
        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(200)
        scroll.add(view)
        left.pack_start(scroll, False, True, 0)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        page.pack_start(right, True, True, 0)
        right.pack_start(Gtk.Label(label="Perfis salvos em ~/.local/share/sm809/profiles",
                                   xalign=0), False, True, 0)
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, handler in (("Apply", self._apply_profile_ui), ("Save", self._save_profile_ui),
                               ("Reset", self._reset_profile), ("Refresh", self._reload_profiles_ui)):
            btn = Gtk.Button(label=label)
            btn.connect("clicked", handler)
            buttons.pack_start(btn, False, True, 0)
        right.pack_start(buttons, False, True, 0)
        self.profile_info = Gtk.Label(label="", xalign=0, selectable=True)
        right.pack_start(self.profile_info, True, True, 0)
        self._reload_profiles_ui()

    def _profiles(self, mouse) -> Profiles:
        return Profiles(mouse, data_home() / "profiles")

    def _profile_names(self) -> list[str]:
        return sorted(p.stem for p in (data_home() / "profiles").glob("*.json"))

    def _reload_profiles_ui(self, *_args) -> None:
        names = self._profile_names()
        active = self.profile_combo.get_active_text()
        self.profile_combo.remove_all()
        for name in names:
            self.profile_combo.append_text(name)
        if not names:
            self.profile_combo.append_text("Profile 1")
        if active in names:
            self.profile_combo.set_active(names.index(active))
        else:
            self.profile_combo.set_active(0)
        self.profile_store.clear()
        for name in names:
            self.profile_store.append([name])

    def _profile_selected(self, selection) -> None:
        model, treeiter = selection.get_selected()
        if treeiter:
            names = self._profile_names()
            if model[treeiter][0] in names:
                self.profile_combo.set_active(names.index(model[treeiter][0]))

    def _current_profile(self) -> str:
        return self.profile_combo.get_active_text() or self.profile_rename.get_text().strip() or "Profile 1"

    def _add_profile(self, *_args) -> None:
        used = self._profile_names()
        index = 1
        while f"Profile {index}" in used:
            index += 1
        name = f"Profile {index}"
        self.profile_rename.set_text(name)
        self._save_profile_ui()
        self._reload_profiles_ui()

    def _profile_path(self, name: str) -> Path:
        safe = "".join(c for c in name if c.isalnum() or c in "-_") or "profile"
        return data_home() / "profiles" / f"{safe}.json"

    def _delete_profile(self, *_args) -> None:
        name = self._current_profile()
        path = self._profile_path(name)
        if path.exists():
            path.unlink()
        self._reload_profiles_ui()
        self.message(f"Perfil removido: {name}")

    def _rename_profile(self, *_args) -> None:
        name = self.profile_rename.get_text().strip()
        old = self._current_profile()
        if not name or name == old:
            return
        source = self._profile_path(old)
        if source.exists():
            source.replace(self._profile_path(name))
        self.profile_rename.set_text("")
        self._reload_profiles_ui()
        self.message(f"Renomeado para {name}")

    def _profile_menu(self, button) -> None:
        menu = Gtk.Menu()
        for label, handler in (("Rename", lambda _w: self.profile_rename.grab_focus()),
                               ("Import", lambda _w: self._profile_import(False)),
                               ("Encrypted Import", lambda _w: self._profile_import(True)),
                               ("Export", lambda _w: self._profile_export(False)),
                               ("Encrypted Export", lambda _w: self._profile_export(True))):
            item = Gtk.MenuItem(label=label)
            item.connect("activate", handler)
            menu.append(item)
        menu.attach_to_widget(button)
        menu.show_all()
        menu.popup_at_widget(button, Gdk.Gravity.SOUTH_WEST, Gdk.Gravity.NORTH_WEST, None)

    def _profile_export(self, encrypted: bool) -> None:
        path = self._macro_file("Exportar perfil", True)
        source = self._profile_path(self._current_profile())
        if not path or not source.exists():
            self.message("Perfil não encontrado para exportar")
            return
        text = source.read_text().strip()
        if encrypted:
            text = "SM809ENC1:" + base64.b64encode(text.encode()).decode()
        path.write_text(text + "\n")
        self.message(f"Perfil exportado: {path}")

    def _profile_import(self, encrypted: bool) -> None:
        path = self._macro_file("Importar perfil", False)
        if not path:
            return
        try:
            text = path.read_text().strip()
            if encrypted or text.startswith("SM809ENC1:"):
                text = base64.b64decode(text.split(":", 1)[1]).decode()
            data = json.loads(text)
            name = data.get("name") or path.stem
            target = self._profile_path(name)
            target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
            self._reload_profiles_ui()
            self.message(f"Perfil importado: {target}")
        except Exception as exc:  # noqa: BLE001
            self.message(f"Falha ao importar: {exc}")

    def _apply_profile_ui(self, *_args) -> None:
        name = self._current_profile()
        def work():
            with self.mouse() as m:
                self._profiles(m).apply(name)
            GLib.idle_add(self.message, f"Perfil aplicado: {name}")
            GLib.idle_add(self._read_light, True)
            GLib.idle_add(self._refresh_status)
            GLib.idle_add(self._reload_buttons)
        self.safe(work)

    def _save_profile_ui(self, *_args) -> None:
        name = self.profile_rename.get_text().strip() or self._current_profile()
        def work():
            with self.mouse() as m:
                path = self._profiles(m).save(name)
            text = path.read_text()
            GLib.idle_add(self.profile_info.set_text, text)
            GLib.idle_add(self._reload_profiles_ui)
            GLib.idle_add(self.message, f"Perfil salvo: {path}")
        self.safe(work)

    def _reset_profile(self, *_args) -> None:
        def work():
            with self.mouse() as m:
                Buttons(m, 0).write([
                    Button(i + 1, tuple(raw)) for i, raw in enumerate(DEFAULT_BUTTONS[0])
                ])
                light = Lighting(m)
                light.set_color(0, 0, 255)
                light.set_effect("static", 255, 0)
            GLib.idle_add(self.message, "Botões restaurados para o mapa de fábrica")
            GLib.idle_add(self._reload_buttons)
            GLib.idle_add(self._read_light, True)
        self.safe(work)
