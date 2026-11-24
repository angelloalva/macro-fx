import os
import json
import urllib.request
from datetime import datetime, timezone, timedelta

STATE_FILE = "state.json"
INPUT_PROFE_FILE = "input_profe.json"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

def load_json(path, default=None):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def fetch_yahoo_price(symbol):
    """Consulta precio actual y variación diaria desde Yahoo Finance público."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            meta = data["chart"]["result"][0]["meta"]
            price = meta.get("regularMarketPrice")
            prev = meta.get("chartPreviousClose")
            if price and prev:
                arrow = "↑" if price >= prev else "↓"
                return round(price, 3), arrow
    except Exception as e:
        print(f"Error consultando {symbol}: {e}")
    return None, None

def update_volatiles(state):
    """Actualiza Capa 2 (VIX, Crudo WTI, Cobre) automáticamente."""
    mapping = {
        "VIX": ("^VIX", "$"),
        "Crudo": ("CL=F", "$"),
        "MPD": ("HG=F", "$")
    }
    for v in state["volatiles"]:
        if v["id"] in mapping:
            sym, prefix = mapping[v["id"]]
            price, arrow = fetch_yahoo_price(sym)
            if price is not None:
                v["valor"] = f"{prefix}{price}" if prefix == "$" and v["id"] != "VIX" else f"{price}"
                v["flecha"] = arrow
                if v["id"] == "VIX":
                    v["color"] = "verde" if price >= 25 else ("amarillo" if price >= 18 else "rojo")
                elif v["id"] == "MPD":
                    v["color"] = "verde" if arrow == "↑" else "rojo"

def analyze_profe_input(state, input_data):
    """Envía texto e imagen (base64) a Gemini 2.5 Flash para extraer puntos a vigilar y actualizar state.json."""
    if not GEMINI_API_KEY:
        print("Falta GEMINI_API_KEY en Secrets de GitHub.")
        return state

    texto = input_data.get("texto", "").strip()
    imagen_b64 = input_data.get("imagen_base64", "")

    if not texto and not imagen_b64:
        return state

    prompt = f"""
    Eres un analista cuantitativo de Forex. Tu tarea es leer el comentario diario y/o la imagen compartida por el profesor de trading y actualizar el JSON del tablero semanal.

    REGLAS METODOLÓGICAS ESTRICTAS:
    1. Escala de colores permitida: "verde", "amarillo", "blanco", "naranja", "rojo".
    2. Por defecto, los comentarios sobre noticias van en el campo "vigilancia_profe" del evento correspondiente y mantienen "nota": "Advertencia, no cambia sesgo".
    3. SOLO cambia el "color" de una divisa en el array "divisas" si el profesor indica explícitamente un cambio estructural de Capa 1 (política monetaria o dato macro extremo), y como máximo un escalón.
    4. Si la imagen contiene una pizarra, tabla o texto con niveles/umbrales (ej. "vigilar 0.3%", "si sale <2.6%"), extráelos y colócalos en "vigilancia_profe" y en "umbral_bajada" o "umbral_subida" del evento.
    5. Actualiza "ultima_nota_profe" con un resumen ejecutivo de 1-2 líneas de lo que indicó el profesor.
    6. Devuelve ÚNICAMENTE el JSON completo actualizado y válido, sin bloques markdown (```json) ni texto adicional.

    TEXTO DEL PROFESOR:
    {texto}

    ESTADO ACTUAL DEL TABLERO (JSON):
    {json.dumps(state, ensure_ascii=False)}
    """

    parts = [{"text": prompt}]
    if imagen_b64:
        if "," in imagen_b64:
            mime_part, b64_clean = imagen_b64.split(",", 1)
            mime_type = mime_part.split(":")[1].split(";")[0]
        else:
            b64_clean = imagen_b64
            mime_type = "image/jpeg"
        parts.append({
            "inline_data": {
                "mime_type": mime_type,
                "data": b64_clean
            }
        })

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={GEMINI_API_KEY}"
    payload = json.dumps({"contents": [{"parts": parts}]}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            res_json = json.loads(resp.read().decode("utf-8"))
            raw_text = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
            if raw_text.startswith("```"):
                raw_text = raw_text.strip("`").replace("json\n", "", 1).strip()
            updated_state = json.loads(raw_text)
            print("Tablero actualizado exitosamente con análisis de Gemini.")
            return updated_state
    except Exception as e:
        print(f"Error analizando con Gemini: {e}")
        state["ultima_nota_profe"] = f"[Error IA, nota guardada]: {texto[:120]}"
        return state

def main():
    state = load_json(STATE_FILE)
    if not state:
        return

    update_volatiles(state)

    input_data = load_json(INPUT_PROFE_FILE, {"procesado": True})
    if input_data and not input_data.get("procesado", True):
        state = analyze_profe_input(state, input_data)
        input_data["procesado"] = True
        input_data["imagen_base64"] = ""
        save_json(INPUT_PROFE_FILE, input_data)

    lima_tz = timezone(timedelta(hours=-5))
    state["ultima_actualizacion"] = datetime.now(lima_tz).strftime("%Y-%m-%d %H:%M Lima")
    save_json(STATE_FILE, state)

if __name__ == "__main__":
    main()
