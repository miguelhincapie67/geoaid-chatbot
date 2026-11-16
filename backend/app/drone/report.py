"""Mapa del vuelo para la pantalla del stand: un solo archivo HTML junto a la carpeta de cuadros.

Leaflet va incluido en el archivo, así que la ruta, los puntos y los cuadros se ven sin internet;
solo el fondo del mapa (OpenStreetMap) necesita conexión.
"""

import json
import re
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from app.drone.flight import Frame

STATIC_DIR = Path(__file__).resolve().parent / "static"


def render_html(frames: list[Frame], title: str) -> str:
    data = {
        "title": title,
        "generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "frames": [asdict(frame) for frame in frames],
    }
    # Dentro de <script> se escapa todo "<" para que ningún texto (p. ej. un hallazgo del modelo) cierre la etiqueta.
    payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    values = {
        "TITLE": _escape(title),
        "LEAFLET_CSS": (STATIC_DIR / "leaflet.css").read_text(encoding="utf-8"),
        "DATA": payload,
        "LEAFLET_JS": (STATIC_DIR / "leaflet.js").read_text(encoding="utf-8"),
    }
    # Una sola pasada sobre la plantilla: lo que se inserta no se vuelve a revisar.
    return re.sub(r"__(TITLE|LEAFLET_CSS|DATA|LEAFLET_JS)__", lambda m: values[m.group(1)], _TEMPLATE)


def write_report(frames: list[Frame], out_dir: Path, title: str) -> Path:
    path = out_dir / "mapa.html"
    path.write_text(render_html(frames, title), encoding="utf-8")
    return path


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


_TEMPLATE = """<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>GeoAid · __TITLE__</title>
<style>__LEAFLET_CSS__</style>
<style>
:root {
  --bg: #f5f3ee; --surface: #ffffff; --ink: #1c1b19; --muted: #5d5a54; --line: #e2ddd3;
  --rojo: #c62828; --amarillo: #d99a00; --verde: #2e7d32; --sin: #8a8f98; --ruta: #1f4e79;
  --radius: 14px;
}
* { box-sizing: border-box; }
html, body { margin: 0; }
body { background: var(--bg); color: var(--ink); font: 16px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
header { padding: 20px 24px 12px; }
.eyebrow { font-size: 13px; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); font-weight: 600; }
h1 { margin: 4px 0 2px; font-size: clamp(22px, 3vw, 34px); line-height: 1.15; }
h2 { margin: 0 0 10px; font-size: 18px; }
.sub { margin: 0; color: var(--muted); }
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.chip { display: inline-flex; align-items: center; gap: 8px; padding: 6px 12px; border-radius: 999px; background: var(--surface); border: 1px solid var(--line); font-weight: 600; }
.dot { width: 12px; height: 12px; border-radius: 50%; flex: none; }
main { display: grid; grid-template-columns: minmax(0, 1.7fr) minmax(280px, 1fr); gap: 16px; padding: 8px 24px 16px; }
.panel { background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden; }
#map { height: min(72vh, 760px); min-height: 360px; }
.nomap { padding: 32px; color: var(--muted); }
aside { display: flex; flex-direction: column; max-height: min(72vh, 760px); min-height: 360px; }
aside h2 { padding: 14px 16px 0; }
ol.lista { list-style: none; margin: 0; padding: 0 8px 8px; overflow-y: auto; }
.item { display: grid; grid-template-columns: 92px 1fr; gap: 10px; width: 100%; padding: 8px; border: 0; background: none; text-align: left; font: inherit; color: inherit; border-radius: 10px; cursor: pointer; }
.item:hover, .item:focus-visible { background: var(--bg); outline: none; }
.item img, .card img { width: 100%; aspect-ratio: 4 / 3; object-fit: cover; border-radius: 8px; background: var(--line); display: block; }
.badge { display: inline-flex; align-items: center; gap: 6px; font-weight: 700; font-size: 14px; }
.meta { font-size: 13px; color: var(--muted); }
.nota { font-size: 14px; margin-top: 2px; overflow: hidden; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
section.ejemplos { padding: 0 24px 16px; }
.credit { color: var(--muted); margin: -4px 0 12px; font-size: 14px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 14px; }
.card { padding: 10px; cursor: pointer; }
.card:hover { border-color: var(--muted); }
footer { padding: 4px 24px 24px; color: var(--muted); font-size: 14px; max-width: 980px; }
.visor { position: fixed; inset: 0; background: rgba(15, 15, 14, .78); display: grid; place-items: center; padding: 16px; z-index: 2000; }
.visor[hidden] { display: none; }
.visor .caja { background: var(--surface); border-radius: var(--radius); max-width: min(1100px, 100%); max-height: 100%; overflow: auto; display: grid; grid-template-columns: minmax(0, 2fr) minmax(240px, 1fr); }
.visor img { width: 100%; height: 100%; max-height: 82vh; object-fit: contain; background: #111; display: block; }
.visor .detalle { padding: 18px; }
.visor ul { padding-left: 18px; margin: 8px 0; }
.cerrar { float: right; border: 1px solid var(--line); background: var(--surface); border-radius: 999px; padding: 4px 12px; font: inherit; cursor: pointer; }
@media (max-width: 860px) {
  main { grid-template-columns: 1fr; padding: 8px 16px 16px; }
  header, section.ejemplos, footer { padding-left: 16px; padding-right: 16px; }
  aside { max-height: none; }
  .visor .caja { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<header>
  <div class="eyebrow">GeoAid · Verificación por dron</div>
  <h1>__TITLE__</h1>
  <p class="sub" id="sub"></p>
  <div class="chips" id="chips"></div>
</header>
<main>
  <section class="panel"><div id="map"></div><div class="nomap" id="nomap" hidden>Estas imágenes no traen GPS, así que no se pueden ubicar en el mapa. Están en la lista y abajo en la galería.</div></section>
  <aside class="panel"><h2>Cuadros, de más grave a menos</h2><ol class="lista" id="lista"></ol></aside>
</main>
<section class="ejemplos" id="ejemplos" hidden>
  <h2>Ejemplos de sismos reales</h2>
  <p class="credit" id="credito"></p>
  <div class="grid" id="galeria"></div>
</section>
<footer>Clasificación preliminar con inteligencia artificial para priorizar las visitas técnicas. No reemplaza la inspección de un ingeniero. Verde significa "sin daño visible desde el aire", no que la edificación sea habitable.</footer>
<div class="visor" id="visor" hidden role="dialog" aria-modal="true" aria-label="Detalle del cuadro">
  <div class="caja"><img id="visor-img" alt=""><div class="detalle" id="visor-detalle"></div></div>
</div>
<script type="application/json" id="datos">__DATA__</script>
<script>__LEAFLET_JS__</script>
<script>
(function () {
  "use strict";
  var data = JSON.parse(document.getElementById("datos").textContent);
  var css = getComputedStyle(document.documentElement);
  var LEVELS = {
    ROJO: { name: "Rojo", desc: "posible riesgo de colapso", color: css.getPropertyValue("--rojo").trim(), rank: 0 },
    AMARILLO: { name: "Amarillo", desc: "daño moderado", color: css.getPropertyValue("--amarillo").trim(), rank: 1 },
    VERDE: { name: "Verde", desc: "sin daño visible", color: css.getPropertyValue("--verde").trim(), rank: 2 },
    NONE: { name: "Sin clasificar", desc: "no se pudo evaluar", color: css.getPropertyValue("--sin").trim(), rank: 3 }
  };
  function lvl(f) { return LEVELS[f.level] || LEVELS.NONE; }
  function el(tag, cls, text) { var n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; }
  function dot(color) { var d = el("span", "dot"); d.style.background = color; return d; }
  function badge(f) { var b = el("span", "badge"); var l = lvl(f); b.appendChild(dot(l.color)); b.appendChild(document.createTextNode(l.name)); return b; }
  function hasGps(f) { return f.lat != null && f.lon != null; }
  function meta(f) {
    var parts = [];
    if (f.t != null) parts.push("segundo " + f.t.toFixed(1));
    if (hasGps(f)) parts.push(f.lat.toFixed(5) + ", " + f.lon.toFixed(5));
    if (f.alt != null) parts.push(Math.round(f.alt) + " m");
    if (f.confidence != null) parts.push("confianza " + Math.round(f.confidence * 100) + " %");
    return parts.join(" · ");
  }

  var frames = data.frames;
  var vuelo = frames.filter(function (f) { return f.source === "vuelo"; });
  var ejemplos = frames.filter(function (f) { return f.source !== "vuelo"; });
  var ordered = frames.slice().sort(function (a, b) { return lvl(a).rank - lvl(b).rank || (a.t || 0) - (b.t || 0); });

  // Resumen
  var conGps = frames.filter(hasGps).length;
  var sub = [];
  if (vuelo.length) sub.push(vuelo.length + " cuadros del vuelo");
  if (ejemplos.length) sub.push(ejemplos.length + " imágenes de ejemplo");
  sub.push(conGps + " con GPS");
  sub.push("generado " + data.generated);
  document.getElementById("sub").textContent = sub.join(" · ");
  var chips = document.getElementById("chips");
  ["ROJO", "AMARILLO", "VERDE", "NONE"].forEach(function (key) {
    var n = frames.filter(function (f) { return (LEVELS[f.level] ? f.level : "NONE") === key; }).length;
    if (!n && key === "NONE") return;
    var c = el("span", "chip"); c.appendChild(dot(LEVELS[key].color));
    c.appendChild(document.createTextNode(n + " " + LEVELS[key].name.toLowerCase() + " · " + LEVELS[key].desc));
    chips.appendChild(c);
  });

  // Visor
  var visor = document.getElementById("visor");
  function abrir(f) {
    document.getElementById("visor-img").src = f.image;
    document.getElementById("visor-img").alt = "Cuadro " + lvl(f).name;
    var d = document.getElementById("visor-detalle"); d.textContent = "";
    var cerrar = el("button", "cerrar", "Cerrar"); cerrar.type = "button"; cerrar.onclick = cerrarVisor; d.appendChild(cerrar);
    var b = badge(f); b.style.fontSize = "20px"; d.appendChild(b);
    d.appendChild(el("p", "meta", lvl(f).desc));
    if (meta(f)) d.appendChild(el("p", "meta", meta(f)));
    if (f.notes && f.notes.length) { var ul = el("ul"); f.notes.forEach(function (n) { ul.appendChild(el("li", null, n)); }); d.appendChild(ul); }
    else if (!f.classified) d.appendChild(el("p", "meta", "Este cuadro no se envió a clasificar."));
    if (f.source !== "vuelo") d.appendChild(el("p", "meta", "Fuente: " + f.source));
    visor.hidden = false; cerrar.focus();
  }
  function cerrarVisor() { visor.hidden = true; }
  visor.addEventListener("click", function (e) { if (e.target === visor) cerrarVisor(); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") cerrarVisor(); });

  // Mapa
  var map = null, markers = new Map();
  var gpsFrames = frames.filter(hasGps);
  if (gpsFrames.length && window.L) {
    map = L.map("map", { scrollWheelZoom: true });
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19, attribution: "&copy; OpenStreetMap"
    }).addTo(map);
    var ruta = vuelo.filter(hasGps).sort(function (a, b) { return a.t - b.t; }).map(function (f) { return [f.lat, f.lon]; });
    if (ruta.length > 1) L.polyline(ruta, { color: css.getPropertyValue("--ruta").trim(), weight: 3, opacity: .7, dashArray: "6 6" }).addTo(map);
    gpsFrames.slice().sort(function (a, b) { return lvl(b).rank - lvl(a).rank; }).forEach(function (f) {
      var m = L.circleMarker([f.lat, f.lon], { radius: 10, color: "#fff", weight: 2, fillColor: lvl(f).color, fillOpacity: 1 })
        .addTo(map).on("click", function () { abrir(f); });
      m.bindTooltip(lvl(f).name + (f.t != null ? " · seg " + f.t.toFixed(1) : ""));
      markers.set(f, m);
    });
    map.fitBounds(L.latLngBounds(gpsFrames.map(function (f) { return [f.lat, f.lon]; })).pad(0.25), { maxZoom: 19 });
  } else {
    document.getElementById("map").hidden = true;
    document.getElementById("nomap").hidden = false;
  }

  // Lista
  var lista = document.getElementById("lista");
  ordered.forEach(function (f) {
    var li = el("li"); var btn = el("button", "item"); btn.type = "button";
    var img = el("img"); img.src = f.image; img.alt = ""; img.loading = "lazy"; btn.appendChild(img);
    var txt = el("div"); txt.appendChild(badge(f));
    if (meta(f)) txt.appendChild(el("div", "meta", meta(f)));
    if (f.notes && f.notes.length) txt.appendChild(el("div", "nota", f.notes[0]));
    if (f.source !== "vuelo") txt.appendChild(el("div", "meta", "Ejemplo · " + f.source));
    btn.appendChild(txt);
    btn.onclick = function () {
      if (map && markers.has(f)) map.flyTo([f.lat, f.lon], Math.max(map.getZoom(), 18), { duration: .6 });
      abrir(f);
    };
    li.appendChild(btn); lista.appendChild(li);
  });

  // Galería de ejemplos
  if (ejemplos.length) {
    document.getElementById("ejemplos").hidden = false;
    var creditos = Array.from(new Set(ejemplos.map(function (f) { return f.source; })));
    document.getElementById("credito").textContent = "Imágenes de: " + creditos.join(" · ");
    var galeria = document.getElementById("galeria");
    ejemplos.slice().sort(function (a, b) { return lvl(a).rank - lvl(b).rank; }).forEach(function (f) {
      var card = el("div", "panel card"); card.tabIndex = 0;
      var img = el("img"); img.src = f.image; img.alt = ""; img.loading = "lazy"; card.appendChild(img);
      var b = badge(f); b.style.marginTop = "8px"; card.appendChild(b);
      if (f.notes && f.notes.length) card.appendChild(el("div", "nota", f.notes[0]));
      card.onclick = function () { abrir(f); };
      card.onkeydown = function (e) { if (e.key === "Enter") abrir(f); };
      galeria.appendChild(card);
    });
  }
})();
</script>
</body>
</html>
"""
