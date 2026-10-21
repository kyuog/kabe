#!/bin/sh
# Instalador sencillo de Kabe (funciona en cualquier distribución Linux).
#
#   sudo ./packaging/install.sh            → instala en /usr/local
#   ./packaging/install.sh --user         → instala en ~/.local (sin sudo)
#
set -e

PREFIX="/usr/local"
BINDIR="$PREFIX/bin"
LIBDIR="$PREFIX/lib/kabe"
DATADIR="$PREFIX/share/kabe"
USER_MODE=0

for arg in "$@"; do
    case "$arg" in
        --user) USER_MODE=1 ;;
        --prefix=*) PREFIX="${arg#--prefix=}" ;;
        --help|-h)
            echo "Uso: $0 [--user] [--prefix=/ruta]"
            exit 0 ;;
    esac
done

if [ "$USER_MODE" = "1" ]; then
    BINDIR="$HOME/.local/bin"
    LIBDIR="$HOME/.local/lib/kabe"
    DATADIR="$HOME/.local/share/kabe"
    ICON_DIR="$HOME/.local/share/icons/hicolor"
    APP_DIR="$HOME/.local/share/applications"
else
    ICON_DIR="/usr/share/icons/hicolor"
    APP_DIR="/usr/share/applications"
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "Kabe → $PREFIX"

mkdir -p "$BINDIR" "$LIBDIR" "$DATADIR" "$ICON_DIR" "$APP_DIR"

# Código Python
rm -rf "$LIBDIR/kabe"
cp -r "$ROOT/kabe" "$LIBDIR/kabe"
find "$LIBDIR" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true

# Recursos (logo, catálogo de repositorios, traducciones)
mkdir -p "$DATADIR/share"
cp -r "$ROOT/share/." "$DATADIR/share/" 2>/dev/null || true
if [ -f "$ROOT/kabe-icon.svg" ]; then cp "$ROOT/kabe-icon.svg" "$DATADIR/"; fi
if [ -f "$ROOT/kabe-logo.svg" ]; then cp "$ROOT/kabe-logo.svg" "$DATADIR/"; fi

# Lanzador
cat > "$BINDIR/kabe" <<EOF
#!/bin/sh
PYTHONPATH="$LIBDIR\${PYTHONPATH:+:\$PYTHONPATH}" exec python3 -m kabe "\$@"
EOF
chmod +x "$BINDIR/kabe"

# Entrada de menú
sed "s|^Exec=kabe %F|Exec=$BINDIR/kabe %F|" "$ROOT/desktop/kabe.desktop" > "$APP_DIR/kabe.desktop"
chmod +x "$APP_DIR/kabe.desktop"

# Iconos
for size in 16 24 32 48 64 128 256; do
    src="$ROOT/share/icons/hicolor/${size}x${size}/apps/kabe.png"
    [ -f "$src" ] || continue
    mkdir -p "$ICON_DIR/${size}x${size}/apps"
    cp "$src" "$ICON_DIR/${size}x${size}/apps/kabe.png"
done
for kind in scalable symbolic; do
    src="$ROOT/share/icons/hicolor/$kind/apps"
    [ -d "$src" ] || continue
    mkdir -p "$ICON_DIR/$kind/apps"
    cp "$src"/* "$ICON_DIR/$kind/apps/" 2>/dev/null || true
done

# Caché de iconos (si está disponible)
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f "$ICON_DIR" 2>/dev/null || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APP_DIR" 2>/dev/null || true
fi

echo "Instalado. Ejecuta «kabe» para abrir la aplicación."
