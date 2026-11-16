"""Lee el GPS de los subtítulos .SRT que los drones DJI graban junto a cada video.

Para que el dron los grabe hay que activar "Subtítulos de video" en DJI Fly (Ajustes → Cámara).
Cada bloque del .SRT trae el tiempo del video y una línea con datos de vuelo. Formatos que entiende:

    [latitude: 4.601234] [longitude: -74.065432] [rel_alt: 25.300 abs_alt: 2650.123]   (Avata 2, Mini, Air)
    [latitude: 4.601234] [longtitude: -74.065432] ...                                (firmwares con el error de tipeo)
    GPS(-74.065432,4.601234,25) BAROMETER:25.3                                       (drones más viejos: lon, lat)

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
_BAROMETER = re.compile(rf"\bBAROMETER\s*:\s*{_NUM}", re.IGNORECASE)


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


def parse_srt(text: str) -> list[SrtPoint]:
    points = []
    for block in re.split(r"\r?\n\s*\r?\n", text):
        point = _parse_block(block)
        if point is not None:
            points.append(point)
    points.sort(key=lambda p: p.t)
    return points


def _parse_block(block: str) -> SrtPoint | None:
    time = _TIME.search(block)
    if not time:
        return None
    h, m, s, ms = time.groups()
    t = int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000

    lat_match, lon_match = _LAT.search(block), _LON.search(block)
    if lat_match and lon_match:
        lat, lon = float(lat_match.group(1)), float(lon_match.group(1))
    elif gps := _GPS.search(block):
        lon, lat = float(gps.group(1)), float(gps.group(2))  # el formato viejo va (longitud, latitud)
    else:
        return None

    if (lat == 0 and lon == 0) or not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return SrtPoint(t=round(t, 3), lat=lat, lon=lon, alt=_altitude(block))


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
