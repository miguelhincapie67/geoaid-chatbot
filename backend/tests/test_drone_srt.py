"""Lectura del GPS de los .SRT de DJI (app/drone/srt.py)."""

import pytest

from app.drone.srt import SrtPoint, parse_srt, position_at, read_srt

AVATA = """1
00:00:00,000 --> 00:00:00,033
<font size="28">FrameCnt: 1, DiffTime: 33ms
2026-11-15 10:20:30.123
[iso: 100] [shutter: 1/1000.0] [fnum: 2.8] [ev: 0] [color_md: default] [focal_len: 12.00] [latitude: 4.601234] [longitude: -74.065432] [rel_alt: 25.300 abs_alt: 2650.123] [ct: 5300] </font>

2
00:00:01,000 --> 00:00:01,033
<font size="28">FrameCnt: 31, DiffTime: 33ms
2026-11-15 10:20:31.123
[iso: 100] [shutter: 1/1000.0] [fnum: 2.8] [ev: 0] [latitude: 4.601300] [longitude: -74.065500] [rel_alt: 26.000 abs_alt: 2650.823] </font>
"""


def test_formato_actual_de_dji():
    points = parse_srt(AVATA)
    assert points == [
        SrtPoint(t=0.0, lat=4.601234, lon=-74.065432, alt=25.3),
        SrtPoint(t=1.0, lat=4.6013, lon=-74.0655, alt=26.0),
    ]


def test_error_de_tipeo_longtitude():
    block = "1\n00:00:02,500 --> 00:00:02,533\n[latitude: 4.6] [longtitude: -74.1] [altitude: 30.5]\n"
    assert parse_srt(block) == [SrtPoint(t=2.5, lat=4.6, lon=-74.1, alt=30.5)]


def test_formato_viejo_gps_lon_lat():
    block = "3\n00:01:05,000 --> 00:01:06,000\nHOME(-74.0,4.5) 2026.11.15 10:20:30\nGPS(-74.065432,4.601234,19) BAROMETER:25.3\n"
    assert parse_srt(block) == [SrtPoint(t=65.0, lat=4.601234, lon=-74.065432, alt=25.3)]


def test_descarta_bloques_sin_senal_o_sin_gps():
    text = (
        "1\n00:00:00,000 --> 00:00:00,033\n[latitude: 0.000000] [longitude: 0.000000] [rel_alt: 0.000]\n\n"
        "2\n00:00:01,000 --> 00:00:01,033\n[iso: 100] [shutter: 1/1000.0]\n\n"
        "3\n00:00:02,000 --> 00:00:02,033\n[latitude: 95.0] [longitude: -74.0]\n"
    )
    assert parse_srt(text) == []


def test_lee_archivo_con_bom_y_finales_de_linea_de_windows(tmp_path):
    path = tmp_path / "DJI_0001.SRT"
    path.write_bytes(("﻿" + AVATA.replace("\n", "\r\n")).encode("utf-8"))
    assert len(read_srt(path)) == 2


def test_ordena_por_tiempo():
    later = "2\n00:00:05,000 --> 00:00:05,033\n[latitude: 4.7] [longitude: -74.2]\n"
    earlier = "1\n00:00:01,000 --> 00:00:01,033\n[latitude: 4.6] [longitude: -74.1]\n"
    assert [p.t for p in parse_srt(later + "\n" + earlier)] == [1.0, 5.0]


@pytest.mark.parametrize(("t", "expected"), [(0.4, 0.0), (0.6, 1.0), (2.9, 1.0), (3.1, None), (-5, None)])
def test_posicion_mas_cercana_con_tolerancia(t, expected):
    points = parse_srt(AVATA)
    point = position_at(points, t, tolerance_s=2.0)
    assert (point.t if point else None) == expected


def test_posicion_sin_puntos():
    assert position_at([], 3.0) is None
