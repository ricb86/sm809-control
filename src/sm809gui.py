#!/usr/bin/python3
"""Interface GTK 3 do SM809 inspirada no driver original."""
from __future__ import annotations
import argparse, fcntl, json, os, sys, threading, time
from contextlib import contextmanager
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import gi  # noqa: E402
gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_foreign("cairo")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402
import cairo  # noqa: E402
from sm809 import protocol as proto  # noqa: E402
from sm809.config import Buttons, Lighting, MacroEvent, Macros, Profiles  # noqa: E402
from sm809.runtime import data_home, open_mouse  # noqa: E402
from sm809.usbfs import UsbMouse  # noqa: E402

LIGHT_MODES = [
    ("off", "Off", 0x00), ("static", "Standard", 0x01),
    ("breathing", "Breathing", 0x02), ("neon", "Neon", 0x03),
    ("wave", "Wave", 0x04), ("key-reaction", "Key reaction", 0x05),
    ("trailing", "Trailing", 0x06), ("drag", "Drag back and forth", 0x07),
    ("slide", "Slide", 0x08), ("yo-yo", "YO-YO", 0x09),
    ("marbles", "Marbles", 0x0A), ("flying-star", "Flying star", 0x0B),
]
LOOP_COLORS = ["ff0000", "00ff00", "0000ff", "ffff00",
               "ff00ff", "00ffff", "ff7f00", "ffffff"]
DPI_COLORS = LOOP_COLORS  # cores dos 8 estagios (pagina 1 do comando 0x10)
CSS = b"""
window { background-color: #111111; color: #e8e8e8; }
headerbar { background-color: #202020; color: #ffffff; }
notebook header { background-color: #181818; }
notebook tab { background-color: #2b2b2b; color: #cfcfcf; padding: 6px 14px; }
notebook tab:checked { background-color: #0d6efd; color: #ffffff; }
.frame { background-color: #1c1c1c; border: 1px solid #5f5f5f; }
.section { background-color: #5f5f5f; color: #ffffff; padding: 6px 12px; font-weight: bold; }
.button { background-color: #363636; color: #eeeeee; border: 1px solid #555555; }
.entry, .textview { background-color: #242424; color: #eeeeee; }
.treeview { background-color: #242424; color: #eeeeee; }
.statusbar { background-color: #181818; color: #9a9a9a; }
"""


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


def parse_hex(text: str) -> tuple[int, int, int]:
    value = text.strip().lstrip("#")
    if len(value) != 6:
        raise ValueError("cor deve estar no formato RRGGBB")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


class App(Gtk.Window):
    def __init__(self, key: str | None = None, verbose: bool = False):
        super().__init__(title="SM809 Control")
        self.key, self.verbose = key, verbose
        self._hw_lock = threading.Lock()
        self.dpi_stage = 0
        self._dpi_stop = threading.Event()
        self._dpi_thread = None
        self.set_default_size(1000, 660)
        self.set_border_width(10)
        header = Gtk.HeaderBar(title="SM809 Control", subtitle="SOLAKAKA SM809 Wired")
        header.set_show_close_button(True)
        self.set_titlebar(header)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add(box)
        self.notebook = Gtk.Notebook()
        box.pack_start(self.notebook, True, True, 0)
        self.status = Gtk.Statusbar()
        box.pack_start(self.status, False, True, 0)
        self.fw3 = self._detect_firmware3()
        self.color_hex = "0000ff"
        self._build_light()
        self._build_buttons()
        self._build_macros()
        self._build_profiles()
        self._read_light(silent=True)
        self._refresh_status()
        self.safe(self._write_dpi_palette)
        if os.environ.get("SM809_DPI_INDICATOR") == "1":
            self.dpi_indicator.set_active(True)

    def message(self, text: str) -> None:
        self.status.push(0, text)

    def safe(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            self.message(f"Erro: {exc}")
            return None

    @contextmanager
    def mouse(self):
        with self._hw_lock:
            with open_mouse(self.key, self.verbose) as device:
                yield device

    def _detect_firmware3(self) -> bool:
        try:
            with self.mouse() as m:
                return isinstance(m, UsbMouse)
        except Exception:
            return False

    def _section(self, title: str, child: Gtk.Widget) -> Gtk.Frame:
        frame = Gtk.Frame()
        frame.get_style_context().add_class("frame")
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        label = Gtk.Label(label=title, xalign=0)
        label.get_style_context().add_class("section")
        inner.pack_start(label, False, True, 0)
        inner.pack_start(child, True, True, 0)
        frame.add(inner)
        return frame

    def _slider(self, title: str, low: int, high: int, value: int):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        top.pack_start(Gtk.Label(label=title, xalign=0), True, True, 0)
        readout = Gtk.Label(label=str(value))
        top.pack_end(readout, False, True, 0)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, low, high, 1)
        scale.set_value(value)
        scale.set_draw_value(False)
        scale.set_hexpand(True)
        scale.connect("value-changed", self._param_changed)
        box.pack_start(top, False, True, 0)
        box.pack_start(scale, False, True, 0)
        return box, scale, readout

    def _refresh_status(self) -> None:
        def work():
            with self.mouse() as m:
                state = Lighting(m).get()
                fw = ""
                if isinstance(m, UsbMouse):
                    raw = m.read(proto.CMD_FIRMWARE | proto.READ)[0]
                    fw = f" | firmware {raw[0]}.{raw[1]:02x} | chave {m.key.decode()}"
                self.message(
                    f"#{state.color[0]:02x}{state.color[1]:02x}{state.color[2]:02x} "
                    f"{state.mode_name} p1={state.p1:#04x} p2={state.p2:#04x}{fw}")
        self.safe(work)

    # -------------------------------------------------------------- luz
    def _build_light(self) -> None:
        page = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, border_width=12)
        self.notebook.append_page(page, Gtk.Label(label="Luz"))
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        left.set_size_request(460, -1)
        page.pack_start(left, True, True, 0)

        modes = Gtk.Grid(row_spacing=4, column_spacing=18, border_width=10)
        self.mode_buttons = {}
        group = None
        for index, (key, label, code) in enumerate(LIGHT_MODES):
            if group is None:
                radio = Gtk.RadioButton(label=label)
                group = radio
            else:
                radio = Gtk.RadioButton.new_from_widget(group)
                radio.set_label(label)
            radio.connect("toggled", self._mode_changed, key)
            self.mode_buttons[key] = radio
            modes.attach(radio, index // 6, index % 6, 1, 1)
        left.pack_start(self._section("Light Setting", modes), False, True, 0)

        params = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, border_width=10)
        self.brightness_box, self.brightness, self.brightness_label = self._slider("Brightness", 0, 255, 255)
        self.frequency_box, self.frequency, self.frequency_label = self._slider("Frequency", 0, 4, 3)
        self.length_box, self.length, self.length_label = self._slider("Length", 0, 4, 3)
        params.pack_start(self.brightness_box, False, True, 0)
        params.pack_start(self.frequency_box, False, True, 0)
        params.pack_start(self.length_box, False, True, 0)
        left.pack_start(self._section("Parameter Setting", params), False, True, 0)

        colors = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, border_width=10)
        color_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.fixed_radio = Gtk.RadioButton(label="Fix Color:")
        self.loop_radio = Gtk.RadioButton.new_from_widget(self.fixed_radio)
        self.loop_radio.set_label("Loop Color:")
        self.fixed_radio.set_active(True)
        self.color_button = Gtk.ColorButton.new_with_rgba(hex_rgba(self.color_hex))
        self.color_button.connect("color-set", self._color_changed)
        color_row.pack_start(self.fixed_radio, False, True, 0)
        color_row.pack_start(self.color_button, False, True, 0)
        color_row.pack_start(self.loop_radio, False, True, 0)
        colors.pack_start(color_row, False, True, 0)
        palette = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        for hex_color in LOOP_COLORS:
            btn = Gtk.Button()
            btn.set_size_request(32, 28)
            btn.set_tooltip_text(f"#{hex_color}")
            provider = Gtk.CssProvider()
            provider.load_from_data(
                f"button {{ background-color: #{hex_color}; border: 1px solid #777777; }}".encode())
            btn.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
            btn.connect("clicked", self._choose_palette_color, hex_color)
            palette.pack_start(btn, False, True, 0)
        colors.pack_start(palette, False, True, 0)
        left.pack_start(self._section("Color Setting", colors), False, True, 0)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        for label, handler in (("Apply Light", self._apply_light),
                               ("Read Light", lambda _b: self._read_light()),
                               ("Restore Blue", self._restore_blue)):
            btn = Gtk.Button(label=label)
            btn.connect("clicked", handler)
            actions.pack_start(btn, False, True, 0)
        left.pack_start(actions, False, True, 0)
        self.dpi_indicator = Gtk.CheckButton(label="Atualizar LED DPI ao trocar estagio")
        self.dpi_indicator.set_tooltip_text(
            "Quando ativo, DPI+/DPI- reescreve a cor do LED dedicado do DPI.")
        self.dpi_indicator.connect("toggled", self._toggle_dpi_indicator)
        left.pack_start(self.dpi_indicator, False, True, 0)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        right.pack_start(Gtk.Label(label="Preview", xalign=0), False, True, 0)
        self.preview = Gtk.DrawingArea()
        self.preview.set_size_request(280, 470)
        self.preview.connect("draw", self._draw_mouse)
        right.pack_start(self.preview, True, True, 0)
        page.pack_start(right, False, True, 0)
        self._update_mode_controls()

    def _selected_mode(self) -> str:
        for key, radio in self.mode_buttons.items():
            if radio.get_active():
                return key
        return "static"

    def _update_mode_controls(self) -> None:
        mode = self._selected_mode()
        self.brightness_box.set_visible(mode in ("static", "key-reaction", "slide", "yo-yo", "marbles", "flying-star"))
        self.frequency_box.set_visible(mode in ("breathing", "neon", "wave", "trailing", "drag"))
        self.length_box.set_visible(mode in ("neon", "wave"))
        for label, scale in ((self.brightness_label, self.brightness),
                             (self.frequency_label, self.frequency),
                             (self.length_label, self.length)):
            label.set_text(str(int(scale.get_value())))
        self.preview.queue_draw()

    def _mode_changed(self, _radio, _key: str) -> None:
        self._update_mode_controls()

    def _param_changed(self, scale: Gtk.Scale) -> None:
        for label, candidate in ((self.brightness_label, self.brightness),
                                 (self.frequency_label, self.frequency),
                                 (self.length_label, self.length)):
            if scale is candidate:
                label.set_text(str(int(scale.get_value())))
        self.preview.queue_draw()

    def _color_changed(self, button: Gtk.ColorButton) -> None:
        self.color_hex = rgba_hex(button.get_rgba())
        self.fixed_radio.set_active(True)
        self.preview.queue_draw()

    def _choose_palette_color(self, _btn, hex_color: str) -> None:
        self.color_hex = hex_color
        self.color_button.set_rgba(hex_rgba(hex_color))
        self.loop_radio.set_active(True)
        self.preview.queue_draw()

    def _params_for_mode(self) -> tuple[int, int]:
        mode = self._selected_mode()
        p1, p2 = proto.DEFAULT_EFFECT_PARAMS[proto.EFFECTS[mode]]
        if mode == "static":
            p1 = int(self.brightness.get_value())
        elif mode in ("breathing", "trailing", "drag"):
            p1 = int(self.frequency.get_value())
        elif mode in ("neon", "wave"):
            p1 = int(self.frequency.get_value())
            p2 = int(self.length.get_value())
        elif mode in ("key-reaction", "slide", "yo-yo", "marbles", "flying-star"):
            p1 = int(self.brightness.get_value())
        return p1, p2

    def _apply_light(self, *_args) -> None:
        mode = self._selected_mode()
        p1, p2 = self._params_for_mode()
        color = self.color_hex
        loop = self.loop_radio.get_active()

        def work():
            r, g, b = parse_hex(color)
            with self.mouse() as m:
                light = Lighting(m)
                if loop:
                    light.set_palette([parse_hex(c) for c in LOOP_COLORS])
                if mode != "off":
                    light.set_color(r, g, b)
                light.set_effect(mode, p1, p2)
            extra = " | Loop Color" if loop else ""
            self.message(f"Luz aplicada: {mode} #{r:02x}{g:02x}{b:02x} "
                         f"p1={p1:#04x} p2={p2:#04x}{extra}")
            self._refresh_status()
        self.safe(work)

    def _restore_blue(self, *_args) -> None:
        self.color_hex = "0000ff"
        self.color_button.set_rgba(hex_rgba("0000ff"))
        self.fixed_radio.set_active(True)
        self.mode_buttons["static"].set_active(True)
        self.brightness.set_value(255)
        self._apply_light()

    # ------------------------ indicador de cor do DPI -----------------------
    @staticmethod
    def _find_hidraw() -> str | None:
        base = "/sys/class/hidraw"
        if not os.path.isdir(base):
            return None
        for name in os.listdir(base):
            uevent = os.path.join(base, name, "device", "uevent")
            try:
                text = open(uevent, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            if "HID_ID=0003:000004D9:0000A09F" in text:
                return "/dev/" + name
        return None

    def _toggle_dpi_indicator(self, button: Gtk.CheckButton) -> None:
        if button.get_active():
            path = self._find_hidraw()
            if not path:
                button.set_active(False)
                self.message("Mouse hidraw nao encontrado")
                return
            self._dpi_stop.clear()
            self._dpi_thread = threading.Thread(
                target=self._dpi_monitor_loop, args=(path,), daemon=True)
            self._dpi_thread.start()
            self.message(f"Indicador DPI ativo ({path})")
        else:
            self._dpi_stop.set()
            if self._dpi_thread:
                self._dpi_thread.join(timeout=1)
                self._dpi_thread = None
            self.message("Indicador DPI desativado")

    def _dpi_monitor_loop(self, path: str) -> None:
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError as exc:
            GLib.idle_add(self.message, f"Indicador DPI: {exc}")
            GLib.idle_add(self.dpi_indicator.set_active, False)
            return
        previous = 0
        try:
            while not self._dpi_stop.is_set():
                try:
                    data = os.read(fd, 64)
                except BlockingIOError:
                    time.sleep(0.02)
                    continue
                except OSError:
                    break
                if not data:
                    continue
                buttons = data[0] & 0x11  # 0x10 = DPI+, 0x01 = DPI-
                if previous & 0x10 and not buttons & 0x10:
                    self.dpi_stage = (self.dpi_stage + 1) % len(DPI_COLORS)
                    GLib.idle_add(self._apply_dpi_color)
                if previous & 0x01 and not buttons & 0x01:
                    self.dpi_stage = (self.dpi_stage - 1) % len(DPI_COLORS)
                    GLib.idle_add(self._apply_dpi_color)
                previous = buttons
        finally:
            os.close(fd)

    def _write_dpi_palette(self) -> None:
        """Reescreve a pagina 1; isso atualiza o LED dedicado do estagio atual."""
        with self.mouse() as m:
            Lighting(m).set_palette([parse_hex(c) for c in DPI_COLORS], page=1)

    def _apply_dpi_color(self) -> None:
        try:
            self._write_dpi_palette()
            self.message(f"Indicador DPI atualizado (estagio {self.dpi_stage + 1})")
        except Exception as exc:  # noqa: BLE001
            self.message(f"Indicador DPI: {exc}")

    def _read_light(self, silent: bool = False) -> None:
        def work():
            with self.mouse() as m:
                state = Lighting(m).get()
            self.color_hex = f"{state.color[0]:02x}{state.color[1]:02x}{state.color[2]:02x}"
            self.color_button.set_rgba(hex_rgba(self.color_hex))
            for key, radio in self.mode_buttons.items():
                if proto.EFFECTS[key] == state.mode:
                    radio.set_active(True)
            if state.mode == 0x01:
                self.brightness.set_value(state.p1)
            if 0 <= state.p1 <= 4:
                self.frequency.set_value(state.p1)
            if 0 <= state.p2 <= 4:
                self.length.set_value(state.p2)
            self._update_mode_controls()
            if not silent:
                self.message("Estado do mouse carregado na interface")
        self.safe(work)

    def _draw_mouse(self, area: Gtk.DrawingArea, cr: cairo.Context) -> None:
        width, height = area.get_allocated_width(), area.get_allocated_height()
        cr.save()
        cr.scale(width / 280.0, height / 470.0)
        mode = self._selected_mode()
        try:
            r, g, b = parse_hex(self.color_hex)
        except ValueError:
            r, g, b = 0, 0, 255
        bright = int(self.brightness.get_value()) / 255 if mode == "static" else 0.9

        cr.move_to(140, 30)
        cr.curve_to(70, 30, 38, 105, 38, 220)
        cr.curve_to(38, 350, 82, 450, 140, 450)
        cr.curve_to(198, 450, 242, 350, 242, 220)
        cr.curve_to(242, 105, 210, 30, 140, 30)
        cr.close_path()
        gradient = cairo.LinearGradient(60, 40, 220, 450)
        if mode == "off":
            gradient.add_color_stop_rgb(0, 0.14, 0.14, 0.16)
            gradient.add_color_stop_rgb(1, 0.08, 0.08, 0.09)
        elif mode in ("neon", "wave", "yo-yo", "marbles", "flying-star"):
            for stop, color in enumerate(LOOP_COLORS):
                cr_color = parse_hex(color)
                gradient.add_color_stop_rgb(stop / 7, *(c / 255 for c in cr_color))
        else:
            gradient.add_color_stop_rgb(0, r / 255 * bright, g / 255 * bright, b / 255 * bright)
            gradient.add_color_stop_rgb(1, r / 255 * bright * 0.35,
                                        g / 255 * bright * 0.35, b / 255 * bright * 0.35)
        cr.set_source(gradient)
        cr.fill_preserve()
        cr.set_source_rgb(0.30, 0.30, 0.33)
        cr.set_line_width(3)
        cr.stroke()

        cr.set_source_rgba(0.05, 0.05, 0.06, 0.85)
        cr.set_line_width(2)
        cr.move_to(140, 96)
        cr.line_to(140, 205)
        cr.stroke()
        cr.rectangle(130, 52, 20, 44)
        cr.fill()
        cr.set_source_rgb(0.80, 0.84, 0.92)
        cr.rectangle(132, 54, 16, 38)
        cr.fill()

        cr.set_source_rgba(0.10, 0.10, 0.12, 0.9)
        for index in range(9):
            y = 96 + index * 33
            cr.rectangle(48, y, 30, 26)
            cr.fill()
            cr.set_source_rgb(0.85, 0.86, 0.90)
            cr.select_font_face("Sans")
            cr.set_font_size(12)
            cr.move_to(59, y + 18)
            cr.show_text(str(index + 1))
            cr.set_source_rgba(0.10, 0.10, 0.12, 0.9)
        cr.restore()

    # ------------------------------------------------------------ botões
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
            view.append_column(Gtk.TreeViewColumn(title, Gtk.CellRendererText(), text=i))
        view.get_selection().connect("changed", self._button_selected)
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
                page = self._profile_number() - 1 if isinstance(m, UsbMouse) else 0
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
        slot, action = model[treeiter][0], self.action_entry.get_text()

        def work():
            with self.mouse() as m:
                page = self._profile_number() - 1 if isinstance(m, UsbMouse) else 0
                Buttons(m, page).set(slot, action)
            self.message(f"Botão {slot} -> {action}")
            self._reload_buttons()
        self.safe(work)

    # ------------------------------------------------------------- macros
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
        self.macro_view.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        scroll = Gtk.ScrolledWindow()
        scroll.set_min_content_height(320)
        scroll.add(self.macro_view)
        page.pack_start(scroll, True, True, 0)
        page.pack_start(Gtk.Label(
            label='Eventos: {"key":4,"press":true,"delay":1} | WAIT: {"key":0,"command":1,"wait":50}',
            halign=Gtk.Align.START), False, True, 0)
        self._read_macro()

    def _macro_text(self) -> str:
        buf = self.macro_view.get_buffer()
        return buf.get_text(buf.get_start_iter(), buf.get_end_iter(), False)

    def _set_macro_text(self, text: str) -> None:
        self.macro_view.get_buffer().set_text(text)

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

    # ------------------------------------------------------------ perfis
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
            self._read_light(silent=True)
            self._reload_buttons()
        self.safe(work)


def main() -> None:
    parser = argparse.ArgumentParser(description="Interface gráfica do SM809")
    parser.add_argument("--key", help="chave de 6 caracteres")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    # Evita duas instancias disputando a escrita no mouse.
    data_home().mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(data_home() / "sm809-gui.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(lock_fd)
        dialog = Gtk.MessageDialog(
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.OK,
            text="O SM809 Control já está aberto.",
        )
        dialog.run()
        dialog.destroy()
        return

    settings = Gtk.Settings.get_default()
    if settings:
        settings.set_property("gtk-application-prefer-dark-theme", True)
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    app = App(args.key, args.verbose)
    app.show_all()
    app._update_mode_controls()  # show_all() revela tambem os controles ocultos
    Gtk.main()


if __name__ == "__main__":
    main()
