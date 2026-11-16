"""Lee el GPS de los subtítulos .SRT que los drones DJI graban junto a cada video.

Para que el dron los grabe hay que activar "Subtítulos de video" en DJI Fly (Ajustes → Cámara).
Cada bloque del .SRT trae el tiempo del video y una línea con datos de vuelo. Formatos que entiende:

    [latitude: 4.601234] [longitude: -74.065432] [rel_alt: 25.300 abs_alt: 2650.123]   (Mini, Air, Avata, Mavic 3)
    [latitude: 4.601234] [longtitude: -74.065432] ...                                (firmwares con el error de tipeo)
    GPS(-74.065432,4.601234,25) BAROMETER:25.3                                       (Phantom 4, Mavic Pro: lon, lat)
    GPS(4.601234,-74.065432,25.0M) BAROMETER(25.3)                                   (Matrice 300 y otros: lat, lon)

GPS(...) no dice qué número es la latitud, y DJI usa los dos órdenes. Se decide una vez por
archivo: primero por geografía (una latitud no pasa de ±90 y nadie vuela al sur de -60, así que en
Colombia, con longitudes entre -67 y -82, siempre queda claro), luego por las pistas del formato
(altitud con unidad "M" o BAROMETER(...) → lat, lon) y, si no hay ninguna, como los Phantom (lon, lat).

Los bloques sin GPS (0, 0 antes de que el dron tenga señal) se descartan.
"""

import re
from bisect import bisect_left
from dataclasses import dataclass
from pathlib import Path

_NUM = r"(-?\d+(?:\.\d+)?)"
_TIME = re.compile(r"(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->")
_LAT = re.compile(rf"\blatitude\s*:\s*{_NUM}", re.IGNORECASE)
_LON = re.compile(rf"\blong[a-z]*itude\s*:\s*{_NUM}", re.IGNORECASE)
_GPS = re.compile(rf"GPS\s*\(\s*{_NUM}\s*,\s*{_NUM}(?:\s*,\s*{_NUM})?", re.IGNORECASE)
_REL_ALT = re.compile(rf"\brel_alt\s*:\s*{_NUM}", re.IGNORECASE)
_ALT = re.compile(rf"\baltitude\s*:\s*{_NUM}", re.IGNORECASE)
_BAROMETER = re.compile(rf"\bBAROMETER\s*[:(]\s*{_NUM}", re.IGNORECASE)
_LAT_FIRST_HINT = re.compile(r"GPS\s*\([^)]*\d\s*M\s*\)|\bBAROMETER\s*\(", re.IGNORECASE)
_SOUTHERNMOST_FLIGHT = -60.0  # más al sur solo está la Antártida


@dataclass(frozen=True)
class SrtPoint:
    t: float  # segundos desde el inicio del video
    lat: float
    lon: float
    alt: float | None = None  # metros sobre el punto de despegue, si el .SRT lo trae


def read_srt(path: Path) -> list[SrtPoint]:
    """Devuelve los puntos con GPS del archivo, ordenados por tiempo."""
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    return parse_srt(text)


@dataclass(frozen=True)
class _Block:
    t: float
    first: float  # latitud si `labeled`; si no, el primer número de GPS(...)
    second: float
    alt: float | None
    labeled: bool  # el bloque dice cuál es la latitud y cuál la longitud
    hints_lat_first: bool = False


def parse_srt(text: str) -> list[SrtPoint]:
    blocks = [b for raw in re.split(r"\r?\n\s*\r?\n", text) if (b := _parse_block(raw)) is not None]
    lon_first = _gps_is_lon_first([b for b in blocks if not b.labeled])

    points = []
    for b in blocks:
        lat, lon = (b.second, b.first) if (lon_first and not b.labeled) else (b.first, b.second)
        if (lat == 0 and lon == 0) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        points.append(SrtPoint(t=b.t, lat=lat, lon=lon, alt=b.alt))
    points.sort(key=lambda p: p.t)
    return points


def _parse_block(block: str) -> _Block | None:
    time = _TIME.search(block)
    if not time:
        return None
    h, m, s, ms = time.groups()
    t = round(int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000, 3)

    lat_match, lon_match = _LAT.search(block), _LON.search(block)
    if lat_match and lon_match:
        return _Block(t, float(lat_match.group(1)), float(lon_match.group(1)), _altitude(block), labeled=True)
    if gps := _GPS.search(block):
        hint = bool(_LAT_FIRST_HINT.search(block))
        return _Block(t, float(gps.group(1)), float(gps.group(2)), _altitude(block), labeled=False, hints_lat_first=hint)
    return None


def _gps_is_lon_first(blocks: list[_Block]) -> bool:
    """Decide el orden de GPS(a, b) para todo el archivo."""
    with_signal = [b for b in blocks if not (b.first == 0 and b.second == 0)]
    for b in with_signal:
        if not _can_be_latitude(b.first):
            return True
        if not _can_be_latitude(b.second):
            return False
    return not any(b.hints_lat_first for b in with_signal)


def _can_be_latitude(value: float) -> bool:
    return _SOUTHERNMOST_FLIGHT <= value <= 90


def _altitude(block: str) -> float | None:
    for pattern in (_REL_ALT, _ALT, _BAROMETER):
        if match := pattern.search(block):
            return float(match.group(1))
    return None


def position_at(points: list[SrtPoint], t: float, tolerance_s: float = 2.0) -> SrtPoint | None:
    """El punto más cercano al segundo `t`, si hay uno a menos de `tolerance_s` segundos."""
    if not points:
        return None
    times = [p.t for p in points]
    i = bisect_left(times, t)
    candidates = [points[j] for j in (i - 1, i) if 0 <= j < len(points)]
    best = min(candidates, key=lambda p: abs(p.t - t))
    return best if abs(best.t - t) <= tolerance_s else None
