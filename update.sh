#!/bin/bash
# =============================================================
#  YKAI Quant Core — Script de actualización
#  Uso: bash update.sh
#  Hace git pull y reinicia el servicio con la nueva versión
# =============================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

BOT_DIR="$HOME/BotTrader"
SERVICE_NAME="ykai-bot"
VENV_DIR="$BOT_DIR/.venv"

echo -e "${CYAN}[YKAI] Actualizando bot desde GitHub...${NC}"

# ─────────────────────────────────────────────
# 1. Verificar que el directorio existe
# ─────────────────────────────────────────────
if [ ! -d "$BOT_DIR/.git" ]; then
    echo -e "${RED}Error: $BOT_DIR no es un repositorio git.${NC}"
    echo "Ejecuta deploy.sh primero."
    exit 1
fi

cd "$BOT_DIR"

# ─────────────────────────────────────────────
# 2. Mostrar estado actual antes de actualizar
# ─────────────────────────────────────────────
COMMIT_ANTES=$(git rev-parse --short HEAD)
echo -e "  Commit actual : ${YELLOW}${COMMIT_ANTES}${NC}"

# ─────────────────────────────────────────────
# 3. Pull de cambios
# ─────────────────────────────────────────────
echo -e "${YELLOW}[1/3] Descargando cambios...${NC}"
git fetch origin main
COMMITS_NUEVOS=$(git rev-list HEAD..origin/main --count)

if [ "$COMMITS_NUEVOS" = "0" ]; then
    echo -e "${GREEN}      ✓ Ya estás en la versión más reciente (${COMMIT_ANTES}).${NC}"
    echo ""
    echo -e "  Estado del servicio: ${CYAN}$(sudo systemctl is-active ${SERVICE_NAME})${NC}"
    exit 0
fi

echo -e "  ${COMMITS_NUEVOS} commit(s) nuevo(s) disponibles"
git pull origin main

COMMIT_NUEVO=$(git rev-parse --short HEAD)
echo -e "${GREEN}      ✓ Actualizado: ${YELLOW}${COMMIT_ANTES}${GREEN} → ${CYAN}${COMMIT_NUEVO}${NC}"

# ─────────────────────────────────────────────
# 4. Actualizar dependencias Python si cambiaron
# ─────────────────────────────────────────────
echo -e "${YELLOW}[2/3] Verificando dependencias Python...${NC}"
source "$VENV_DIR/bin/activate"
pip install --quiet --upgrade ccxt pandas numpy requests python-dotenv
echo -e "${GREEN}      ✓ Dependencias OK${NC}"

# ─────────────────────────────────────────────
# 5. Reiniciar el servicio
# ─────────────────────────────────────────────
echo -e "${YELLOW}[3/3] Reiniciando servicio...${NC}"
sudo systemctl restart "${SERVICE_NAME}"
sleep 3

STATUS=$(sudo systemctl is-active "${SERVICE_NAME}" 2>/dev/null || echo "desconocido")
if [ "$STATUS" = "active" ]; then
    echo -e "${GREEN}      ✓ Bot reiniciado — estado: ${STATUS}${NC}"
else
    echo -e "${RED}      ✗ Error al reiniciar — estado: ${STATUS}${NC}"
    echo "      Ver logs: sudo journalctl -u ${SERVICE_NAME} -n 50"
    exit 1
fi

# ─────────────────────────────────────────────
# Resumen
# ─────────────────────────────────────────────
echo ""
echo -e "${CYAN}  Actualización completada ✓${NC}"
echo -e "  Versión anterior : ${YELLOW}${COMMIT_ANTES}${NC}"
echo -e "  Versión actual   : ${CYAN}${COMMIT_NUEVO}${NC}"
echo ""
echo -e "  ${GREEN}📜 Ver logs:${NC} tail -f ${BOT_DIR}/trading.log"
echo ""

# Mostrar últimas 10 líneas del log para confirmar que arrancó bien
echo -e "${CYAN}  Últimas líneas del log:${NC}"
echo "  ──────────────────────────────────────────"
tail -n 10 "${BOT_DIR}/trading.log" 2>/dev/null | sed 's/^/  /'
echo "  ──────────────────────────────────────────"
echo ""
