import os
import json
import urllib.request
from datetime import datetime, timezone, timedelta

STATE_FILE = "state.json"
INPUT_PROFE_FILE = "input_profe.json"
CRON_FILE = ".github/workflows/cron.yml"
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

def sync_cron_schedule(state):
    """Genera disparadores cron exactos (hora de publicación UTC + 10 minutos) solo para noticias pendientes."""
    cron_lines = []
    seen = set()
    now_utc = datetime.now(timezone.utc)

    for ev in state.get("eventos", []):
        if ev.get("estado") != "proxima":
            continue
        fecha_utc_str = ev.get("fecha_utc")  # Ej: "2026-11-25 00:30"
        if not fecha_utc_str:
            continue
        try:
            dt = datetime.strptime(fecha_utc_str, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
            run_dt = dt + timedelta(minutes=10)
            if run_dt > now_utc:
                expr = f"{run_dt.minute} {run_dt.hour} {run_dt.day} {run_dt.month} *"
                if expr not in seen:
                    seen.add(expr)
                    cron_lines.append(f"    - cron: '{expr}' # [{ev.get('divisa')}] {ev.get('titulo')}")
        except Exception as e:
            print(f"Error parseando fecha_utc {fecha_utc_str}: {e}")

    schedule_block = "  schedule:\n" + ("\n".join(cron_lines) if cron_lines else "    # Sin noticias pendientes esta semana")

    yml_content = f"""name: Actualizar Tablero Macro FX

on:
  push:
    paths:
      - 'input_profe.json'
  workflow_dispatch:
{schedule_block}

permissions:
  contents: write

jobs:
  update:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repositorio
        uses: actions/checkout@v4

      - name: Configurar Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Ejecutar analizador y volátiles
        env:
          GEMINI_API_KEY: ${{{{ secrets.GEMINI_API_KEY }}}}
        run: python update_board.py

      - name: Guardar cambios en state.json y cron.yml
        run: |
          git config --local user.email "action@github.com"
          git config --local user.name "GitHub Action"
          git add state.json input_profe.json .github/workflows/cron.yml
          git diff --quiet && git diff --staged --quiet || git commit -m "Actualización automática Macro FX [skip ci]"
          git push
"""
    os.makedirs(os.path.dirname(CRON_FILE), exist_ok=True)
    with open(CRON_FILE, "w", encoding="utf-8") as f:
        f.write(yml_content)
    print(f"Cron actualizado con {len(cron_lines)} tareas programadas (+10 min post-noticia).")

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
       - Para cada noticia en "eventos" con "estado": "proxima", incluye su fecha y hora oficial de publicación en UTC en el campo "fecha_utc" con formato exacto "YYYY-MM-DD HH:MM" (por ejemplo, 19:30 Lima del martes es "2026-11-25 00:30" UTC; 08:30 Lima del miércoles es "2026-11-25 13:30" UTC). Esto programa el cron automáticamente 10 minutos después.
    2. CIFRA REAL EXACTA ("resultado"):
       - Para toda noticia en "eventos" que ya se haya publicado, escribe el número exacto publicado en "resultado" (ej. "Real: 4.8% vs 4.7%-4.8% esp.") y cambia su "estado" a "publicada".
    3. NOTICIAS PRÓXIMAS ("estado": "proxima"):
       - Mantén "color": "blanco" y "resultado": null hasta que salga el dato real.
    4. FILTRO DE RELEVANCIA Y COLORES ("verde", "amarillo", "blanco", "naranja", "rojo"):
       - Si sale dentro de expectación: "color": "blanco" en bitácora y NO lo agregues a "riesgos_volatilidad".
       - Si es mixto o pista adelantada: "amarillo" o "naranja".
       - Si sorprende fuera de expectación: "verde" o "rojo", añádelo AL FINAL de "riesgos_volatilidad" (debajo de las existentes) y marca "muy_relevante": true solo si cambia la postura del Banco Central.
    5. EXPLICACIÓN DEL IMPACTO ("analisis_impacto"):
       - Explica en 2-3 líneas por qué lleva ese color y su efecto en la divisa y su Banco Central.
    6. PIZARRA DERECHA ("divisas" y "volatiles"):
       - Sincroniza colores y etiquetas (RF, V, C.R, (oil)) con las imágenes o indicaciones del profesor.
    7. Devuelve ÚNICAMENTE el JSON completo válido, sin bloques markdown (```json) ni texto adicional.

    TEXTO DEL PROFESOR:
    {texto if texto else "Verifica resultados macro publicados recientemente y horarios UTC de próximas noticias."}

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
    payload_dict = {
        "contents": [{"parts": parts}],
        "tools": [{"google_search": {}}]
    }
    payload = json.dumps(payload_dict).encode("utf-8")
    req = urllib.request.Request(url=api_endpoint, data=payload, headers={"Content-Type": "application/json"})

    try:
        with urllib.request.urlopen(req, timeout=75) as resp:
            res_json = json.loads(resp.read().decode("utf-8"))
            raw_text = res_json["candidates"][0]["content"]["parts"][0]["text"].strip()
            if raw_text.startswith("```"):
                raw_text = raw_text.strip("`").replace("json\n", "", 1).strip()
            updated_state = json.loads(raw_text)
            print("Tablero actualizado con cifras reales y horarios UTC (+10m).")
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

    if hay_input or hay_noticia_lista:
        state, ok = analyze_and_fetch_data(state, input_data if hay_input else None)
        if hay_input and ok:
            input_data["procesado"] = True
            input_data["imagenes_base64"] = []
            input_data.pop("imagen_base64", None)
            save_json(INPUT_PROFE_FILE, input_data)

    sync_cron_schedule(state)

    lima_tz = timezone(timedelta(hours=-5))
    state["ultima_actualizacion"] = datetime.now(lima_tz).strftime("%Y-%m-%d %H:%M Lima")
    save_json(STATE_FILE, state)

if __name__ == "__main__":
    main()
