"""Recuadros por edificación (app/drone/boxes.py) y su seguimiento en video (app/drone/tracking.py), sin la API real."""

import base64
import io
import json
from argparse import Namespace
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from app.drone import boxes
from app.drone.boxes import Box, box_corners, draw_overlay, parse_boxes


def _response(data) -> SimpleNamespace:
    text = data if isinstance(data, str) else json.dumps(data)
    return SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn",
    )


def _item(**changes):
    item = {"x1": 100, "y1": 200, "x2": 400, "y2": 600, "nivel": "ROJO", "confianza": 0.9, "etiqueta": "colapso total"}
    return item | changes


# --------------------------------------------------------------------------- respuesta de Claude


def test_convierte_coordenadas_de_0_a_1000_en_fracciones():
    [box] = parse_boxes(_response({"edificaciones": [_item()]}))
    assert box == Box(0.1, 0.2, 0.4, 0.6, "ROJO", 0.9, "colapso total")


def test_endereza_esquinas_invertidas_y_recorta_lo_que_se_sale():
    [box] = parse_boxes(_response({"edificaciones": [_item(x1=1200, x2=900, y1=-50, y2=300)]}))
    assert (box.x1, box.x2, box.y1, box.y2) == (0.9, 1.0, 0.0, 0.3)


def test_descarta_recuadros_diminutos_o_incompletos():
    items = [_item(x2=105), {"nivel": "ROJO"}, "texto suelto"]
    assert parse_boxes(_response({"edificaciones": items})) == []


@pytest.mark.parametrize(("nivel", "confianza", "esperado"), [("rojo", 0.9, "ROJO"), ("NARANJA", 0.9, "SIN_CLASIFICAR"), ("VERDE", 0.2, "SIN_CLASIFICAR")])
def test_nivel_raro_o_poca_confianza_queda_sin_clasificar(nivel, confianza, esperado):
    [box] = parse_boxes(_response({"edificaciones": [_item(nivel=nivel, confianza=confianza)]}))
    assert box.level == esperado


def test_lo_mas_grave_va_primero():
    items = [_item(nivel="VERDE"), _item(nivel="ROJO"), _item(nivel="AMARILLO")]
    assert [b.level for b in parse_boxes(_response({"edificaciones": items}))] == ["ROJO", "AMARILLO", "VERDE"]


def test_respuesta_sin_json_es_none():
    assert parse_boxes(_response("no sé")) is None
    assert parse_boxes(_response({"otra_cosa": []})) is None


def test_sin_clave_no_llama_a_la_api(tmp_path, monkeypatch):
    monkeypatch.setattr(boxes, "get_settings", lambda: SimpleNamespace(ANTHROPIC_API_KEY=""))
    assert boxes.detect_buildings(tmp_path / "x.jpg") is None


def test_el_prompt_usa_los_mismos_criterios_del_semaforo():
    assert "Columnas o vigas fracturadas" in boxes.BOXES_PROMPT
    assert "SIN_CLASIFICAR:" not in boxes._CRITERIA


# --------------------------------------------------------------------------- dibujo


def test_la_imagen_para_claude_lleva_cuadricula(tmp_path):
    photo = tmp_path / "cuadro.jpg"
    Image.new("RGB", (3000, 1500), "black").save(photo)
    block = boxes._image_with_grid(photo)
    assert block["source"]["media_type"] == "image/jpeg"
    sent = Image.open(io.BytesIO(base64.b64decode(block["source"]["data"])))
    assert max(sent.size) == 1568
    assert sent.convert("L").getpixel((round(sent.width / 2), round(sent.height * 0.75))) > 20  # la línea del 500


def test_las_etiquetas_no_se_pisan():
    image = Image.new("RGB", (1920, 1080), "white")
    same = [Box(0.3, 0.4, 0.5, 0.6, level, 0.9, "colapso total") for level in ("ROJO", "AMARILLO", "VERDE")]
    taken = [boxes._hud(ImageDraw.Draw(Image.new("RGBA", (1920, 1080))), 1920, [], boxes._font(27), 1.0, None)]
    draw = ImageDraw.Draw(Image.new("RGBA", (1920, 1080)))
    for box in same:
        boxes._label(draw, box_corners(box, 1920, 1080), box, boxes._font(30), 1.0, (1920, 1080), taken)
    labels = taken[1:]
    assert len(labels) == 3
    assert not any(boxes._overlaps(a, b) for i, a in enumerate(labels) for b in labels[i + 1 :])
    assert draw_overlay(image, [(box_corners(b, 1920, 1080), b) for b in same]).size == (1920, 1080)


def test_dibuja_recuadro_con_el_color_del_nivel():
    image = Image.new("RGB", (800, 450), "white")
    box = Box(0.25, 0.4, 0.75, 0.9, "ROJO", 0.9, "colapso")
    out = draw_overlay(image, [(box_corners(box, 800, 450), box)])
    assert out.size == (800, 450)
    red, green, blue = out.getpixel((200, 300))  # sobre el borde izquierdo del recuadro
    assert red > 150 and green < 100 and blue < 120


def test_foto_con_recuadros(tmp_path, monkeypatch):
    photo = tmp_path / "cuadro.jpg"
    Image.new("RGB", (640, 360), "gray").save(photo)
    found = [Box(0.1, 0.3, 0.5, 0.9, "AMARILLO", 0.7, "techo")]
    monkeypatch.setattr(boxes, "detect_buildings", lambda path, effort="low": found)
    out, result = boxes.annotate_photo(photo)
    assert out.name == "cuadro_cajas.jpg" and out.exists() and result == found


# --------------------------------------------------------------------------- seguimiento en video

cv2 = pytest.importorskip("cv2", reason="sin OpenCV: pip install -r requirements-dron.txt")
np = pytest.importorskip("numpy")
from app.drone import tracking
from app.drone.flight import find_ffmpeg

try:
    HAS_FFMPEG = bool(find_ffmpeg())
except RuntimeError:
    HAS_FFMPEG = False


def _texture(width=1400, height=800, seed=1) -> np.ndarray:
    """Una 'ciudad' falsa con bordes y esquinas para que ORB encuentre puntos."""
    rng = np.random.default_rng(seed)
    image = Image.new("RGB", (width, height), (90, 90, 90))
    draw = ImageDraw.Draw(image)
    for _ in range(600):
        x, y = rng.integers(0, width), rng.integers(0, height)
        w, h = rng.integers(10, 60), rng.integers(10, 60)
        draw.rectangle((x, y, x + w, y + h), fill=tuple(int(c) for c in rng.integers(0, 255, 3)))
    return cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)


def _write_video(path, frames, fps=10):
    height, width = frames[0].shape[:2]
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    for frame in frames:
        writer.write(frame)
    writer.release()


@pytest.fixture
def paneo(tmp_path):
    """Video de 3 s: la cámara se corre 4 px por cuadro y en el cuadro 20 corta a otra escena."""
    city, other = _texture(seed=1), _texture(seed=2)
    frames = [city[100:460, 100 + 4 * i : 740 + 4 * i].copy() for i in range(20)]
    frames += [other[100:460, 100 + 4 * i : 740 + 4 * i].copy() for i in range(10)]
    path = tmp_path / "paneo.mp4"
    _write_video(path, frames)
    return path


def test_sigue_el_movimiento_y_encuentra_el_corte(paneo):
    motion = tracking.estimate_motion(paneo)
    assert motion.frame_count == 30
    assert tracking.scenes(motion) == [(0, 20), (20, 30)]
    shifts = [step[0, 2] for step in motion.steps[1:20]]
    assert all(abs(dx + 4) < 1.0 for dx in shifts)  # la imagen se corre 4 px a la izquierda


def test_cuadros_clave_al_empezar_cada_escena_y_cada_tanto():
    keys = tracking.pick_keyframes([(0, 100), (100, 103), (103, 160)], fps=10, every_s=3, max_keys=30)
    assert keys == [4, 34, 64, 94, 107, 137]  # la escena de 3 cuadros es muy corta y queda sin recuadros
    assert tracking.pick_keyframes([(0, 100), (103, 160)], fps=10, every_s=3, max_keys=2) == [4, 107]


def test_el_recuadro_se_mueve_con_la_imagen(paneo):
    motion = tracking.estimate_motion(paneo)
    box = Box(0.5, 0.5, 0.6, 0.6, "ROJO", 0.9, "x")
    plan = tracking._frame_plan(motion, {10: [box], 25: []})
    [(corners, _)] = tracking._shapes_for(plan[0], motion.width, motion.height)
    # En el cuadro 0 la cámara estaba 40 px más a la izquierda: la casa se veía 40 px más a la derecha.
    assert corners[0][0] == pytest.approx(0.5 * 640 + 40, abs=2)
    assert 25 not in plan  # la segunda escena no tiene edificaciones


@pytest.mark.skipif(not HAS_FFMPEG, reason="sin ffmpeg: pip install -r requirements-dron.txt")
def test_video_completo_con_detector_falso(paneo, tmp_path, monkeypatch):
    monkeypatch.setattr(tracking, "BACKEND_DIR", tmp_path)
    calls = []

    def detector(path):
        calls.append(path.name)
        return [Box(0.2, 0.2, 0.5, 0.6, "AMARILLO", 0.8, "techo")]

    args = Namespace(video=paneo, nombre="prueba", cada=1.0, max_cuadros=10, de_nuevo=False, si=True, no_abrir=True)
    assert tracking.run_video(args, "low", detector=detector) == 0
    out_dir = tmp_path / "data" / "vuelos" / "prueba"
    assert (out_dir / "video_cajas.mp4").stat().st_size > 0
    saved = json.loads((out_dir / "cajas.json").read_text(encoding="utf-8"))
    assert saved["video"] == "paneo.mp4" and len(saved["cuadros_clave"]) == len(calls) > 0

    # La segunda vez usa lo guardado y no vuelve a llamar.
    calls.clear()
    assert tracking.run_video(args, "low", detector=detector) == 0
    assert calls == []
