#!/usr/bin/env python3
"""CLI para o mouse SOLAKAKA SM809 Wired (Holtek 04D9:A09F) em Linux."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sm809 import protocol as proto                     # noqa: E402
from sm809.config import Buttons, Lighting, MacroEvent, Macros, Profiles  # noqa: E402
from sm809.runtime import data_home, open_mouse         # noqa: E402
from sm809.usbfs import UsbMouse                        # noqa: E402

BACKUPS = data_home() / "backups"
PROFILES = data_home() / "profiles"


def parse_rgb(text: str) -> tuple[int, int, int]:
    text = text.strip().lstrip("#")
    if len(text) != 6:
        raise argparse.ArgumentTypeError("cor deve ter 6 digitos hex (RRGGBB)")
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError as exc:
        raise argparse.ArgumentTypeError("cor invalida") from exc


def backup(light: Lighting) -> Path:
    state = light.get()
    BACKUPS.mkdir(parents=True, exist_ok=True)
    path = BACKUPS / f"led-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps({
        "color": list(state.color),
        "mode": state.mode,
        "p1": state.p1,
        "p2": state.p2,
    }, indent=2) + "\n")
    return path


def confirm(yes: bool, detail: str) -> None:
    if yes:
        return
    print(detail)
    if input("Gravar no mouse? [y/N] ").strip().lower() != "y":
        raise SystemExit("cancelado")


def cmd_detect(args) -> None:
    with open_mouse(args.key, args.verbose) as m:
        print(f"dispositivo : {m.path}")
        print(f"backend     : {m.__class__.__name__}")
        print(f"chave       : {m.key.decode('ascii', 'replace')}")
        if isinstance(m, UsbMouse):
            fw = m.read(proto.CMD_FIRMWARE | proto.READ)[0]
            print(f"firmware    : {fw[0]}.{fw[1]:02x}")
        light = Lighting(m)
        state = light.get()
        print(f"cor         : #{state.color[0]:02x}{state.color[1]:02x}{state.color[2]:02x}")
        print(f"efeito      : {state.mode_name} ({state.mode:02x}) p1={state.p1:#04x} p2={state.p2:#04x}")
        div_reply = m.read(proto.CMD_POLLING | proto.READ)[0]
        if div_reply[0]:
            print(f"polling     : {1000 // div_reply[0]} Hz")


def cmd_status(args) -> None:
    cmd_detect(args)


def cmd_rgb(args) -> None:
    with open_mouse(args.key, args.verbose) as m:
        light = Lighting(m)
        old = light.get()
        path = backup(light)
        detail = (
            f"cor atual  #{old.color[0]:02x}{old.color[1]:02x}{old.color[2]:02x}\n"
            f"nova cor   #{args.color[0]:02x}{args.color[1]:02x}{args.color[2]:02x}\n"
            f"backup     {path}"
        )
        confirm(args.yes, detail)
        light.set_color(*args.color)
        if args.effect is not None:
            light.set_effect(args.effect, args.p1, args.p2)
        new = light.get()
        ok = (new.color == args.color and
              (args.effect is None or new.mode == proto.EFFECTS[args.effect]))
        print(f"agora      #{new.color[0]:02x}{new.color[1]:02x}{new.color[2]:02x} "
              f"{new.mode_name} p1={new.p1:#04x} p2={new.p2:#04x}")
        print("VERIFICADO" if ok else "ERRO: leitura diferente do solicitado")
        if not ok:
            raise SystemExit(1)


def cmd_effect(args) -> None:
    with open_mouse(args.key, args.verbose) as m:
        light = Lighting(m)
        path = backup(light)
        confirm(args.yes, f"efeito {args.name}, backup {path}")
        light.set_effect(args.name, args.p1, args.p2)
        state = light.get()
        print(f"efeito agora: {state.mode_name} ({state.mode:02x}) p1={state.p1:#04x} p2={state.p2:#04x}")


def _button_page(m, profile: int) -> int:
    """Perfis 1..4 do software viram paginas 0..3 no usbfs (3.x)."""
    if not 1 <= profile <= 4:
        raise ValueError("perfil deve estar entre 1 e 4")
    return profile - 1 if isinstance(m, UsbMouse) else 1


def cmd_buttons(args) -> None:
    with open_mouse(args.key, args.verbose) as m:
        buttons = Buttons(m, _button_page(m, args.profile))
        if args.action == "list":
            for b in buttons.read():
                print(f"{b.slot:2d} {b.action:24s} {bytes(b.data).hex(' ')}")
            return
        if not args.slot or not args.value:
            raise SystemExit("uso: buttons set <slot> <acao>")
        old = buttons.read()[args.slot - 1]
        buttons.set(args.slot, args.value)
        print(f"botao {args.slot}: {old.action} -> {buttons.read()[args.slot - 1].action}")


def cmd_macro(args) -> None:
    with open_mouse(args.key, args.verbose) as m:
        macros = Macros(m)
        if args.action == "read":
            events = macros.read(args.page)
            if not events:
                print("(vazio)")
            for i, ev in enumerate(events, 1):
                print(f"{i:2d} {ev}")
            return
        if not args.file:
            raise SystemExit("uso: macro write --page N --file events.json")
        data = json.loads(args.file.read_text())
        if isinstance(data, dict):
            events_data = data.get("events", [])
            repeat = int(data.get("repeat", 1))
        else:
            events_data, repeat = data, 1
        events = [MacroEvent(**e) for e in events_data]
        macros.write(args.page, events, repeat)
        print(f"{len(events)} eventos gravados na pagina {args.page}")


def cmd_profile(args) -> None:
    with open_mouse(args.key, args.verbose) as m:
        profiles = Profiles(m, PROFILES, button_page=_button_page(m, args.profile))
        if args.action == "list":
            for name in profiles.list():
                print(name)
        elif args.action == "save":
            print(profiles.save(args.name))
        else:
            if not args.name:
                raise SystemExit("uso: profile apply <nome>")
            profiles.apply(args.name)
            print(f"perfil {args.name} aplicado")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--key", help="chave de 6 caracteres (ex.: FB1570)")
    ap.add_argument("--verbose", action="store_true")
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("detect", help="identifica o mouse e mostra o estado").set_defaults(func=cmd_detect)
    sub.add_parser("status", help="alias de detect").set_defaults(func=cmd_status)

    rgb = sub.add_parser("rgb", help="define a cor RGB")
    rgb.add_argument("color", type=parse_rgb, metavar="RRGGBB")
    rgb.add_argument("--effect", choices=sorted(proto.EFFECTS))
    rgb.add_argument("--p1", type=lambda s: int(s, 0))
    rgb.add_argument("--p2", type=lambda s: int(s, 0))
    rgb.add_argument("--yes", action="store_true", help="nao pedir confirmacao")
    rgb.set_defaults(func=cmd_rgb)

    eff = sub.add_parser("effect", help="define o efeito de luz")
    eff.add_argument("name", choices=sorted(proto.EFFECTS))
    eff.add_argument("--p1", type=lambda s: int(s, 0))
    eff.add_argument("--p2", type=lambda s: int(s, 0))
    eff.add_argument("--yes", action="store_true")
    eff.set_defaults(func=cmd_effect)

    bt = sub.add_parser("buttons", help="lista/remapeia botoes (funciona em 2.x e 3.x)")
    bt.add_argument("action", choices=("list", "set"))
    bt.add_argument("slot", type=int, nargs="?")
    bt.add_argument("value", nargs="?", metavar="ACAO")
    bt.add_argument("--profile", type=int, default=1, help="perfil 1..4 (padrao 1)")
    bt.set_defaults(func=cmd_buttons)

    mac = sub.add_parser("macro", help="le/grava macros (funciona em 2.x e 3.x)")
    mac.add_argument("action", choices=("read", "write"))
    mac.add_argument("--page", type=int, default=1, help="pagina 1..9 (padrao 1)")
    mac.add_argument("--file", type=Path, help="JSON com events[], opcionalmente repeat")
    mac.set_defaults(func=cmd_macro)

    prof = sub.add_parser("profile", help="salva/aplica perfis locais")
    prof.add_argument("action", choices=("list", "save", "apply"))
    prof.add_argument("name", nargs="?")
    prof.add_argument("--profile", type=int, default=1, help="perfil de botoes 1..4")
    prof.set_defaults(func=cmd_profile)
    return ap


def main() -> None:
    args = build_parser().parse_args()
    try:
        args.func(args)
    except (OSError, ValueError, TimeoutError, PermissionError, NotImplementedError) as exc:
        raise SystemExit(f"erro: {exc}") from exc


if __name__ == "__main__":
    main()
