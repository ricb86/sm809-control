#!/bin/sh
# Gera sm809-control_<versao>_all.deb sem fakeroot (usa --root-owner-group).
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
VERSION=$(cat "$ROOT/VERSION")
DIST="$ROOT/dist"
STAGE="$DIST/build-sm809-control"

rm -rf "$STAGE"
mkdir -p \
  "$STAGE/DEBIAN" \
  "$STAGE/usr/bin" \
  "$STAGE/usr/share/sm809/sm809" \
  "$STAGE/usr/share/applications" \
  "$STAGE/usr/share/icons/hicolor/64x64/apps" \
  "$STAGE/usr/share/icons/hicolor/128x128/apps" \
  "$STAGE/usr/share/icons/hicolor/scalable/apps" \
  "$STAGE/usr/share/doc/sm809-control/examples" \
  "$STAGE/lib/udev/rules.d"

# --- metadados -------------------------------------------------------------
cat > "$STAGE/DEBIAN/control" <<EOF
Package: sm809-control
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.8), python3-gi, gir1.2-gtk-3.0, udev
Maintainer: ricb86 <ricb86@users.noreply.github.com>
Homepage: https://github.com/ricb86/sm809-control
Description: Controlador para mouse SOLAKAKA SM809 (RGB, botões e macros)
 Software Linux para o mouse gamer SOLAKAKA SM809 Wired (04D9:A09F).
 Controla cor/efeitos RGB, remapeamento de botões, macros e perfis,
 com interface gráfica GTK e CLI. Compatível com firmware 2.x e 3.x.
EOF

cat > "$STAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ -x /usr/bin/udevadm ]; then
    udevadm control --reload-rules || true
    udevadm trigger || true
fi
EOF

cat > "$STAGE/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if [ -x /usr/bin/udevadm ]; then
    udevadm control --reload-rules || true
    udevadm trigger || true
fi
EOF
chmod 755 "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/postrm"

# --- codigo ----------------------------------------------------------------
cp "$ROOT/src/sm809ctl.py" "$ROOT/src/sm809gui.py" "$STAGE/usr/share/sm809/"
find "$ROOT/src/sm809" -maxdepth 1 -name '*.py' -exec cp {} "$STAGE/usr/share/sm809/sm809/" \;

cat > "$STAGE/usr/bin/sm809ctl" <<'EOF'
#!/bin/sh
exec /usr/bin/python3 /usr/share/sm809/sm809ctl.py "$@"
EOF
cat > "$STAGE/usr/bin/sm809-gui" <<'EOF'
#!/bin/sh
exec /usr/bin/python3 /usr/share/sm809/sm809gui.py "$@"
EOF
chmod 755 "$STAGE/usr/bin/sm809ctl" "$STAGE/usr/bin/sm809-gui"

# --- integracao desktop ----------------------------------------------------
python3 "$ROOT/packaging/make_icon.py" >/dev/null
cp "$ROOT/packaging/sm809.desktop" "$STAGE/usr/share/applications/"
cp "$ROOT/packaging/icons/sm809-64.png" "$STAGE/usr/share/icons/hicolor/64x64/apps/sm809.png"
cp "$ROOT/packaging/icons/sm809-128.png" "$STAGE/usr/share/icons/hicolor/128x128/apps/sm809.png"
cp "$ROOT/packaging/icons/sm809.svg" "$STAGE/usr/share/icons/hicolor/scalable/apps/sm809.svg"
cp "$ROOT/udev/99-sm809.rules" "$STAGE/lib/udev/rules.d/99-sm809.rules"

# --- documentacao ----------------------------------------------------------
cp "$ROOT/README.md" "$ROOT/LICENSE" "$STAGE/usr/share/doc/sm809-control/"
cp "$ROOT/docs/protocolo.md" "$STAGE/usr/share/doc/sm809-control/"
cp "$ROOT/examples/macro-exemplo.json" "$STAGE/usr/share/doc/sm809-control/examples/"
cat > "$STAGE/usr/share/doc/sm809-control/changelog.Debian" <<EOF
sm809-control ($VERSION) unstable; urgency=low

  * RGB, botoes, macros, perfis, CLI e interface grafica GTK.
  * Suporte ao firmware 3.01 via usbfs.

 -- ricb86 <ricb86@users.noreply.github.com>  $(date -R)
EOF

# --- build -----------------------------------------------------------------
mkdir -p "$DIST"
DEB="$DIST/sm809-control_${VERSION}_all.deb"
dpkg-deb --build --root-owner-group "$STAGE" "$DEB"
echo "Pacote gerado: $DEB"
dpkg-deb --info "$DEB" | sed -n '1,20p'
