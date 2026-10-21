#!/bin/sh
# Construye el paquete .deb de Kabe (prioritario para MX Linux y Debian).
#
#   ./packaging/build_deb.sh [version]
#
# Necesita: dpkg-deb (debian) y los binarios de Python 3 + PyGObject.
set -e

VERSION="${1:-$(grep -oP '__version__ = "\K[^"]+' "$(dirname "$0")/../kabe/__init__.py")}"
ARCH="$(dpkg --print-architecture 2>/dev/null || echo amd64)"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BUILD="$(mktemp -d)"
PKG="$BUILD/kabe_${VERSION}_${ARCH}"

echo "Kabe $VERSION ($ARCH)"

mkdir -p "$PKG/DEBIAN"
mkdir -p "$PKG/usr/bin" "$PKG/usr/lib/kabe" "$PKG/usr/share/kabe" \
         "$PKG/usr/share/applications" "$PKG/usr/share/icons/hicolor" \
         "$PKG/usr/share/doc/kabe"

cp -r "$ROOT/kabe" "$PKG/usr/lib/kabe/"
find "$PKG/usr/lib/kabe" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
cp -r "$ROOT/share/." "$PKG/usr/share/kabe/share/" 2>/dev/null || true
cp "$ROOT/kabe-icon.svg" "$ROOT/kabe-logo.svg" "$PKG/usr/share/kabe/" 2>/dev/null || true
cp "$ROOT/desktop/kabe.desktop" "$PKG/usr/share/applications/"

for size in 16 24 32 48 64 128 256; do
    src="$ROOT/share/icons/hicolor/${size}x${size}/apps/kabe.png"
    [ -f "$src" ] || continue
    mkdir -p "$PKG/usr/share/icons/hicolor/${size}x${size}/apps"
    cp "$src" "$PKG/usr/share/icons/hicolor/${size}x${size}/apps/"
done
for kind in scalable symbolic; do
    src="$ROOT/share/icons/hicolor/$kind/apps"
    [ -d "$src" ] || continue
    mkdir -p "$PKG/usr/share/icons/hicolor/$kind/apps"
    cp "$src"/* "$PKG/usr/share/icons/hicolor/$kind/apps/" 2>/dev/null || true
done

cat > "$PKG/usr/bin/kabe" <<'EOF'
#!/bin/sh
PYTHONPATH="/usr/lib/kabe${PYTHONPATH:+:$PYTHONPATH}" exec python3 -m kabe "$@"
EOF
chmod +x "$PKG/usr/bin/kabe"

cat > "$PKG/DEBIAN/control" <<EOF
Package: kabe
Version: $VERSION
Section: utils
Priority: optional
Architecture: $ARCH
Maintainer: Kabe <kabe@example.org>
Depends: python3 (>= 3.8), python3-gi, gir1.2-gtk-3.0, python3-gi-cairo
Recommends: xfconf-query | plasma-apply-wallpaperimage | feh | swww
Homepage: https://github.com/kabe-app/kabe
Description: Kabe - fondos de pantalla en alta resolución para Linux
 Kabe (壁, "pared") descubre, descarga y aplica fondos de pantalla de alta
 calidad (4K, 5K, ultrawide) en cualquier escritorio Linux.
 .
 Indexa repositorios de GitHub con el API de árbol (sin clonarlos), busca en
 un índice local con tolerancia a errores de tipeo, y aplica el fondo en XFCE,
 GNOME, KDE, Cinnamon, MATE, LXQt, LXDE, Budgie y Deepin, además de feh,
 nitrogen, swww, hyprpaper y swaybg.
EOF

cat > "$PKG/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f /usr/share/icons/hicolor || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database /usr/share/applications || true
fi
exit 0
EOF
chmod +x "$PKG/DEBIAN/postinst"

cp "$ROOT/README.md" "$PKG/usr/share/doc/kabe/README.md" 2>/dev/null || true
if [ -d "$ROOT/LICENSE" ]; then cp "$ROOT/LICENSE" "$PKG/usr/share/doc/kabe/"; fi
if [ -d "$ROOT/po" ]; then
    mkdir -p "$PKG/usr/share/kabe/locale"
    for f in "$ROOT"/po/*.po; do
        [ -f "$f" ] || continue
        lang=$(basename "$f" .po)
        mkdir -p "$PKG/usr/share/kabe/locale/$lang/LC_MESSAGES"
        python3 "$ROOT/tools/msgfmt.py" "$f" "$PKG/usr/share/kabe/locale/$lang/LC_MESSAGES/kabe.mo" || true
    done
fi

OUT="$ROOT/dist/kabe_${VERSION}_${ARCH}.deb"
mkdir -p "$ROOT/dist"
dpkg-deb --build --root-owner-group "$PKG" "$OUT"
echo "→ $OUT"
