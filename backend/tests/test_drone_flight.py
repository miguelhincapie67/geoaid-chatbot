"""Módulo del dron (app/drone): cuadros, GPS, clasificación y mapa, sin llamar a la API real."""

import json
import re
import subprocess

import pytest
from PIL import Image

from app.db.models import DamageLevel
from app.drone import __main__ as cli
from app.drone.flight import (
    Frame,
    classify,
    find_ffmpeg,
    frames_from_images,
    frames_from_video,
    read_exif_gps,
    sample_times,
    to_geojson,
)
from app.drone.report import render_html
from app.services.vision_service import DamageAssessment

try:
    FFMPEG = find_ffmpeg()  # el del sistema o el de imageio-ffmpeg (requirements-dron.txt)
except RuntimeError:
    FFMPEG = None
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="sin ffmpeg: pip install -r requirements-dron.txt")


# --------------------------------------------------------------------------- muestreo


def test_un_cuadro_cada_n_segundos():
    assert sample_times(0, 12, every=5, max_frames=40) == [0, 5, 10]


def test_reparte_parejo_si_se_pasa_del_tope():
    times = sample_times(0, 100, every=1, max_frames=5)
    assert times == [0, 25, 50, 75, 100]


def test_video_muy_corto_da_un_cuadro():
    assert sample_times(3, 3, every=5, max_frames=40) == [3]


def test_tope_de_un_cuadro_toma_el_del_medio():
    assert sample_times(0, 10, every=1, max_frames=1) == [5]


@pytest.mark.parametrize(("every", "max_frames"), [(0, 10), (5, 0)])
def test_parametros_invalidos(every, max_frames):
    with pytest.raises(ValueError):
        sample_times(0, 10, every=every, max_frames=max_frames)


# --------------------------------------------------------------------------- fotos sueltas


def _photo(path, gps: dict | None = None, size=(2000, 1500)):
    image = Image.new("RGB", size, (120, 110, 100))
    exif = Image.Exif()
    if gps:
        exif.get_ifd(0x8825).update(gps)
    image.save(path, exif=exif)
    return path


def test_lee_el_gps_del_exif(tmp_path):
    path = _photo(tmp_path / "a.jpg", {1: "N", 2: (4.0, 36.0, 5.5), 3: "W", 4: (74.0, 3.0, 55.0), 6: 31.5})
    lat, lon, alt = read_exif_gps(Image.open(path))
    assert lat == pytest.approx(4.601528, abs=1e-6)
    assert lon == pytest.approx(-74.065278, abs=1e-6)
    assert alt == 31.5


def test_foto_sin_gps(tmp_path):
    assert read_exif_gps(Image.open(_photo(tmp_path / "a.jpg"))) is None


def test_fotos_de_ejemplo_se_achican_y_llevan_credito(tmp_path):
    folder = tmp_path / "ejemplos"
    folder.mkdir()
    _photo(folder / "1.jpg")
    _photo(folder / "2.png")
    (folder / "notas.txt").write_text("no es imagen")
    (folder / "rota.jpg").write_bytes(b"no es una imagen")

    frames = frames_from_images([folder], tmp_path / "out", credit="UAVs-TEBDE (CC BY 4.0)")

    assert [f.image for f in frames] == ["cuadros/ejemplo_001.jpg", "cuadros/ejemplo_002.jpg"]
    assert {f.source for f in frames} == {"UAVs-TEBDE (CC BY 4.0)"}
    assert max(Image.open(tmp_path / "out" / frames[0].image).size) == 1568


# --------------------------------------------------------------------------- clasificación


def test_clasifica_en_modo_dron(tmp_path):
    frames = [Frame(image="cuadros/a.jpg", source="vuelo"), Frame(image="cuadros/b.jpg", source="vuelo")]
    calls = []

    def fake(paths, source="whatsapp"):
        calls.append((paths, source))
        if paths[0].name == "a.jpg":
            return DamageAssessment(level=DamageLevel.ROJO, confidence=0.9, notes=("techo hundido",))
        return DamageAssessment(level=None)

    classify(frames, tmp_path, classifier=fake, workers=2)

    assert {source for _, source in calls} == {"dron"}
    assert calls[0][0][0].parent == tmp_path / "cuadros"
    assert (frames[0].level, frames[0].confidence, frames[0].notes) == ("ROJO", 0.9, ["techo hundido"])
    assert (frames[1].level, frames[1].classified) == (None, True)


def test_geojson_con_y_sin_gps():
    frames = [
        Frame(image="cuadros/a.jpg", source="vuelo", t=1.0, lat=4.6, lon=-74.1, level="VERDE"),
        Frame(image="cuadros/b.jpg", source="ejemplo"),
    ]
    data = to_geojson(frames, "Vuelo")
    assert data["features"][0]["geometry"] == {"type": "Point", "coordinates": [-74.1, 4.6]}
    assert data["features"][1]["geometry"] is None
    assert data["features"][0]["properties"]["nivel"] == "VERDE"


# --------------------------------------------------------------------------- mapa


def test_el_mapa_no_deja_que_un_texto_cierre_el_script():
    frames = [Frame(image="cuadros/a.jpg", source="vuelo", notes=["</script><script>alert(1)</script>"])]
    html = render_html(frames, "Vuelo <prueba>")
    payload = re.search(r'<script type="application/json" id="datos">(.*?)</script>', html, re.DOTALL).group(1)
    assert "<" not in payload
    assert json.loads(payload)["frames"][0]["notes"] == ["</script><script>alert(1)</script>"]
    assert "<title>GeoAid · Vuelo &lt;prueba&gt;</title>" in html
    assert "window.L" in html  # Leaflet va incluido: funciona sin internet


# --------------------------------------------------------------------------- de punta a punta


def _video_with_srt(tmp_path, seconds=12):
    video = tmp_path / "DJI_0001.MP4"
    subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc=duration={seconds}:size=640x480:rate=10",
         "-pix_fmt", "yuv420p", "-y", str(video)],
        check=True,
    )  # fmt: skip
    blocks = [
        f"{i + 1}\n00:00:{i:02d},000 --> 00:00:{i:02d},100\n"
        f"[iso: 100] [latitude: {4.6 + i / 10000:.6f}] [longitude: {-74.06 - i / 10000:.6f}] [rel_alt: 30.0 abs_alt: 2650.0]\n"
        for i in range(seconds)
    ]
    video.with_suffix(".SRT").write_text("\n".join(blocks), encoding="utf-8")
    return video


@needs_ffmpeg
def test_cuadros_del_video_con_su_gps(tmp_path):
    video = _video_with_srt(tmp_path)
    frames = frames_from_video(video, video.with_suffix(".SRT"), tmp_path / "out", every=5, max_frames=40)

    assert [f.t for f in frames] == [0, 5, 10]
    assert [f.image for f in frames] == ["cuadros/cuadro_001.jpg", "cuadros/cuadro_002.jpg", "cuadros/cuadro_003.jpg"]
    assert frames[1].lat == pytest.approx(4.6005) and frames[1].lon == pytest.approx(-74.0605)
    assert all((tmp_path / "out" / f.image).exists() for f in frames)


@needs_ffmpeg
def test_cuadros_sin_srt_quedan_sin_gps(tmp_path):
    video = _video_with_srt(tmp_path, seconds=6)
    frames = frames_from_video(video, None, tmp_path / "out", every=2, max_frames=40)
    assert len(frames) == 3 and not any(f.has_gps for f in frames)


@needs_ffmpeg
def test_linea_de_comandos_sin_clasificar(tmp_path, capsys):
    video = _video_with_srt(tmp_path, seconds=6)
    out = tmp_path / "salida"

    code = cli.main(["--video", str(video), "--cada", "2", "--sin-clasificar", "--no-abrir", "--salida", str(out)])

    assert code == 0
    assert (out / "mapa.html").exists()
    data = json.loads((out / "resultados.geojson").read_text(encoding="utf-8"))
    assert len(data["features"]) == 3
    assert "3 imágenes listas, 3 con GPS" in capsys.readouterr().out


def test_linea_de_comandos_sin_clave_no_gasta(tmp_path, monkeypatch, capsys):
    folder = tmp_path / "ejemplos"
    folder.mkdir()
    _photo(folder / "1.jpg")
    monkeypatch.setattr(cli, "get_settings", lambda: type("S", (), {"ANTHROPIC_API_KEY": ""})())
    monkeypatch.setattr(cli, "classify", lambda *a, **k: pytest.fail("No debería clasificar sin clave"))

    code = cli.main(["--imagenes", str(folder), "--no-abrir", "--salida", str(tmp_path / "salida")])

    assert code == 1
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err
