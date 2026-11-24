import os
import json
import urllib.request
from datetime import datetime, timezone, timedelta

STATE_FILE = "state.json"
INPUT_PROFE_FILE = "input_profe.json"
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()

def load_json(path, default=None):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def fetch_yahoo_price(symbol):
    url = "https://query1.finance.yahoo.com/v8/finance/chart/" + symbol + "?interval=1d&range=2d"
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
    mapping = {
        "VIX": ("^VIX", ""),
        "Crudo": ("CL=F", "$"),
        "MPD": ("HG=F", "$")
    }
    for v in state["volatiles"]:
        if v["id"] in mapping:
            sym, prefix = mapping[v["id"]]
            price, arrow = fetch_yahoo_price(sym)
            if price is not None:
                v["valor"] = f"{prefix}{price}"
                v["flecha"] = arrow

def analyze_profe_input(state, input_data):
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
    Eres un analista cuantitativo de Forex. Analiza el mensaje y TODAS las imágenes enviadas por el profesor (pizarras de sesgos, capturas de resultados o tablas de "LÍMITES DE EXPECTACIÓN / Rango de Consenso") para actualizar el JSON del tablero.

    REGLAS DE ACTUALIZACIÓN:
    1. Colores permitidos únicamente: "verde", "amarillo", "blanco", "naranja", "rojo".
    2. Si alguna imagen es una tabla de "LÍMITES DE EXPECTACIÓN / Rango de Consenso":
       - Extrae TODAS las noticias relevantes de cada día (Lunes a Viernes) con su divisa, título y rango exacto en "rango_expectacion".
       - Coloca "estado": "proxima" para noticias futuras y "estado": "publicada" para días/noticias que ya salieron o tienen resultado.
    3. Si el profesor reporta el resultado de una noticia que ya salió:
       - Cambia su "estado" a "publicada" en "eventos", anota el dato real en "resultado" (comparándolo con su "rango_expectacion") y agrégalo también en "riesgos_volatilidad" si está en la pizarra del día.
    4. Sincroniza "riesgos_volatilidad", "divisas" ("Pre Semana") y "volatiles" con lo que muestre la pizarra o diga el profesor.
    5. Actualiza "ultima_nota_profe" con un resumen ejecutivo (2-3 líneas).
    6. Devuelve ÚNICAMENTE el JSON completo válido, sin bloques markdown (```json) ni texto extra.

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

    api_endpoint = "[https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=](https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=)" + GEMINI_API_KEY
    payload = json.dumps({"contents": [{"parts": parts}]}).encode("utf-8")
    req = urllib.request.Request(api_endpoint, data=payload, headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            res_json = json.loads(resp.read().decode("utf-8"))
            raw_text = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
            if raw_text.startswith("```"):
                raw_text = raw_text.strip("`").replace("json\n", "", 1).strip()
            updated_state = json.loads(raw_text)
            print("Tablero actualizado exitosamente con Gemini.")
            return updated_state, True
    except Exception as e:
        print(f"Error analizando con Gemini: {e}")
        state["ultima_nota_profe"] = f"[Error API Gemini: {str(e)[:120]}] {texto[:150]}"
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
