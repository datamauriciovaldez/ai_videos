# Setup del generador de videos de fútbol

## 1. Crear el repositorio en GitHub
1. Crea un repo **público** (así los minutos de Actions son ilimitados y gratis).
2. Sube estos 3 archivos manteniendo la misma estructura de carpetas:
   - `generate_video.py`
   - `requirements.txt`
   - `.github/workflows/generate.yml`

## 2. Conseguir las API keys gratis
- **Pexels**: crea cuenta en https://www.pexels.com/api/ y copia tu API key (gratis, sin tarjeta).
- **Gemini**: crea una key en https://aistudio.google.com/apikey (tier gratuito).
- **Personal Access Token de GitHub**: Settings → Developer settings → Fine-grained tokens.
  Dale permiso de "Contents: Read and write" y "Actions: Read and write" solo sobre ese repo.
  Esta es la que usará Make para disparar el workflow (no la de GITHUB_TOKEN del workflow, esa la
  pone GitHub solo).

## 3. Configurar los secrets del repo
En GitHub: Settings → Secrets and variables → Actions → New repository secret
- `PEXELS_API_KEY` = tu key de Pexels
- `MAKE_WEBHOOK_URL` = la URL del webhook de Make (la generas en el paso 4)

## 4. Armar el escenario en Make
Módulos en orden:
1. **Google Sheets / Telegram Bot** — Watch Rows / Watch Updates (trigger con tu idea).
2. **HTTP – Make a request** → POST a
   `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key=TU_GEMINI_KEY`
   con un prompt que le pida devolver **solo JSON** con el formato:
   `{"narration": "...", "scenes": [{"text":"...","keywords":"..."}], "caption":"...", "hashtags":[...]}`
3. **HTTP – Make a request** → POST a
   `https://api.github.com/repos/TU_USUARIO/TU_REPO/dispatches`
   Headers: `Authorization: Bearer TU_GITHUB_TOKEN`, `Accept: application/vnd.github+json`
   Body: `{"event_type": "generate-video", "client_payload": <el JSON del paso 2>}`
4. **Webhooks – Custom webhook** — este es el que recibe el aviso de GitHub Actions cuando el
   video ya está listo (usa la URL que te da Make aquí como `MAKE_WEBHOOK_URL` en el paso 3).
5. **Telegram/Email** — te manda el `video_url` recibido para que lo revises.
6. **Router + botón de aprobación** → si apruebas, sigue al módulo de publicación en TikTok.
7. **HTTP – Make a request** → POST al endpoint de TikTok Content Posting API con el video,
   el caption y los hashtags.

## 5. Probar antes de automatizar del todo
Antes de conectar el paso 6-7, corre el flujo manualmente varias veces y revisa los videos que
salen. Los primeros intentos van a necesitar ajustes en el prompt de Gemini (para que las
keywords de b-roll sean más específicas) y en el tamaño de fuente de los subtítulos.

## Costos
Todo lo de arriba es gratis dentro de límites generosos:
- GitHub Actions: ilimitado en repos públicos.
- Pexels API: 200 requests/hora gratis.
- Gemini API: tier gratuito con límite diario de requests.
- Make: 1.000 operaciones/mes gratis (cada escenario completo gasta ~5-6 operaciones).
- TikTok Content Posting API: gratis, requiere aprobación de tu app.
