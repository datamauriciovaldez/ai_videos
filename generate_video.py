#!/usr/bin/env python3
"""
generate_video.py
------------------
Toma un JSON con guion + escenas y produce un video vertical (1080x1920)
listo para TikTok: narración en voz, b-roll de fútbol y subtítulos
sincronizados palabra por palabra.

Uso:
    python generate_video.py script.json output.mp4

Formato esperado de script.json (lo genera Gemini en el paso 2 de Make):
{
  "narration": "Texto completo que se va a narrar de corrido...",
  "scenes": [
    {"text": "Primera frase o bloque del guion.", "keywords": "messi gol celebracion"},
    {"text": "Segunda frase...", "keywords": "estadio futbol multitud"}
  ],
  "caption": "Texto para el pie del video en TikTok",
  "hashtags": ["#futbol", "#viral", "#deportes"]
}

Variables de entorno necesarias:
    PEXELS_API_KEY   -> https://www.pexels.com/api/ (gratis)
    TTS_VOICE        -> opcional, default "es-ES-AlvaroNeural"
"""

import os
import sys
import json
import asyncio
import subprocess
import tempfile
from pathlib import Path

import requests
import edge_tts
import whisper
from moviepy.editor import (
    VideoFileClip, AudioFileClip, CompositeVideoClip,
    TextClip, concatenate_videoclips, ColorClip
)

PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
TTS_VOICE = os.environ.get("TTS_VOICE", "es-ES-AlvaroNeural")
TARGET_W, TARGET_H = 1080, 1920


# ---------------------------------------------------------------------------
# 1. Narración (TTS gratis con edge-tts)
# ---------------------------------------------------------------------------
async def generate_narration(text: str, out_path: str) -> None:
    communicate = edge_tts.Communicate(text, TTS_VOICE)
    await communicate.save(out_path)


# ---------------------------------------------------------------------------
# 2. Subtítulos palabra por palabra (Whisper, corre local y gratis)
# ---------------------------------------------------------------------------
def transcribe_words(audio_path: str):
    """Devuelve lista de dicts: {'word': str, 'start': float, 'end': float}"""
    model = whisper.load_model("base")
    result = model.transcribe(audio_path, word_timestamps=True, language="es")
    words = []
    for segment in result["segments"]:
        for w in segment.get("words", []):
            words.append({
                "word": w["word"].strip(),
                "start": w["start"],
                "end": w["end"],
            })
    return words


# ---------------------------------------------------------------------------
# 3. B-roll: buscar y descargar clips de Pexels según keywords de cada escena
# ---------------------------------------------------------------------------
def fetch_broll_clip(keywords: str, dest_dir: str, index: int) -> str:
    headers = {"Authorization": PEXELS_API_KEY}
    url = "https://api.pexels.com/videos/search"
    params = {"query": keywords, "orientation": "portrait", "per_page": 1}
    resp = requests.get(url, headers=headers, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if not data.get("videos"):
        # fallback genérico si no hay resultados para esas keywords
        params["query"] = "soccer stadium"
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        data = resp.json()

    video_files = data["videos"][0]["video_files"]
    # elegimos el archivo de mayor resolución disponible
    best = max(video_files, key=lambda f: (f.get("width") or 0) * (f.get("height") or 0))
    video_url = best["link"]

    out_path = os.path.join(dest_dir, f"clip_{index}.mp4")
    with requests.get(video_url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
    return out_path


# ---------------------------------------------------------------------------
# 4. Recorte/zoom para llenar formato vertical sin franjas negras
# ---------------------------------------------------------------------------
def fit_vertical(clip):
    clip = clip.without_audio()
    scale = max(TARGET_W / clip.w, TARGET_H / clip.h)
    clip = clip.resize(scale)
    x_center = clip.w / 2
    y_center = clip.h / 2
    clip = clip.crop(
        x_center=x_center, y_center=y_center,
        width=TARGET_W, height=TARGET_H,
    )
    return clip


# ---------------------------------------------------------------------------
# 5. Subtítulo tipo "karaoke": una palabra grande resaltada a la vez
# ---------------------------------------------------------------------------
def build_caption_clips(words, video_duration):
    clips = []
    for w in words:
        if w["start"] >= video_duration:
            break
        end = min(w["end"], video_duration)
        txt = TextClip(
            w["word"].upper(),
            fontsize=90,
            color="white",
            font="DejaVu-Sans-Bold",
            stroke_color="black",
            stroke_width=4,
            method="label",
        ).set_position(("center", TARGET_H * 0.72))
        txt = txt.set_start(w["start"]).set_end(end)
        clips.append(txt)
    return clips


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(script_path: str, output_path: str):
    with open(script_path, "r", encoding="utf-8") as f:
        script = json.load(f)

    narration_text = script["narration"]
    scenes = script["scenes"]

    with tempfile.TemporaryDirectory() as tmp:
        # --- Voz ---
        narration_path = os.path.join(tmp, "narration.mp3")
        asyncio.run(generate_narration(narration_text, narration_path))
        audio_clip = AudioFileClip(narration_path)
        total_duration = audio_clip.duration

        # --- Subtítulos sincronizados ---
        words = transcribe_words(narration_path)

        # --- B-roll ---
        broll_paths = []
        for i, scene in enumerate(scenes):
            try:
                path = fetch_broll_clip(scene["keywords"], tmp, i)
                broll_paths.append(path)
            except Exception as e:
                print(f"[warn] no se pudo bajar b-roll para '{scene['keywords']}': {e}")

        if not broll_paths:
            raise RuntimeError("No se descargó ningún clip de b-roll. Revisa PEXELS_API_KEY.")

        # repartimos la duración total entre los clips disponibles
        per_clip_duration = total_duration / len(broll_paths)
        video_segments = []
        for path in broll_paths:
            clip = VideoFileClip(path)
            clip = fit_vertical(clip)
            if clip.duration < per_clip_duration:
                loops = int(per_clip_duration // clip.duration) + 1
                clip = concatenate_videoclips([clip] * loops)
            clip = clip.subclip(0, per_clip_duration)
            video_segments.append(clip)

        base_video = concatenate_videoclips(video_segments, method="compose")
        base_video = base_video.set_duration(total_duration)
        base_video = base_video.set_audio(audio_clip)

        caption_clips = build_caption_clips(words, total_duration)
        final = CompositeVideoClip([base_video, *caption_clips], size=(TARGET_W, TARGET_H))
        final = final.set_duration(total_duration)

        final.write_videofile(
            output_path,
            fps=30,
            codec="libx264",
            audio_codec="aac",
            threads=4,
            preset="medium",
        )

    print(f"[ok] video generado en: {output_path}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Uso: python generate_video.py script.json output.mp4")
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
