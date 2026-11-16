"""Video del dron con los recuadros de cada edificación pegados a las casas.

Claude solo mira algunos cuadros clave: uno al empezar cada escena y después uno cada `--cada`
segundos. Entre un cuadro clave y otro, el movimiento de la cámara se estima con OpenCV (puntos ORB
y una homografía de un cuadro al siguiente) y los recuadros se mueven con la imagen. Cada cuadro del
video usa el cuadro clave más cercano de su misma escena.

Todo se procesa antes de mostrarlo (no en vivo): en la expo se proyecta el video resultante, que se ve
igual, y no depende del internet del lugar.

Necesita OpenCV:  .venv\\Scripts\\pip install -r requirements-dron.txt
"""

import json
import subprocess
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from app.config import BACKEND_DIR
from app.drone.boxes import (
    COST_PER_FRAME_USD,
    Box,
    _open,
    box_corners,
    boxes_from_json,
    boxes_to_json,
    detect_buildings,
    draw_overlay,
)
from app.drone.flight import find_ffmpeg

WORK_WIDTH = 640  # el movimiento se estima en una copia pequeña: es más rápido y igual de preciso para esto
MIN_MATCHES = 25
CUT_DIFF = 25.0  # diferencia promedio (0-255) entre dos cuadros seguidos que se toma como corte de escena
MIN_SCENE_S = 0.6  # escenas más cortas (transiciones) quedan sin recuadros
FIRST_KEY_S = 0.4  # el primer cuadro clave de cada escena, un poco después del corte
KEYS_FILE = "cajas.json"
OUTPUT_VIDEO = "video_cajas.mp4"
KEYS_DIR = "clave"

Detector = Callable[[Path], list[Box] | None]


@dataclass
class Motion:
    fps: float
    width: int
    height: int
    # steps[i]: homografía del cuadro i-1 al i, o None si ahí hay un corte de escena (steps[0] siempre es None).
    steps: list[np.ndarray | None]

    @property
    def frame_count(self) -> int:
        return len(self.steps)


# ---------- Movimiento de la cámara ----------


def estimate_motion(video: Path, on_progress: Callable[[int], None] | None = None) -> Motion:
    capture = _open_video(video)
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    orb = cv2.ORB_create(nfeatures=2000, fastThreshold=12)
    matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
    steps: list[np.ndarray | None] = []
    previous = previous_tiny = None
    width = height = 0
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        height, width = frame.shape[:2]
        scale = WORK_WIDTH / width
        small = cv2.cvtColor(cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY)
        tiny = cv2.resize(small, (160, max(1, round(160 * small.shape[0] / small.shape[1]))), interpolation=cv2.INTER_AREA)
        tiny = tiny.astype(np.float32)
        current = orb.detectAndCompute(small, None)
        step = None
        # Un corte se nota en que casi toda la imagen cambia de golpe; los logos y subtítulos fijos
        # pueden engañar a la homografía, pero no a esta diferencia.
        if previous is not None and float(np.mean(np.abs(tiny - previous_tiny))) < CUT_DIFF:
            step = _homography(previous, current, matcher)
        steps.append(_to_full_size(step, scale) if step is not None else None)
        previous, previous_tiny = current, tiny
        if on_progress and len(steps) % 100 == 0:
            on_progress(len(steps))
    capture.release()
    if not steps:
        raise RuntimeError(f"No pude leer cuadros de {video.name}")
    return Motion(fps=fps, width=width, height=height, steps=steps)


def _homography(previous, current, matcher) -> np.ndarray | None:
    (kp1, des1), (kp2, des2) = previous, current
    if des1 is None or des2 is None or len(kp1) < MIN_MATCHES or len(kp2) < MIN_MATCHES:
        return None
    good = [p[0] for p in matcher.knnMatch(des1, des2, k=2) if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
    if len(good) < MIN_MATCHES:
        return None
    src = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    homography, mask = cv2.findHomography(src, dst, cv2.RANSAC, 3.0)
    if homography is None or mask is None:
        return None
    inliers = int(mask.sum())
    if inliers < MIN_MATCHES or inliers < 0.3 * len(good):
        return None
    return homography


def _to_full_size(homography: np.ndarray, scale: float) -> np.ndarray:
    s = np.diag([scale, scale, 1.0])
    return np.linalg.inv(s) @ homography @ s


def scenes(motion: Motion) -> list[tuple[int, int]]:
    """Tramos [inicio, fin) sin cortes de cámara."""
    cuts = [i for i, step in enumerate(motion.steps) if step is None]
    bounds = [*cuts, motion.frame_count]
    return [(start, end) for start, end in pairwise(bounds) if end > start]


def pick_keyframes(scene_list: list[tuple[int, int]], fps: float, every_s: float, max_keys: int) -> list[int]:
    """Un cuadro clave al empezar cada escena y luego uno cada `every_s` segundos, sin pasar de `max_keys`."""
    first, rest = [], []
    for start, end in scene_list:
        if (end - start) < MIN_SCENE_S * fps:
            continue
        key = start + min(round(FIRST_KEY_S * fps), (end - start) // 2)
        first.append(key)
        step = max(1, round(every_s * fps))
        rest += list(range(key + step, end - round(0.3 * fps), step))
    chosen = first[:max_keys]
    chosen += rest[: max(0, max_keys - len(chosen))]
    return sorted(chosen)


def scene_transforms(motion: Motion, scene: tuple[int, int]) -> list[np.ndarray]:
    """Para cada cuadro de la escena, la homografía desde el primer cuadro de la escena."""
    start, end = scene
    out = [np.eye(3)]
    for i in range(start + 1, end):
        out.append(motion.steps[i] @ out[-1])
    return out


# ---------- Cuadros clave y Claude ----------


def save_keyframes(video: Path, keys: list[int], out_dir: Path) -> dict[int, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    wanted, saved = set(keys), {}
    capture = _open_video(video)
    index = 0
    while wanted - saved.keys():
        ok, frame = capture.read()
        if not ok:
            break
        if index in wanted:
            path = out_dir / f"clave_{index:06d}.jpg"
            cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
            saved[index] = path
        index += 1
    capture.release()
    return saved


def classify_keyframes(paths: dict[int, Path], detector: Detector, workers: int = 3) -> dict[int, list[Box] | None]:
    keys = sorted(paths)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(lambda k: detector(paths[k]), keys))
    return dict(zip(keys, results))


# ---------- Video de salida ----------


def render(video: Path, motion: Motion, results: dict[int, list[Box]], out_path: Path) -> Path:
    """Escribe el video con los recuadros, moviéndolos con la cámara desde el cuadro clave más cercano."""
    plan = _frame_plan(motion, results)
    width, height = motion.width - motion.width % 2, motion.height - motion.height % 2
    tmp = out_path.with_name(out_path.stem + ".tmp.mp4")
    encoder = subprocess.Popen(
        [find_ffmpeg(), "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
         "-r", f"{motion.fps:.3f}", "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(tmp)],
        stdin=subprocess.PIPE,
    )  # fmt: skip
    capture = _open_video(video)
    index = 0
    try:
        while index < motion.frame_count:
            ok, frame = capture.read()
            if not ok:
                break
            rgb = Image.fromarray(cv2.cvtColor(frame[:height, :width], cv2.COLOR_BGR2RGB))
            shapes = _shapes_for(plan.get(index), width, height)
            encoder.stdin.write(draw_overlay(rgb, shapes).tobytes())
            index += 1
    finally:
        capture.release()
        encoder.stdin.close()
        code = encoder.wait()
    if code != 0:
        raise RuntimeError("ffmpeg no pudo escribir el video")
    tmp.replace(out_path)
    return out_path


def _frame_plan(motion: Motion, results: dict[int, list[Box]]) -> dict[int, tuple[list[Box], np.ndarray]]:
    """Para cada cuadro: los recuadros de su cuadro clave y la homografía para llevarlos hasta él."""
    plan = {}
    for scene in scenes(motion):
        start, end = scene
        keys = [k for k in sorted(results) if start <= k < end and results[k]]
        if not keys:
            continue
        transforms = scene_transforms(motion, scene)
        for i in range(start, end):
            key = min(keys, key=lambda k: abs(k - i))
            to_frame = transforms[i - start] @ np.linalg.inv(transforms[key - start])
            plan[i] = (results[key], to_frame)
    return plan


def _shapes_for(entry, width: int, height: int):
    if entry is None:
        return []
    boxes, homography = entry
    shapes = []
    for box in boxes:
        corners = np.float32(box_corners(box, width, height)).reshape(-1, 1, 2)
        moved = cv2.perspectiveTransform(corners, homography).reshape(-1, 2)
        if not np.isfinite(moved).all():
            continue
        xs, ys = moved[:, 0], moved[:, 1]
        visible_w = min(xs.max(), width) - max(xs.min(), 0)
        visible_h = min(ys.max(), height) - max(ys.min(), 0)
        if visible_w < 0.02 * width or visible_h < 0.02 * height:  # se salió de la imagen
            continue
        shapes.append(([tuple(map(float, p)) for p in moved], box))
    return shapes


def _open_video(video: Path) -> cv2.VideoCapture:
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise RuntimeError(f"OpenCV no pudo abrir {video}")
    return capture


# ---------- Comando ----------


def run_video(args, effort: str, detector: Detector | None = None) -> int:
    video: Path = args.video.resolve()
    if not video.exists():
        print(f"No encuentro el video {video}")
        return 1
    out_dir = BACKEND_DIR / "data" / "vuelos" / (args.nombre or video.stem)
    out_dir.mkdir(parents=True, exist_ok=True)
    detector = detector or (lambda path: detect_buildings(path, effort=effort))

    print("1/3 Siguiendo el movimiento de la cámara…")
    started = time.monotonic()
    motion = estimate_motion(video, on_progress=lambda n: print(f"    {n} cuadros", end="\r"))
    scene_list = scenes(motion)
    keys = pick_keyframes(scene_list, motion.fps, args.cada, args.max_cuadros)
    print(f"    {motion.frame_count} cuadros, {len(scene_list)} escenas, {len(keys)} cuadros clave ({time.monotonic() - started:.0f} s)")
    if not keys:
        print("No quedó ningún cuadro clave (¿el video es muy corto?).")
        return 1

    keys_file = out_dir / KEYS_FILE
    saved = {} if args.de_nuevo else _load_results(keys_file, video)
    missing = [k for k in keys if k not in saved]
    results = {k: saved[k] for k in keys if k in saved}
    if missing:
        cost = len(missing) * COST_PER_FRAME_USD
        print(f"2/3 Claude va a mirar {len(missing)} cuadros clave (≈ USD {cost:.2f}).")
        if not args.si and sys.stdin.isatty() and input("¿Sigo? (s/n): ").strip().lower() not in {"s", "si", "sí", "y"}:
            print("Listo, no gasté nada.")
            return 0
        paths = save_keyframes(video, missing, out_dir / KEYS_DIR)
        fresh = classify_keyframes(paths, detector)
        failed = [k for k, boxes in fresh.items() if boxes is None]
        results |= {k: boxes for k, boxes in fresh.items() if boxes is not None}
        _save_results(keys_file, video, results)
        if failed:
            print(f"    {len(failed)} cuadros clave fallaron; esos tramos usan el cuadro clave vecino.")
    else:
        print("2/3 Uso los recuadros guardados (gratis). Con --de-nuevo se le vuelve a preguntar a Claude.")

    total = sum(len(boxes) for boxes in results.values())
    print(f"3/3 Dibujando el video ({total} recuadros en {len(results)} cuadros clave)…")
    out = render(video, motion, results, out_dir / OUTPUT_VIDEO)
    print(f"\nVideo: {out}")
    if not args.no_abrir:
        _open(out)
    return 0


def _load_results(path: Path, video: Path) -> dict[int, list[Box]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if data.get("video") != video.name:
        return {}
    return {int(k): boxes_from_json(v) for k, v in data.get("cuadros_clave", {}).items()}


def _save_results(path: Path, video: Path, results: dict[int, list[Box]]) -> None:
    data = {"video": video.name, "cuadros_clave": {str(k): boxes_to_json(v) for k, v in sorted(results.items())}}
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
