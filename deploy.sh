#!/bin/bash
# =============================================================
#  YKAI Quant Core — Deploy Script para Oracle Cloud Free Tier
#  Ubuntu 22.04 LTS | ARM Ampere A1 (1 OCPU, 6 GB RAM)
#  Uso: bash deploy.sh
# =============================================================

set -e  # abortar si cualquier comando falla

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # sin color

BOT_USER="$(whoami)"
BOT_DIR="$HOME/BotTrader"
REPO_URL="https://github.com/Umi-otoko/Ykai-SystemTrading.git"
SERVICE_NAME="ykai-bot"
PYTHON_BIN="python3"
VENV_DIR="$BOT_DIR/.venv"

echo -e "${CYAN}"
echo "╔══════════════════════════════════════════════════════╗"
echo "║       YKAI Quant Core — Oracle Cloud Deploy          ║"
echo "║       TradingBot v2.9 | Binance USD-M Testnet        ║"
echo "╚══════════════════════════════════════════════════════╝"
echo -e "${NC}"

# ─────────────────────────────────────────────
# 1. Actualizar sistema e instalar dependencias
# ─────────────────────────────────────────────
echo -e "${YELLOW}[1/7] Actualizando sistema...${NC}"
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-pip python3-venv git curl

echo -e "${GREEN}      ✓ Sistema actualizado${NC}"

# ─────────────────────────────────────────────
# 2. Clonar o actualizar repositorio
# ─────────────────────────────────────────────
echo -e "${YELLOW}[2/7] Clonando repositorio...${NC}"
if [ -d "$BOT_DIR/.git" ]; then
    echo "      Repositorio ya existe — haciendo pull..."
    cd "$BOT_DIR"
    git pull origin main
else
    git clone "$REPO_URL" "$BOT_DIR"
    cd "$BOT_DIR"
fi
echo -e "${GREEN}      ✓ Repositorio listo en $BOT_DIR${NC}"

# ─────────────────────────────────────────────
# 3. Crear entorno virtual e instalar paquetes
# ─────────────────────────────────────────────
echo -e "${YELLOW}[3/7] Creando entorno virtual Python...${NC}"
cd "$BOT_DIR"
$PYTHON_BIN -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet ccxt pandas numpy requests python-dotenv
echo -e "${GREEN}      ✓ Paquetes instalados: ccxt pandas numpy requests python-dotenv${NC}"

# ─────────────────────────────────────────────
# 4. Crear archivo .env con credenciales
# ─────────────────────────────────────────────
echo -e "${YELLOW}[4/7] Configurando credenciales (.env)...${NC}"

if [ -f "$BOT_DIR/.env" ]; then
    echo -e "${CYAN}      .env ya existe. ¿Deseas reemplazarlo? (s/n):${NC}"
    read -r resp
    if [[ "$resp" != "s" && "$resp" != "S" ]]; then
        echo "      Manteniendo .env existente."
    else
        rm "$BOT_DIR/.env"
    fi
fi

if [ ! -f "$BOT_DIR/.env" ]; then
    echo ""
    echo -e "${CYAN}  Ingresa tus credenciales (no se muestran en pantalla):${NC}"
    echo ""

    read -p "  API_KEY_BINANCE    : " BINANCE_KEY
    read -sp "  API_SECRET_BINANCE : " BINANCE_SECRET
    echo ""
    read -p "  TELEGRAM_TOKEN     : " TG_TOKEN
    read -p "  TELEGRAM_CHAT_ID   : " TG_CHAT

    cat > "$BOT_DIR/.env" <<EOF
API_KEY_BINANCE=${BINANCE_KEY}
API_SECRET_BINANCE=${BINANCE_SECRET}
TELEGRAM_TOKEN=${TG_TOKEN}
TELEGRAM_CHAT_ID=${TG_CHAT}
EOF

    chmod 600 "$BOT_DIR/.env"
    echo -e "${GREEN}      ✓ .env creado con permisos 600 (solo lectura del propietario)${NC}"
fi

# ─────────────────────────────────────────────
# 5. Mostrar IP pública del servidor
# ─────────────────────────────────────────────
echo -e "${YELLOW}[5/7] Verificando IP pública del servidor...${NC}"
PUBLIC_IP=$(curl -s ifconfig.me 2>/dev/null || curl -s api.ipify.org 2>/dev/null || echo "No detectada")
echo -e "${GREEN}      ✓ IP pública: ${CYAN}${PUBLIC_IP}${NC}"
echo ""
echo -e "${YELLOW}  ⚠️  IMPORTANTE: Agrega esta IP en Binance API Management:${NC}"
echo -e "      https://www.binance.com/en/my/settings/api-management"
echo -e "      Sección: 'Restrict access to trusted IPs only' → ${CYAN}${PUBLIC_IP}${NC}"
echo ""

# ─────────────────────────────────────────────
# 6. Instalar servicio systemd
# ─────────────────────────────────────────────
echo -e "${YELLOW}[6/7] Instalando servicio systemd...${NC}"

# Generar el archivo .service con rutas reales
sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null <<EOF
[Unit]
Description=YKAI Quant Core TradingBot v2.9
Documentation=https://github.com/Umi-otoko/Ykai-SystemTrading
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${BOT_USER}
WorkingDirectory=${BOT_DIR}
ExecStart=${VENV_DIR}/bin/python ${BOT_DIR}/TradingBot_v2.py
Restart=always
RestartSec=30
StandardOutput=append:${BOT_DIR}/trading.log
StandardError=append:${BOT_DIR}/trading.log
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE_NAME}
echo -e "${GREEN}      ✓ Servicio ${SERVICE_NAME} registrado y habilitado para autostart${NC}"

# ─────────────────────────────────────────────
# 7. Arrancar el bot
# ─────────────────────────────────────────────
echo -e "${YELLOW}[7/7] Iniciando el bot...${NC}"
sudo systemctl start ${SERVICE_NAME}
sleep 3

STATUS=$(sudo systemctl is-active ${SERVICE_NAME} 2>/dev/null || echo "desconocido")
if [ "$STATUS" = "active" ]; then
    echo -e "${GREEN}      ✓ Bot corriendo — estado: ${STATUS}${NC}"
else
    echo -e "${RED}      ✗ Bot no arrancó — estado: ${STATUS}${NC}"
    echo "      Ver logs: sudo journalctl -u ${SERVICE_NAME} -n 50"
fi

# ─────────────────────────────────────────────
# Resumen final
# ─────────────────────────────────────────────
echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════════╗"
echo -e "║                  DEPLOY COMPLETADO                  ║"
echo -e "╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${GREEN}📊 Estado del bot:${NC}     sudo systemctl status ${SERVICE_NAME}"
echo -e "  ${GREEN}📜 Logs en tiempo real:${NC} tail -f ${BOT_DIR}/trading.log"
echo -e "  ${GREEN}🔄 Actualizar bot:${NC}      bash ${BOT_DIR}/update.sh"
echo -e "  ${GREEN}⏹  Detener bot:${NC}         sudo systemctl stop ${SERVICE_NAME}"
echo -e "  ${GREEN}▶️  Iniciar bot:${NC}          sudo systemctl start ${SERVICE_NAME}"
echo -e "  ${GREEN}🔁 Reiniciar bot:${NC}        sudo systemctl restart ${SERVICE_NAME}"
echo ""
echo -e "  ${YELLOW}IP del servidor: ${CYAN}${PUBLIC_IP}${NC}"
echo -e "  ${YELLOW}Recuerda agregar esta IP en Binance → API Management${NC}"
echo ""
