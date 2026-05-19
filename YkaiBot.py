import ccxt
import requests
import pandas as pd
import time
import os

# Parámetros de la Sonda
ACTIVOS = ['SOL/USDT', 'BTC/USDT']  
TIMEFRAME = '5m'       
INTERVALO_SCAN = 15    

# Parámetros Financieros (Simulados)
CAPITAL_TOTAL = 50.0  
RIESGO_PORCENTAJE = 0.02  
APALANCAMIENTO = 10

exchange = ccxt.binance({
    'apiKey': API_KEY_BINANCE,
    'secret': API_SECRET_BINANCE,
    'enableRateLimit': True,
    'options': {
        'defaultType': 'future', 
        'fetchCurrencies': False, 
        'adjustForTimeDifference': True, 
    }
})

# [!] NUEVO: MEMORIA DE SIMULACIÓN (PAPER TRADING)
simulacion_activa = {
    'SOL/USDT': {'activa': False, 'accion': '', 'precio_entrada': 0, 'sl': 0, 'tp': 0},
    'BTC/USDT': {'activa': False, 'accion': '', 'precio_entrada': 0, 'sl': 0, 'tp': 0}
}

# ==========================================
# 2. MOTORES DE REGISTRO
# ==========================================
def registrar_datos_crudos(simbolo, precio, rsi, ema50, ema200):
    fecha_hora = time.strftime('%Y-%m-%d %H:%M:%S')
    file_name = "mercado_historico.csv"
    es_nuevo = not os.path.exists(file_name)
    with open(file_name, "a") as f:
        if es_nuevo: f.write("Fecha,Simbolo,Precio,RSI,EMA50,EMA200\n")
        f.write(f"{fecha_hora},{simbolo},{precio},{rsi},{ema50},{ema200}\n")

def registrar_señal_simulada(simbolo, accion, precio, sl, tp):
    fecha_hora = time.strftime('%Y-%m-%d %H:%M:%S')
    file_name = "ykai_database.csv"
    es_nuevo = not os.path.exists(file_name)
    with open(file_name, "a") as f:
        if es_nuevo: f.write("Fecha,Accion,Simbolo,Precio,SL,TP\n")
        f.write(f"{fecha_hora},{accion},{simbolo},{precio},{sl},{tp}\n")

# ==========================================
# 3. TELEMETRÍA Y CÁLCULOS
# ==========================================
def enviar_telegram(mensaje: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "Markdown"}
    try: requests.post(url, json=payload)
    except: pass

def analizar_mercado(simbolo: str):
    try:
        velas = exchange.fetch_ohlcv(simbolo, TIMEFRAME, limit=250)
        df = pd.DataFrame(velas, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        df['ema_200'] = df['close'].ewm(span=200, adjust=False).mean()
        df['ema_50'] = df['close'].ewm(span=50, adjust=False).mean()
        
        delta = df['close'].diff()
        up = delta.clip(lower=0)
        down = -1 * delta.clip(upper=0)
        ema_up = up.ewm(alpha=1/14, adjust=False).mean()
        ema_down = down.ewm(alpha=1/14, adjust=False).mean()
        df['rsi'] = 100 - (100 / (1 + (ema_up / ema_down)))
        
        v = df.iloc[-1]
        v_ant = df.iloc[-2]
        precio = v['close']
        
        registrar_datos_crudos(simbolo, precio, v['rsi'], v['ema_50'], v['ema_200'])
        
        # [!] GESTIÓN DE LA OPERACIÓN EN CURSO
        sim = simulacion_activa[simbolo]
        if sim['activa']:
            print(f"[*] {simbolo} | ${precio:.2f} | OPERACIÓN {sim['accion']} EN CURSO...")
            
            if sim['accion'] == 'LONG':
                if precio <= sim['sl']:
                    enviar_telegram(f"🔴 **STOP LOSS TOCADO** en `{simbolo}`\nPerdida controlada. Radar reiniciado.")
                    sim['activa'] = False
                elif precio >= sim['tp']:
                    enviar_telegram(f"🟢 **TAKE PROFIT ALCANZADO** en `{simbolo}`\n¡Ganancia asegurada! Radar reiniciado.")
                    sim['activa'] = False
                    
            elif sim['accion'] == 'SHORT':
                if precio >= sim['sl']:
                    enviar_telegram(f"🔴 **STOP LOSS TOCADO** en `{simbolo}`\nPerdida controlada. Radar reiniciado.")
                    sim['activa'] = False
                elif precio <= sim['tp']:
                    enviar_telegram(f"🟢 **TAKE PROFIT ALCANZADO** en `{simbolo}`\n¡Ganancia asegurada! Radar reiniciado.")
                    sim['activa'] = False
            return # Si la operación sigue viva, corta la función aquí para no abrir otra.

        print(f"[*] {simbolo} | ${precio:.2f} | RSI: {v['rsi']:.1f} | EMA50: {v['ema_50']:.1f}")

        # Lógica de Estrategia (Nuevos ratios 1:1)
        if (precio > v['ema_200'] and v['close'] > v['ema_50'] and v_ant['close'] <= v_ant['ema_50'] and v['rsi'] < 60):
            sl = v['low'] * 0.998 # Stop Loss más ajustado
            tp = precio + (precio - sl) # Take Profit 1:1
            
            # Guardamos la operación en la memoria local
            simulacion_activa[simbolo] = {'activa': True, 'accion': 'LONG', 'precio_entrada': precio, 'sl': sl, 'tp': tp}
            
            registrar_señal_simulada(simbolo, "LONG", precio, sl, tp)
            enviar_telegram(f"👻 **SIMULACIÓN LONG**\n`{simbolo}` | Entrada: `${precio}`\nTarget: `${tp:.2f}`")
            
        elif (precio < v['ema_200'] and v['close'] < v['ema_50'] and v_ant['close'] >= v_ant['ema_50'] and v['rsi'] > 40):
            sl = v['high'] * 1.002 # Stop Loss más ajustado
            tp = precio - (sl - precio) # Take Profit 1:1
            
            # Guardamos la operación en la memoria local
            simulacion_activa[simbolo] = {'activa': True, 'accion': 'SHORT', 'precio_entrada': precio, 'sl': sl, 'tp': tp}
            
            registrar_señal_simulada(simbolo, "SHORT", precio, sl, tp)
            enviar_telegram(f"👻 **SIMULACIÓN SHORT**\n`{simbolo}` | Entrada: `${precio}`\nTarget: `${tp:.2f}`")

    except Exception as e:
        print(f"[-] Error en {simbolo}: {e}")

# ==========================================
# 4. EJECUCIÓN CONTINUA
# ==========================================
def main():
    print("========================================")
    print("YKAI QUANT CORE v3.0 - PRECISION SIMULATOR")
    print(f"Objetivos: {ACTIVOS} | Modo: PAPER TRADING")
    print("========================================")
    
    while True:
        for activo in ACTIVOS:
            analizar_mercado(activo)
        time.sleep(INTERVALO_SCAN)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] Simulador desactivado.")
