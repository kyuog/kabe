#!/bin/sh
# Construye la AppImage de Kabe.
#
#   ./packaging/build_appimage.sh
#
# Requiere appimagetool (https://github.com/AppImage/AppImageKit/releases).
# Si no está disponible, el script deja el AppDir listo en dist/AppDir y lo
# avisa: se puede ejecutar con ./dist/AppDir/AppRun.
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="$(grep -oP '__version__ = "\K[^"]+' "$ROOT/kabe/__init__.py")"
APPDIR="$ROOT/dist/AppDir"
APPDIR="$APPDIR"

echo "Kabe $VERSION → AppDir"

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "$APPDIR/usr/lib/kabe" "$APPDIR/usr/share/kabe" \
         "$APPDIR/usr/share/applications" "$APPDIR/usr/share/icons/hicolor"

cp -r "$ROOT/kabe" "$APPDIR/usr/lib/kabe/"
find "$APPDIR/usr/lib/kabe" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
cp -r "$ROOT/share/." "$APPDIR/usr/share/kabe/" 2>/dev/null || true
cp "$ROOT/kabe-icon.svg" "$ROOT/kabe-logo.svg" "$APPDIR/usr/share/kabe/" 2>/dev/null || true
cp "$ROOT/desktop/kabe.desktop" "$APPDIR/"
cp "$ROOT/desktop/kabe.desktop" "$APPDIR/usr/share/applications/"
cp "$ROOT/packaging/appimage/AppRun" "$APPDIR/AppRun"
chmod +x "$APPDIR/AppRun"

for size in 16 24 32 48 64 128 256; do
    src="$ROOT/share/icons/hicolor/${size}x${size}/apps/kabe.png"
    [ -f "$src" ] || continue
    mkdir -p "$APPDIR/usr/share/icons/hicolor/${size}x${size}/apps"
    cp "$src" "$APPDIR/usr/share/icons/hicolor/${size}x${size}/apps/"
done
for kind in scalable symbolic; do
    src="$ROOT/share/icons/hicolor/$kind/apps"
    [ -d "$src" ] || continue
    mkdir -p "$APPDIR/usr/share/icons/hicolor/$kind/apps"
    cp "$src"/* "$APPDIR/usr/share/icons/hicolor/$kind/apps/" 2>/dev/null || true
done

cat > "$APPDIR/kabe.png" <<'EOF'
EOF
cp "$ROOT/share/icons/hicolor/256x256/apps/kabe.png" "$APPDIR/kabe.png"

if command -v appimagetool >/dev/null 2>&1; then
    OUT="$ROOT/dist/kabe-${VERSION}-x86_64.AppImage"
    appimagetool "$APPDIR" "$OUT"
    echo "→ $OUT"
else
    echo "appimagetool no está instalado."
    echo "AppDir listo en $APPDIR (ejecutable con ./dist/AppDir/AppRun)."
fi
