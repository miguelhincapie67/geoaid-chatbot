"""Procesa un vuelo del dron y arma el mapa para el stand.

Desde la carpeta backend/ (en Windows):

    .venv\\Scripts\\python -m app.drone --video DJI_0001.MP4
    .venv\\Scripts\\python -m app.drone --video DJI_0001.MP4 --cada 5 --max-cuadros 40
    .venv\\Scripts\\python -m app.drone --imagenes C:\\ruta\\fotos --credito "UAVs-TEBDE, Turquía 2023 (CC BY 4.0)"
    .venv\\Scripts\\python -m app.drone --video DJI_0001.MP4 --sin-clasificar      (gratis: solo cuadros y mapa)

El .SRT se busca solo junto al video (mismo nombre). El resultado queda en backend/data/vuelos/<nombre>/,
que no se sube a git: mapa.html, resultados.geojson y la carpeta cuadros/.
"""

import argparse
import json
import logging
import shutil
import sys
import webbrowser
from pathlib import Path

from app.config import BACKEND_DIR, get_settings
from app.drone.flight import (
    COST_PER_FRAME_USD,
    FRAMES_DIR,
    Frame,
    classify,
    frames_from_images,
    frames_from_video,
    to_geojson,
)
from app.drone.report import write_report


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    if not args.video and not args.imagenes:
        _parser().error("Pasa --video, --imagenes o los dos.")

    name = args.nombre or (args.video.stem if args.video else "ejemplos")
    out_dir = (args.salida or BACKEND_DIR / "data" / "vuelos" / name).resolve()
    if (out_dir / FRAMES_DIR).exists():
        shutil.rmtree(out_dir / FRAMES_DIR)  # cuadros de una corrida anterior con el mismo nombre
    out_dir.mkdir(parents=True, exist_ok=True)

    frames: list[Frame] = []
    if args.video:
        if not args.video.exists():
            return _fail(f"No encuentro el video {args.video}")
        srt = args.srt or _find_srt(args.video)
        if srt is None:
            print("Ojo: no encontré el .SRT junto al video. Los cuadros quedan sin GPS (activa 'Subtítulos de video' en DJI Fly).")
        print(f"Sacando un cuadro cada {args.cada:g} s (máximo {args.max_cuadros})…")
        try:
            frames += frames_from_video(args.video, srt, out_dir, every=args.cada, max_frames=args.max_cuadros)
        except RuntimeError as error:
            return _fail(str(error))
    if args.imagenes:
        frames += frames_from_images(args.imagenes, out_dir, credit=args.credito)
    if not frames:
        return _fail("No salió ningún cuadro ni imagen para procesar.")

    with_gps = sum(frame.has_gps for frame in frames)
    print(f"{len(frames)} imágenes listas, {with_gps} con GPS.")

    if not args.sin_clasificar:
        if not get_settings().ANTHROPIC_API_KEY:
            return _fail("Falta ANTHROPIC_API_KEY en backend\\.env. Usa --sin-clasificar para solo armar el mapa.")
        cost = len(frames) * COST_PER_FRAME_USD
        print(f"Se van a clasificar {len(frames)} imágenes (≈ USD {cost:.2f}).")
        if not args.si and sys.stdin.isatty() and input("¿Sigo? (s/n): ").strip().lower() not in {"s", "si", "sí", "y"}:
            print("Listo, no clasifiqué nada. El mapa queda sin colores.")
        else:
            classify(frames, out_dir, on_done=_progress)

    title = args.titulo or (f"Sobrevuelo {name}" if args.video else "Daño visto por dron: ejemplos")
    (out_dir / "resultados.geojson").write_text(json.dumps(to_geojson(frames, title), ensure_ascii=False, indent=2), encoding="utf-8")
    html = write_report(frames, out_dir, title)
    print(f"\nMapa: {html}")
    if not args.no_abrir:
        webbrowser.open(html.as_uri())
    return 0


def _find_srt(video: Path) -> Path | None:
    for suffix in (".SRT", ".srt"):
        candidate = video.with_suffix(suffix)
        if candidate.exists():
            return candidate
    return None


def _progress(done: int, total: int, frame: Frame) -> None:
    level = frame.level or "SIN CLASIFICAR"
    confidence = f" ({frame.confidence:.2f})" if frame.confidence is not None else ""
    print(f"  [{done}/{total}] {Path(frame.image).name} → {level}{confidence}")


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m app.drone", description="Clasifica un vuelo del dron con el semáforo de GeoAid.")
    p.add_argument("--video", type=Path, help="video del dron (MP4)")
    p.add_argument("--srt", type=Path, help="subtítulos con el GPS (si no, se busca junto al video)")
    p.add_argument("--cada", type=float, default=5.0, help="segundos entre cuadros (por defecto 5)")
    p.add_argument("--max-cuadros", type=int, default=40, help="tope de cuadros del video, para cuidar el presupuesto (40)")
    p.add_argument("--imagenes", type=Path, nargs="+", help="fotos o carpetas con fotos (p. ej. ejemplos de sismos reales)")
    p.add_argument("--credito", default="imágenes de ejemplo", help="de dónde salen las --imagenes; se muestra en el mapa")
    p.add_argument("--nombre", help="nombre de la carpeta de salida (por defecto, el del video)")
    p.add_argument("--titulo", help="título del mapa")
    p.add_argument("--salida", type=Path, help="carpeta de salida (por defecto backend/data/vuelos/<nombre>)")
    p.add_argument("--sin-clasificar", action="store_true", help="no llama a la API: solo cuadros y mapa (gratis)")
    p.add_argument("--si", action="store_true", help="no preguntar antes de gastar")
    p.add_argument("--no-abrir", action="store_true", help="no abrir el mapa en el navegador")
    return p


if __name__ == "__main__":
    sys.exit(main())
