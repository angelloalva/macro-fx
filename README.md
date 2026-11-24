# Tablero Macro FX Automatizado (Semana 23/11/2026)

## Estructura de archivos incluidos
- `index.html`: Interfaz web visual del tablero (pizarra oscura) con soporte para pegar texto o capturas de pantalla (`Ctrl+V`) del profesor.
- `state.json`: Estado actual del tablero (sesgos base de Capa 1, volátiles de Capa 2 y eventos de la semana).
- `input_profe.json`: Buzón de entrada donde la web envía las notas/imágenes del profesor para ser procesadas.
- `update_board.py`: Script en Python que actualiza volátiles (VIX, Crudo, Cobre) y analiza texto/imágenes con Gemini Vision (`gemini-2.5-flash`).
- `.github/workflows/cron.yml`: Disparadores automáticos por horario (GMT) y ejecución instantánea al recibir notas del profesor.

## Instalación rápida en GitHub (3 minutos)
1. Crea un repositorio nuevo en GitHub y sube todo el contenido de este ZIP manteniendo la estructura de carpetas (incluyendo `.github/workflows/cron.yml`).
2. Ve a **Settings -> Pages**, selecciona `Deploy from a branch` (`main` / `/(root)`) y guarda.
3. Obtén una API Key gratuita en **Google AI Studio** y guárdala en tu repositorio en **Settings -> Secrets and variables -> Actions -> New repository secret** con el nombre `GEMINI_API_KEY`.
4. Crea un *Fine-grained Personal Access Token* en GitHub con permiso `Contents: Read and write` solo para este repositorio, y guárdalo en la pestaña de configuración dentro del botón **"+ Nota / Captura del Profe"** de tu web.
