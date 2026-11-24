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
    """Envía texto y múltiples imágenes (base64) a Gemini 2.5 Flash para actualizar state.json."""
    if not GEMINI_API_KEY:
        print("ERROR: Falta GEMINI_API_KEY en Secrets de GitHub.")
        return state, False

    texto = input_data.get("texto", "").strip()
    imagenes = input_data.get("imagenes_base64", [])
    if not imagenes and input_data.get("imagen_base64"):
        imagenes = [input_data.get("imagen_base64")]

    if not texto and not imagenes:
        return state, True

    prompt = f"""
    Eres un analista cuantitativo de Forex. Lee el comentario diario y TODAS las imágenes/capturas compartidas por el profesor de trading y actualiza el JSON del tablero semanal.

    REGLAS DE ACTUALIZACIÓN:
    1. Escala de colores permitida: "verde", "amarillo", "blanco", "naranja", "rojo".
    2. Actualiza "ultima_nota_profe" con un resumen ejecutivo claro (2-3 líneas) integrando lo que dicen el texto y todas las imágenes (pizarras, gráficos, noticias).
    3. Si las imágenes o el texto indican cambios de sesgo o colores en la columna Pre Semana (ej. pizarras de divisas con colores verde/amarillo/blanco/naranja/rojo, o divisas favorecidas como GBP o USD), actualiza el "color", "tags" y el "motivo" de esas divisas en el array "divisas".
    4. Si mencionan puntos a vigilar sobre eventos de la semana, añádelos en "vigilancia_profe" del evento correspondiente manteniendo "nota": "Advertencia, no cambia sesgo" salvo que indique cambio estructural.
    5. Devuelve ÚNICAMENTE el JSON completo actualizado y válido, sin bloques markdown (```json) ni texto adicional.

    TEXTO DEL PROFESOR:
    {texto}

    ESTADO ACTUAL DEL TABLERO (JSON):
    {json.dumps(state, ensure_ascii=False)}
    """

    parts = [{"text": prompt}]
    for img_b64 in imagenes:
        if not img_b64:
            continue
        if "," in img_b64:
            mime_part, b64_clean = img_b64.split(",", 1)
            mime_type = mime_part.split(":")[1].split(";")[0]
        else:
            b64_clean = img_b64
            mime_type = "image/jpeg"
        parts.append({
            "inline_data": {
                "mime_type": mime_type,
                "data": b64_clean
            }
        })

    url = f"[https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=](https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=){GEMINI_API_KEY}"
    payload = json.dumps({"contents": [{"parts": parts}]}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            res_json = json.loads(resp.read().decode("utf-8"))
            raw_text = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
            if raw_text.startswith("```"):
                raw_text = raw_text.strip("`").replace("json\n", "", 1).strip()
            updated_state = json.loads(raw_text)
            print(f"Tablero actualizado exitosamente con {len(imagenes)} imágenes y texto.")
            return updated_state, True
    except Exception as e:
        print(f"Error analizando con Gemini: {e}")
        state["ultima_nota_profe"] = f"[Error API Gemini: {str(e)[:100]}] {texto[:150]}"
        return state, True

def main():
    state = load_json(STATE_FILE)
    if not state:
        return

    update_volatiles(state)

    input_data = load_json(INPUT_PROFE_FILE, {"procesado": True})
    if input_data and not input_data.get("procesado", True):
        state, ok = analyze_profe_input(state, input_data)
        if ok:
            input_data["procesado"] = True
            input_data["imagenes_base64"] = []
            input_data.pop("imagen_base64", None)
            save_json(INPUT_PROFE_FILE, input_data)

    lima_tz = timezone(timedelta(hours=-5))
    state["ultima_actualizacion"] = datetime.now(lima_tz).strftime("%Y-%m-%d %H:%M Lima")
    save_json(STATE_FILE, state)

if __name__ == "__main__":
    main()
