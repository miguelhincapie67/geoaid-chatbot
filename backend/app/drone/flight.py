"""Procesa un vuelo del dron: saca cuadros del video, les pone el GPS del .SRT y los clasifica con el semáforo.

También acepta fotos sueltas (por ejemplo, imágenes públicas de dron de un sismo real para mostrar en el stand):
si la foto trae GPS en el EXIF se ubica en el mapa; si no, aparece solo en la galería con su crédito.
"""

import logging
import re
import shutil
import subprocess
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from app.drone.srt import position_at, read_srt
from app.services.vision_service import DamageAssessment, analyze_building_damage

logger = logging.getLogger(__name__)

FRAME_LONG_EDGE = 1568  # el mismo tope que usa el semáforo; más grande solo ocupa espacio
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".bmp", ".tif", ".tiff"}
COST_PER_FRAME_USD = 0.01  # aproximado con Sonnet 5.5 y esfuerzo bajo
FRAMES_DIR = "cuadros"

Classifier = Callable[..., DamageAssessment]


@dataclass
class Frame:
    image: str  # ruta relativa a la carpeta del vuelo, p. ej. "cuadros/cuadro_001.jpg"
    source: str  # "vuelo" o el crédito de las imágenes de ejemplo
    t: float | None = None  # segundo del video
    lat: float | None = None
    lon: float | None = None
    alt: float | None = None
    level: str | None = None  # VERDE, AMARILLO, ROJO o None (sin clasificar)
    confidence: float | None = None
    notes: list[str] = field(default_factory=list)
    classified: bool = False

    @property
    def has_gps(self) -> bool:
        return self.lat is not None and self.lon is not None


# --------------------------------------------------------------------------- video


def find_ffmpeg() -> str:
    """ffmpeg del sistema o, si no hay, el que trae el paquete imageio-ffmpeg (requirements-dron.txt)."""
    if path := shutil.which("ffmpeg"):
        return path
    try:
        import imageio_ffmpeg
    except ImportError as error:
        raise RuntimeError(
            "No encontré ffmpeg. Instálalo con: .venv\\Scripts\\python -m pip install -r requirements-dron.txt"
        ) from error
    return imageio_ffmpeg.get_ffmpeg_exe()


def video_duration(ffmpeg: str, video: Path) -> float | None:
    result = subprocess.run([ffmpeg, "-hide_banner", "-i", str(video)], capture_output=True, text=True, errors="replace", check=False)
    match = re.search(r"Duration:\s*(\d+):(\d{2}):(\d{2}(?:\.\d+)?)", result.stderr)
    if not match:
        return None
    h, m, s = match.groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def sample_times(start: float, end: float, every: float, max_frames: int) -> list[float]:
    """Un segundo cada `every` entre `start` y `end`; si son más de `max_frames`, se reparten parejo."""
    if every <= 0 or max_frames <= 0:
        raise ValueError("every y max_frames deben ser positivos")
    if end <= start:
        return [round(start, 2)]
    count = int((end - start) // every) + 1
    times = [start + i * every for i in range(count)]
    if len(times) > max_frames:
        if max_frames == 1:
            times = [times[len(times) // 2]]
        else:
            step = (len(times) - 1) / (max_frames - 1)
            times = [times[round(i * step)] for i in range(max_frames)]
    return [round(t, 2) for t in times]


def extract_frame(ffmpeg: str, video: Path, t: float, out: Path) -> bool:
    command = [
        ffmpeg, "-hide_banner", "-loglevel", "error",
        "-ss", f"{t:.2f}", "-i", str(video),
        "-frames:v", "1", "-vf", f"scale=w='min({FRAME_LONG_EDGE},iw)':h=-2", "-q:v", "3", "-y", str(out),
    ]  # fmt: skip
    result = subprocess.run(command, capture_output=True, text=True, errors="replace", check=False)
    if result.returncode != 0 or not out.exists():
        logger.warning("No se pudo sacar el cuadro del segundo %.1f: %s", t, result.stderr.strip()[:200])
        return False
    return True


def frames_from_video(
    video: Path,
    srt: Path | None,
    out_dir: Path,
    every: float = 5.0,
    max_frames: int = 40,
) -> list[Frame]:
    ffmpeg = find_ffmpeg()
    points = read_srt(srt) if srt else []
    duration = video_duration(ffmpeg, video)
    if points:
        start, end = points[0].t, points[-1].t
        if duration:
            end = min(end, duration - 0.1)
    elif duration:
        start, end = 0.0, max(0.0, duration - 0.1)
    else:
        raise RuntimeError(f"No pude leer la duración de {video.name}. ¿Es un video válido?")

    frames_dir = out_dir / FRAMES_DIR
    frames_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for i, t in enumerate(sample_times(start, end, every, max_frames), start=1):
        name = f"cuadro_{i:03d}.jpg"
        if not extract_frame(ffmpeg, video, t, frames_dir / name):
            continue
        point = position_at(points, t)
        frames.append(
            Frame(
                image=f"{FRAMES_DIR}/{name}",
                source="vuelo",
                t=t,
                lat=point.lat if point else None,
                lon=point.lon if point else None,
                alt=point.alt if point else None,
            )
        )
    return frames


# --------------------------------------------------------------------------- fotos sueltas


def image_files(paths: Iterable[Path]) -> list[Path]:
    """Expande carpetas a sus imágenes (ordenadas por nombre) y deja los archivos de imagen tal cual."""
    files = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(p for p in path.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES))
        elif path.suffix.lower() in IMAGE_SUFFIXES:
            files.append(path)
    return files


def frames_from_images(paths: Iterable[Path], out_dir: Path, credit: str) -> list[Frame]:
    frames_dir = out_dir / FRAMES_DIR
    frames_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for i, path in enumerate(image_files(paths), start=1):
        try:
            with Image.open(path) as original:
                gps = read_exif_gps(original)
                image = ImageOps.exif_transpose(original).convert("RGB")
        except (OSError, UnidentifiedImageError):
            logger.warning("No se pudo abrir %s; la salto", path.name)
            continue
        image.thumbnail((FRAME_LONG_EDGE, FRAME_LONG_EDGE))
        name = f"ejemplo_{i:03d}.jpg"
        image.save(frames_dir / name, format="JPEG", quality=88)
        lat, lon, alt = gps or (None, None, None)
        frames.append(Frame(image=f"{FRAMES_DIR}/{name}", source=credit, lat=lat, lon=lon, alt=alt))
    return frames


def read_exif_gps(image: Image.Image) -> tuple[float, float, float | None] | None:
    """(lat, lon, alt) del EXIF, como lo guardan las fotos del Avata 2 y de casi cualquier dron o celular."""
    try:
        gps = image.getexif().get_ifd(0x8825)
        lat = _dms_to_degrees(gps[2], gps.get(1, "N"), negative="S")
        lon = _dms_to_degrees(gps[4], gps.get(3, "E"), negative="W")
    except (KeyError, TypeError, ValueError, ZeroDivisionError, AttributeError):
        return None
    if lat == 0 and lon == 0:
        return None
    alt = float(gps[6]) if 6 in gps else None
    return lat, lon, alt


def _dms_to_degrees(dms, ref, negative: str) -> float:
    degrees, minutes, seconds = (float(x) for x in dms)
    value = degrees + minutes / 60 + seconds / 3600
    ref = ref.decode() if isinstance(ref, bytes) else str(ref)
    return -value if ref.strip().upper() == negative else value


# --------------------------------------------------------------------------- clasificación


def classify(
    frames: list[Frame],
    out_dir: Path,
    classifier: Classifier = analyze_building_damage,
    workers: int = 3,
    on_done: Callable[[int, int, Frame], None] | None = None,
) -> None:
    """Pasa cada cuadro por el semáforo (modo dron). Varios a la vez para que no se demore tanto."""
    pending = [frame for frame in frames if not frame.classified]

    def run(frame: Frame) -> Frame:
        result = classifier([out_dir / frame.image], source="dron")
        frame.level = result.level.value if result.level else None
        frame.confidence = result.confidence
        frame.notes = list(result.notes)
        frame.classified = True
        return frame

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(run, frame) for frame in pending]
        for done, future in enumerate(as_completed(futures), start=1):
            frame = future.result()
            if on_done:
                on_done(done, len(pending), frame)


def to_geojson(frames: list[Frame], title: str) -> dict:
    features = []
    for frame in frames:
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [frame.lon, frame.lat]} if frame.has_gps else None,
                "properties": {
                    "imagen": frame.image,
                    "fuente": frame.source,
                    "segundo": frame.t,
                    "altura_m": frame.alt,
                    "nivel": frame.level,
                    "confianza": frame.confidence,
                    "hallazgos": frame.notes,
                    "clasificado": frame.classified,
                },
            }
        )
    return {"type": "FeatureCollection", "name": title, "features": features}
