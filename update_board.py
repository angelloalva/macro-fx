import os
import re
import json
import urllib.request
from datetime import datetime, timezone, timedelta

STATE_FILE = "state.json"
INPUT_PROFE_FILE = "input_profe.json"
# Limpia espacios, comillas o corchetes accidentales en el Secret de GitHub
GEMINI_API_KEY = re.sub(r'[\[\]\s"\']', '', os.environ.get("GEMINI_API_KEY", ""))

def clean_url(u):
    return u.replace("[", "").replace("]", "").strip()

def load_json(path, default=None):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def fetch_yahoo_price(symbol):
    url = clean_url("https://query1.finance.yahoo.com/v8/finance/chart/" + symbol + "?interval=1d&range=2d")
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

def analyze_and_fetch_data(state, input_data=None):
    if not GEMINI_API_KEY:
        print("ERROR: Falta GEMINI_API_KEY en Secrets de GitHub.")
        return state, False

    texto = (input_data or {}).get("texto", "").strip()
    imagenes = (input_data or {}).get("imagenes_base64", [])
    if not imagenes and (input_data or {}).get("imagen_base64"):
        imagenes = [input_data.get("imagen_base64")]

    lima_tz = timezone(timedelta(hours=-5))
    fecha_actual = datetime.now(lima_tz).strftime("%Y-%m-%d %H:%M Lima")

    prompt = f"""
    Eres un analista macroeconómico de Forex. Fecha/hora actual: {fecha_actual}.
    Analiza las imágenes/notas del profesor (si las hay) Y utiliza Google Search para verificar las cifras reales ya publicadas de los eventos macroeconómicos de esta semana (Semana {state.get("semana", "")}), así como la hora exacta de publicación en UTC de las noticias próximas.

    REGLAS OBLIGATORIAS:
    1. HORA DE PUBLICACIÓN ("fecha_utc"):
       - Para cada noticia en "eventos" con "estado": "proxima", incluye su fecha y hora oficial de publicación en UTC en "fecha_utc" con formato "YYYY-MM-DD HH:MM".
    2. CIFRA REAL EXACTA ("resultado"):
       - Para toda noticia en "eventos" que ya se haya publicado (incluidos los PMIs del lunes si aún no tienen cifra), busca y escribe el número exacto publicado en "resultado" (ej. "Real: Manuf 52.4 / Serv 51.8 vs 52.1-53.1 esp.") y mantén "estado": "publicada".
    3. NOTICIAS PRÓXIMAS ("estado": "proxima"):
       - Mantén "color": "blanco" y "resultado": null hasta que salga el dato real.
    4. FILTRO DE RELEVANCIA Y COLORES ("verde", "amarillo", "blanco", "naranja", "rojo"):
       - Si sale dentro de expectación: "color": "blanco" en bitácora y NO lo agregues a "riesgos_volatilidad".
       - Si es mixto o pista adelantada: "amarillo" o "naranja".
       - Si sorprende fuera de expectación: "verde" o "rojo", añádelo AL FINAL de "riesgos_volatilidad" y marca "muy_relevante": true solo si cambia la postura del Banco Central.
    5. EXPLICACIÓN DEL IMPACTO ("analisis_impacto"):
       - Explica en 2-3 líneas por qué lleva ese color y su efecto en la divisa y su Banco Central.
    6. PIZARRA DERECHA ("divisas" y "volatiles"):
       - Sincroniza colores y etiquetas (RF, V, C.R, (oil)) con las imágenes o indicaciones del profesor.
    7. Actualiza "ultima_nota_profe" con un resumen ejecutivo limpio (2-3 líneas) de lo analizado.
    8. Devuelve ÚNICAMENTE el JSON completo válido, sin bloques markdown (```json) ni texto adicional.

    TEXTO DEL PROFESOR:
    {texto if texto else "Busca y completa las cifras reales exactas de las noticias ya publicadas esta semana y verifica próximas."}

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

    api_endpoint = "https" + "://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"    payload_dict = {
        "contents": [{"parts": parts}],
        "tools": [{"google_search": {}}]
    }
    payload = json.dumps(payload_dict).encode("utf-8")
    req = urllib.request.Request(
        url=api_endpoint,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_API_KEY
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=75) as resp:
            res_json = json.loads(resp.read().decode("utf-8"))
            raw_text = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
            if raw_text.startswith("```"):
                raw_text = raw_text.strip("`").replace("json\n", "", 1).strip()
            updated_state = json.loads(raw_text)
            print("Tablero actualizado con cifras reales y análisis.")
            return updated_state, True
    except Exception as e:
        print(f"Error en Gemini: {e}")
        if texto:
            state["ultima_nota_profe"] = f"[Error API: {str(e)[:100]}] {texto[:150]}"
        return state, True

def main():
    state = load_json(STATE_FILE)
    if not state:
        return

    update_volatiles(state)

    input_data = load_json(INPUT_PROFE_FILE, {"procesado": True})
    hay_input = input_data and not input_data.get("procesado", True)

    ahora_utc = datetime.now(timezone.utc)
    hay_noticia_lista = False
    for ev in state.get("eventos", []):
        if ev.get("estado") == "proxima" and ev.get("fecha_utc"):
            try:
                dt = datetime.strptime(ev["fecha_utc"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
                if dt + timedelta(minutes=10) <= ahora_utc:
                    hay_noticia_lista = True
                    break
            except Exception:
                pass
        elif ev.get("estado") == "publicada" and not re.search(r"\d", str(ev.get("resultado") or "")):
            hay_noticia_lista = True
            break

    if hay_input or hay_noticia_lista:
        state, ok = analyze_and_fetch_data(state, input_data if hay_input else None)
        if hay_input and ok:
            input_data["procesado"] = True
            input_data["imagenes_base64"] = []
            input_data.pop("imagen_base64", None)
            save_json(INPUT_PROFE_FILE, input_data)

    lima_tz = timezone(timedelta(hours=-5))
    state["ultima_actualizacion"] = datetime.now(lima_tz).strftime("%Y-%m-%d %H:%M Lima")
    save_json(STATE_FILE, state)

if __name__ == "__main__":
    main()
