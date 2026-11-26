#!/usr/bin/python3
"""Interface gráfica GTK 3 para o SM809 (RGB, botões, macros e perfis)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gi  # noqa: E402

gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, Gtk  # noqa: E402

from sm809 import protocol as proto                              # noqa: E402
from sm809.config import Buttons, Lighting, MacroEvent, Macros, Profiles  # noqa: E402
from sm809.runtime import data_home, open_mouse                  # noqa: E402


def rgba_hex(color: Gdk.RGBA) -> str:
    def channel(v: float) -> int:
        return max(0, min(255, round(v * 255)))
    return f"{channel(color.red):02x}{channel(color.green):02x}{channel(color.blue):02x}"


def hex_rgba(text: str) -> Gdk.RGBA:
    text = text.strip().lstrip("#")
    if len(text) != 6:
        raise ValueError("cor deve ter 6 dígitos hexadecimais")
    r, g, b = (int(text[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return Gdk.RGBA(red=r, green=g, blue=b, alpha=1.0)


class App(Gtk.Window):
    def __init__(self, key: str | None = None, verbose: bool = False):
        super().__init__(title="SM809 Control")
        self.key = key
        self.verbose = verbose
        self.set_default_size(780, 580)
        self.set_border_width(12)

        header = Gtk.HeaderBar(title="SM809 Control", subtitle="SOLAKAKA SM809 Wired")
        header.set_show_close_button(True)
        self.set_titlebar(header)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(box)
        self.notebook = Gtk.Notebook()
        box.pack_start(self.notebook, True, True, 0)
        self.status = Gtk.Statusbar()
        box.pack_start(self.status, False, True, 0)

        self._build_light()
        self._build_buttons()
        self._build_macros()
        self._build_profiles()
        self._refresh_status()

    # --------------------------------------------------------------- helpers
    def message(self, text: str) -> None:
        self.status.push(0, text)

    def safe(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - erros aparecem na interface
            self.message(f"Erro: {exc}")
            return None

    def mouse(self):
        return open_mouse(self.key, self.verbose)

    def _refresh_status(self) -> None:
        def work():
            with self.mouse() as m:
                light = Lighting(m)
                state = light.get()
                fw = ""
                if isinstance(m, __import__("sm809.usbfs", fromlist=["UsbMouse"]).UsbMouse):
                    raw = m.read(proto.CMD_FIRMWARE | proto.READ)[0]
                    fw = f" | firmware {raw[0]}.{raw[1]:02x} | chave {m.key.decode()}"
                self.message(
                    f"#{state.color[0]:02x}{state.color[1]:02x}{state.color[2]:02x} "
                    f"{state.mode_name} p1={state.p1:#04x} p2={state.p2:#04x}{fw}"
                )
        self.safe(work)

    # ------------------------------------------------------------------ luz
    def _build_light(self) -> None:
        page = Gtk.Grid(row_spacing=10, column_spacing=12, border_width=16)
        page.set_halign(Gtk.Align.CENTER)
        self.notebook.append_page(page, Gtk.Label(label="Luz"))

        self.color_entry = Gtk.Entry(text="0000ff", width_chars=10)
        self.color_button = Gtk.ColorButton.new_with_rgba(hex_rgba("0000ff"))
        self.color_button.connect("color-set", self._color_changed)

        effect = Gtk.ComboBoxText()
        for name in ("off", "static", "breathing", "neon"):
            effect.append_text(name)
        effect.set_active(1)
        self.effect_combo = effect
        self.p1 = Gtk.SpinButton.new_with_range(0, 255, 1)
        self.p1.set_value(255)
        self.p2 = Gtk.SpinButton.new_with_range(0, 255, 1)

        apply_btn = Gtk.Button(label="Aplicar luz")
        apply_btn.connect("clicked", self._apply_light)

        presets = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for label, color, fx in (
            ("Azul", "0000ff", "static"), ("Vermelho", "ff0000", "static"),
            ("Verde", "00ff00", "static"), ("Branco", "ffffff", "static"),
            ("Desligado", "000000", "off"),
        ):
            btn = Gtk.Button(label=label)
            btn.connect("clicked", self._preset, color, fx)
            presets.pack_start(btn, False, False, 0)

        rows = [
            ("Cor (RRGGBB)", self.color_entry, self.color_button),
            ("Efeito", self.effect_combo, None),
            ("Brilho (p1)", self.p1, None),
            ("Velocidade (p2)", self.p2, None),
        ]
        for i, (label, widget, extra) in enumerate(rows):
            page.attach(Gtk.Label(label=label, halign=Gtk.Align.END), 0, i, 1, 1)
            page.attach(widget, 1, i, 1, 1)
            if extra:
                page.attach(extra, 2, i, 1, 1)
        page.attach(apply_btn, 1, 4, 2, 1)
        page.attach(presets, 0, 5, 3, 1)

    def _color_changed(self, button: Gtk.ColorButton) -> None:
        self.color_entry.set_text(rgba_hex(button.get_rgba()))

    def _apply_light(self, *_args) -> None:
        color = self.color_entry.get_text()

        def work():
            r, g, b = (int(color.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
            with self.mouse() as m:
                light = Lighting(m)
                light.set_color(r, g, b)
                light.set_effect(self.effect_combo.get_active_text(),
                                 int(self.p1.get_value()), int(self.p2.get_value()))
            self.message(f"Luz aplicada: #{r:02x}{g:02x}{b:02x}")
            self._refresh_status()

        self.safe(work)

    def _preset(self, _btn, color: str, effect: str) -> None:
        self.color_entry.set_text(color)
        self.color_button.set_rgba(hex_rgba(color))
        self.effect_combo.set_active(["off", "static", "breathing", "neon"].index(effect))
        self._apply_light()

    # --------------------------------------------------------------- botões
    def _build_buttons(self) -> None:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, border_width=12)
        self.notebook.append_page(page, Gtk.Label(label="Botões"))

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        top.pack_start(Gtk.Label(label="Perfil:"), False, False, 0)
        self.profile_combo = Gtk.ComboBoxText()
        for n in range(1, 5):
            self.profile_combo.append_text(str(n))
        self.profile_combo.set_active(0)
        self.profile_combo.connect("changed", lambda _c: self._reload_buttons())
        top.pack_start(self.profile_combo, False, False, 0)
        reload_btn = Gtk.Button(label="Recarregar")
        reload_btn.connect("clicked", lambda _b: self._reload_buttons())
        top.pack_end(reload_btn, False, False, 0)
        page.pack_start(top, False, True, 0)

        self.button_store = Gtk.ListStore(int, str, str)
        view = Gtk.TreeView(model=self.button_store)
        self.button_view = view
        for i, title in enumerate(("Slot", "Ação", "Bytes")):
            renderer = Gtk.CellRendererText()
            column = Gtk.TreeViewColumn(title, renderer, text=i)
            view.append_column(column)
        select = view.get_selection()
        select.connect("changed", self._button_selected)
        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(300)
        scroll.add(view)
        page.pack_start(scroll, True, True, 0)

        bottom = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bottom.pack_start(Gtk.Label(label="Nova ação:"), False, False, 0)
        self.action_entry = Gtk.Entry(hexpand=True)
        bottom.pack_start(self.action_entry, True, True, 0)
        apply_btn = Gtk.Button(label="Aplicar ao slot")
        apply_btn.connect("clicked", self._apply_button)
        bottom.pack_end(apply_btn, False, False, 0)
        page.pack_start(bottom, False, True, 0)
        page.pack_start(Gtk.Label(
            label="Exemplos: left, dpi-up, key-a, macro-1, multiclick-left-3, disabled",
            halign=Gtk.Align.START), False, True, 0)
        self._reload_buttons()

    def _profile_number(self) -> int:
        return self.profile_combo.get_active() + 1

    def _reload_buttons(self) -> None:
        def work():
            with self.mouse() as m:
                page = self._profile_number() - 1 if isinstance(
                    m, __import__("sm809.usbfs", fromlist=["UsbMouse"]).UsbMouse) else 0
                buttons = Buttons(m, page).read()
            self.button_store.clear()
            for b in buttons:
                self.button_store.append([b.slot, b.action, bytes(b.data).hex(" ")])
        self.safe(work)

    def _button_selected(self, selection) -> None:
        model, treeiter = selection.get_selected()
        if treeiter:
            self.action_entry.set_text(model[treeiter][1])

    def _apply_button(self, *_args) -> None:
        model, treeiter = self.button_view.get_selection().get_selected()
        if not treeiter:
            self.message("Selecione um slot na lista")
            return
        slot = model[treeiter][0]
        action = self.action_entry.get_text()

        def work():
            with self.mouse() as m:
                page = self._profile_number() - 1 if isinstance(
                    m, __import__("sm809.usbfs", fromlist=["UsbMouse"]).UsbMouse) else 0
                Buttons(m, page).set(slot, action)
            self.message(f"Botão {slot} -> {action}")
            self._reload_buttons()

        self.safe(work)

    # ---------------------------------------------------------------- macros
    def _build_macros(self) -> None:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, border_width=12)
        self.notebook.append_page(page, Gtk.Label(label="Macros"))

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        top.pack_start(Gtk.Label(label="Página (1–9):"), False, False, 0)
        self.macro_page = Gtk.SpinButton.new_with_range(1, 9, 1)
        self.macro_page.set_value(1)
        top.pack_start(self.macro_page, False, False, 0)
        read_btn = Gtk.Button(label="Ler")
        read_btn.connect("clicked", lambda _b: self._read_macro())
        top.pack_start(read_btn, False, False, 0)
        write_btn = Gtk.Button(label="Gravar")
        write_btn.connect("clicked", self._write_macro)
        top.pack_end(write_btn, False, False, 0)
        page.pack_start(top, False, True, 0)

        self.macro_view = Gtk.TextView()
        css = Gtk.CssProvider()
        css.load_from_data(b"textview { font-family: monospace; font-size: 11pt; }")
        self.macro_view.get_style_context().add_provider(
            css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(320)
        scroll.add(self.macro_view)
        page.pack_start(scroll, True, True, 0)
        page.pack_start(Gtk.Label(
            label='Eventos: {"key":4,"press":true,"delay":1} | WAIT: {"key":0,"command":1,"wait":50} (2 ms/unidade)',
            halign=Gtk.Align.START), False, True, 0)
        self._read_macro()

    def _macro_text(self) -> str:
        return self.macro_view.get_buffer().get_text(self.macro_view.get_buffer().get_start_iter(),
                                                     self.macro_view.get_buffer().get_end_iter(), False)

    def _set_macro_text(self, text: str) -> None:
        buf = self.macro_view.get_buffer()
        buf.set_text(text)

    def _read_macro(self) -> None:
        def work():
            with self.mouse() as m:
                events = Macros(m).read(int(self.macro_page.get_value()))
            payload = {"repeat": 1, "events": [e.__dict__ for e in events]}
            self._set_macro_text(json.dumps(payload, indent=2, ensure_ascii=False))
            self.message(f"{len(events)} evento(s) na página {int(self.macro_page.get_value())}")
        self.safe(work)

    def _write_macro(self, *_args) -> None:
        def work():
            data = json.loads(self._macro_text() or "{}")
            events_data = data.get("events", []) if isinstance(data, dict) else data
            repeat = int(data.get("repeat", 1)) if isinstance(data, dict) else 1
            events = [MacroEvent(**e) for e in events_data]
            with self.mouse() as m:
                Macros(m).write(int(self.macro_page.get_value()), events, repeat)
            self.message(f"{len(events)} evento(s) gravados")
        self.safe(work)

    # --------------------------------------------------------------- perfis
    def _build_profiles(self) -> None:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, border_width=12)
        self.notebook.append_page(page, Gtk.Label(label="Perfis"))

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        top.pack_start(Gtk.Label(label="Nome:"), False, False, 0)
        self.profile_name = Gtk.Entry(text="azul", hexpand=True)
        top.pack_start(self.profile_name, True, True, 0)
        for label, handler in (("Salvar", self._save_profile),
                               ("Aplicar", self._apply_profile),
                               ("Atualizar", self._reload_profiles)):
            btn = Gtk.Button(label=label)
            btn.connect("clicked", handler)
            top.pack_start(btn, False, False, 0)
        page.pack_start(top, False, True, 0)

        self.profile_store = Gtk.ListStore(str)
        view = Gtk.TreeView(model=self.profile_store)
        view.append_column(Gtk.TreeViewColumn("Perfis salvos", Gtk.CellRendererText(), text=0))
        view.get_selection().connect("changed", self._profile_selected)
        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(260)
        scroll.add(view)
        page.pack_start(scroll, True, True, 0)
        page.pack_start(Gtk.Label(label=f"Dados: {data_home()}", halign=Gtk.Align.START), False, True, 0)
        self._reload_profiles()

    def _reload_profiles(self, *_args) -> None:
        def work():
            with self.mouse() as m:
                names = Profiles(m, data_home() / "profiles").list()
            self.profile_store.clear()
            for name in names:
                self.profile_store.append([name])
        self.safe(work)

    def _profile_selected(self, selection) -> None:
        model, treeiter = selection.get_selected()
        if treeiter:
            self.profile_name.set_text(model[treeiter][0])

    def _save_profile(self, *_args) -> None:
        name = self.profile_name.get_text()

        def work():
            with self.mouse() as m:
                path = Profiles(m, data_home() / "profiles").save(name)
            self.message(f"Perfil salvo: {path}")
            self._reload_profiles()

        self.safe(work)

    def _apply_profile(self, *_args) -> None:
        name = self.profile_name.get_text()

        def work():
            with self.mouse() as m:
                Profiles(m, data_home() / "profiles").apply(name)
            self.message(f"Perfil aplicado: {name}")
            self._refresh_status()
            self._reload_buttons()

        self.safe(work)


def main() -> None:
    parser = argparse.ArgumentParser(description="Interface gráfica do SM809")
    parser.add_argument("--key", help="chave de 6 caracteres (ex.: FB1570)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    App(args.key, args.verbose).show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
