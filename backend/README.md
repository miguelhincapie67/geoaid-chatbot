# GeoAid: backend del chatbot de WhatsApp

Backend en FastAPI que recibe por WhatsApp (Meta Cloud API) los reportes de **viviendas** y **negocios (pymes)** afectados por el terremoto. El bot guía al ciudadano paso a paso, casi todo con botones y listas.

**Vivienda** (unos 5 minutos):

1. **Autorización** de datos (Ley 1581) y **tipo de reporte** (Mi vivienda / Mi negocio).
2. **Ubicación:** ¿está en la vivienda?, GPS y **zona urbana o rural**.
   - **Urbana:** dirección y barrio, y municipio de una lista de 13 en dos páginas (o "Otro municipio").
   - **Rural:** vereda, corregimiento o finca, y el pueblo más cercano escrito. No se pregunta el estrato.
3. **Situación de emergencia:** ¿pueden habitar la casa?, heridos (con aviso de la línea 123), agua y luz, y necesidad más urgente.
4. **Hogar:** estrato, número de personas, población vulnerable (8 grupos), pertenencia étnica (opcional) y tenencia.
5. **Identidad:** tipo de documento. Con cédula, foto + OCR, o el número escrito si no la tiene a mano. Si no envió foto del documento, se ofrece una **selfie opcional** con autorización aparte por ser un dato biométrico.
6. **Fotos del daño** (de 1 a 3).

**Negocio.** Toma de 7 a 8 minutos si reporta un empleado y de 10 a 12 si reporta el dueño. Se reutilizan la ubicación, heridos, servicios, la identidad y las fotos:

1. **El negocio:** nombre y **relación de quien reporta** (dueño, representante legal, socio, gerente, directivo, contador, empleado, familiar u otro). Luego el tipo de local, si funciona dentro de la vivienda y si puede seguir funcionando.
2. **El local:** daño en la estructura (sin daño, menor, grave o colapso). Si el daño es grave, el bot pide no entrar al local. Si el negocio funciona parcialmente o está cerrado temporalmente, también pregunta en cuánto tiempo podrá volver a funcionar normal.
3. **La empresa:**
   - sector económico, antigüedad y número de trabajadores (con eso se calcula si es micro, pequeña o mediana);
   - cuántos no pueden trabajar ahora;
   - tenencia del local y si vende por WhatsApp, redes o domicilios.
4. **Obligaciones y finanzas.** Solo para dueño, representante, socio, gerente, directivo o contador. Empieza con un aviso: estos datos no se comparten con la DIAN ni con la alcaldía. Pregunta por:
   - el Registro Mercantil y su renovación;
   - el tipo de persona y el NIT (solo si está registrado);
   - si está al día con el RUT, la facturación electrónica, la seguridad social (solo si tiene empleados), el ICA y el predial (solo si el local es propio);
   - las ventas mensuales y las deudas (banco, cooperativa, proveedores, gota a gota o familiares);
   - dónde puede recibir un apoyo en dinero.
5. **Pérdidas y necesidades:**
   - si lo lidera una mujer, un joven, una víctima, una persona con discapacidad, étnica o migrante;
   - qué se perdió y su valor aproximado;
   - si tiene seguro;
   - **todas** las necesidades para reactivarse (selección múltiple), y si marca varias, cuál es la más urgente.
6. **Representante legal:** si quien reporta no es el dueño ni el representante, da el nombre y el documento del representante. Después va la identidad de quien reporta.

Si el negocio funciona en la vivienda, el menú final ofrece **"Reportar mi vivienda"**, que copia la ubicación del negocio y salta directo a la situación del hogar.

Las preguntas opcionales se pueden **saltar** con la opción "Saltar" o escribiendo *saltar*. Cada pregunta saltada queda en `reports.skipped_questions`. No se pueden saltar:
- la autorización, el tipo de reporte, la zona y el municipio;
- en negocios, el nombre, la relación de quien reporta y el tipo de local;
- la identidad ni las fotos.

Las preguntas que no aplican se omiten sin quedar como saltadas. Por ejemplo: el estrato en zona rural, el bloque de obligaciones si reporta un empleado, el NIT de un negocio no registrado, el predial de un local arrendado y el valor de las pérdidas si no perdió nada.

Al terminar, entrega un código de seguimiento de 8 caracteres. Cada reporte queda **pendiente de revisión humana**, con alertas automáticas que no bloquean nada. Los datos anonimizados se publican para el mapa de la web del equipo.

## Demo local (costo 0)

Todos los comandos se ejecutan dentro de `backend/`.

1. **Primera vez:**
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\python -m pip install -r requirements-dev.txt
   copy .env.example .env    # y completar los valores (ver "Configuración en Meta")
   ```
2. **Arrancar el bot:** `.\run_demo.ps1`. Aplica las migraciones, arranca uvicorn sin `--reload` y guarda los logs en `logs/`.
3. **En otra terminal, el túnel:** `ngrok http --url=<tu-dominio>.ngrok-free.app 8000`.
4. **Comprobar:** `http://localhost:8000/health` → `{"status": "ok"}`.

**Comandos especiales en el chat:**
- `cancelar`: descarta el reporte en curso.
- `ayuda`: muestra las opciones de ayuda.
- `reiniciar demo`: solo funciona desde los números en `DEMO_PHONES`. Deja el celular como nuevo para el siguiente visitante y conserva los reportes ya enviados.

## Configuración en Meta (gratis)

| Variable | Dónde se obtiene |
|---|---|
| `WHATSAPP_TOKEN` | Token **permanente** de un *System User* (Business Manager → Usuarios del sistema → Generar token, con `whatsapp_business_messaging` y `whatsapp_business_management`, caducidad "Nunca") |
| `WHATSAPP_PHONE_NUMBER_ID` | WhatsApp → Configuración de la API → *Phone number ID* |
| `WHATSAPP_APP_SECRET` | Configuración de la app → Básica → Clave secreta de la app |
| `WEBHOOK_VERIFY_TOKEN` | Un texto largo y aleatorio. El mismo valor va en Meta al registrar el webhook |
| `DEMO_PHONES` | Los celulares registrados como destinatarios de prueba (máximo 5 con el número de prueba) |

Para registrar el webhook: WhatsApp → Configuración → Webhook. La URL es `https://<tu-dominio>.ngrok-free.app/api/v1/whatsapp/webhook` y hay que suscribirse al campo **messages**.

## Para el equipo web: reportes en vivo

Ambos endpoints son de solo lectura y no requieren autenticación. **No** incluyen datos personales ni sensibles: nombre, documento, teléfono, dirección, fotos, código de seguimiento, pertenencia étnica, estrato ni el detalle de los grupos vulnerables.

De cada negocio tampoco publican el nombre, el NIT, el representante legal, el rol de quien reporta, las ventas, el valor de las pérdidas, el liderazgo, las obligaciones, las deudas ni la cuenta. De esos datos solo se publican totales en `/stats`.

`GET /api/v1/reports/public?limit=500` devuelve los reportes enviados, del más reciente al más antiguo:

```json
[
  {
    "id": 12,
    "report_type": "VIVIENDA",
    "municipality": "Popayán, Cauca",
    "zone": "URBANA",
    "lat": 2.445, "lon": -76.615,
    "damage_level": "ROJO",
    "status": "PENDIENTE_REVISION",
    "submitted_at": "2026-11-17T15:04:05",
    "household_size": 4,
    "has_vulnerable": true,
    "displaced": true,
    "injured": false,
    "urgent_need": "ALBERGUE",
    "business_sector": null, "business_size": null, "business_closed": null,
    "jobs_at_risk": null, "business_need": null
  },
  {
    "id": 13,
    "report_type": "NEGOCIO",
    "municipality": "Popayán, Cauca",
    "zone": "URBANA",
    "lat": 2.443, "lon": -76.606,
    "damage_level": "AMARILLO",
    "status": "PENDIENTE_REVISION",
    "submitted_at": "2026-11-17T15:20:11",
    "household_size": null,
    "has_vulnerable": false,
    "displaced": false,
    "injured": false,
    "urgent_need": null,
    "business_sector": "COMERCIO",
    "business_size": "MICRO",
    "business_closed": true,
    "jobs_at_risk": 3,
    "business_need": "NOMINA",
    "business_needs": ["CREDITO", "NOMINA", "INVENTARIO"],
    "structural_damage": "GRAVE"
  }
]
```

- `report_type`: `VIVIENDA` o `NEGOCIO`. Conviene usar un ícono distinto en el mapa para los negocios.
- Los campos `business_*` y `jobs_at_risk` solo vienen en los negocios (`null` en las viviendas).
  - `business_size`: `MICRO`, `PEQUENA`, `MEDIANA` o `GRANDE`, según el número de trabajadores.
  - `business_closed`: el negocio está cerrado temporal o definitivamente.
  - `business_sector`: `COMERCIO`, `ALIMENTOS`, `INDUSTRIA`, `AGROPECUARIO`, `TURISMO`, `SERVICIOS`, `BELLEZA_SALUD`, `TRANSPORTE` u `OTRO`.
  - `business_needs`: todas las necesidades marcadas. `business_need` es la más urgente. Valores: `CREDITO`, `SUBSIDIO`, `NOMINA`, `REPARACION`, `MAQUINARIA`, `INVENTARIO`, `ARRIENDO`, `REUBICACION`, `ASESORIA` y `MERCADOS`.
  - `structural_damage`: `SIN_DANO`, `MENOR`, `GRAVE` o `COLAPSO`. Conviene destacar `GRAVE` y `COLAPSO` en el mapa.

- `lat` y `lon` vienen redondeados a unos 100 m y pueden ser `null` si el ciudadano no compartió su GPS. En ese caso, usar `municipality`.
- `damage_level` puede ser `VERDE`, `AMARILLO`, `ROJO` o `null` (todavía en análisis).
- `displaced`: el hogar no puede habitar la vivienda (está en un albergue, con familiares o a la intemperie).
- `injured`: se reportaron personas heridas. Conviene destacarlo en el mapa.
- `urgent_need`: `ALBERGUE`, `ALIMENTOS`, `AGUA`, `MEDICAMENTOS`, `ASEO`, `ROPA` o `NINGUNA`.

`GET /api/v1/reports/stats` devuelve los totales:

```json
{ "total_reports": 37, "total_households": 30, "people_affected": 142, "vulnerable_households": 21,
  "displaced_households": 12, "injured_reports": 3,
  "by_damage_level": { "VERDE": 10, "AMARILLO": 15, "ROJO": 8, "SIN_CLASIFICAR": 4 },
  "by_urgent_need": { "ALBERGUE": 9, "ALIMENTOS": 14, "AGUA": 5, "MEDICAMENTOS": 3, "ASEO": 2, "ROPA": 1, "NINGUNA": 3 },
  "businesses": {
    "total": 7, "closed": 4, "informal": 3, "jobs_at_risk": 19,
    "sells_online": 5, "with_payment_account": 4, "informal_lending": 1,
    "by_sector": { "COMERCIO": 4, "ALIMENTOS": 2, "INDUSTRIA": 1, "...": 0 },
    "by_size": { "MICRO": 6, "PEQUENA": 1, "MEDIANA": 0, "GRANDE": 0 },
    "by_need": { "CREDITO": 5, "INVENTARIO": 4, "NOMINA": 2, "...": 0 },
    "by_top_need": { "CREDITO": 3, "INVENTARIO": 2, "...": 0 },
    "needs_by_size": { "MICRO": { "CREDITO": 4, "INVENTARIO": 4, "...": 0 }, "PEQUENA": { "NOMINA": 1, "...": 0 } },
    "by_structural_damage": { "SIN_DANO": 1, "MENOR": 3, "GRAVE": 2, "COLAPSO": 1 },
    "compliance": {
      "registro_mercantil": { "RENOVADO": 2, "SIN_RENOVAR": 1, "NO": 3, "NO_SABE": 0 },
      "rut": { "AL_DIA": 3, "PENDIENTE": 1, "NO_SABE": 0, "NO_APLICA": 0 },
      "facturacion_electronica": { "...": 0 }, "seguridad_social": { "...": 0 },
      "ica": { "...": 0 }, "predial": { "...": 0 } } } }
```

- `by_need` cuenta cada necesidad marcada (un negocio puede sumar en varias). `by_top_need` cuenta solo la más urgente de cada negocio.
- `needs_by_size` sirve para asignar los apoyos según el tamaño de la empresa: por ejemplo, cuántas microempresas necesitan crédito.
- `compliance` y las finanzas solo incluyen los negocios que reportó alguien con poder de decisión.

Las cifras de hogares (`people_affected`, `vulnerable_households`, `displaced_households`, `by_urgent_need`) cuentan solo viviendas. `total_reports`, `injured_reports` y `by_damage_level` cuentan ambos tipos.

## Dónde se guardan los datos

Todo queda **solo en el computador donde corre el bot**. Nada se sube a git. La única excepción son las **fotos del daño**: se envían a la API de Claude (Anthropic) para el semáforo y no se guardan en otro lado. La cédula y la selfie nunca salen del computador.

| Qué | Dónde |
|---|---|
| Respuestas del ciudadano, reportes y alertas | `backend/geoaid.db` (SQLite). Se puede abrir con *DB Browser for SQLite* |
| Fotos de cédula, selfies y daños | `backend/data/media/<teléfono>/<id del reporte>/` |
| Registros del servidor | `backend/logs/` |

Las tablas principales son:
- `users`: la persona y su identidad;
- `reports`: un reporte por vivienda o negocio, con la columna `report_type`;
- `businesses`: los datos propios de cada negocio, en relación 1:1 con `reports`;
- `media_files`: las fotos;
- `report_alerts`: las alertas para el revisor. En negocios, además de las generales, están:
  - `NEGOCIO_CERRADO`, `NEGOCIO_INFORMAL`, `PERDIDA_ALTA` y `NIT_DUPLICADO`;
  - `RIESGO_ESTRUCTURAL`: daño grave y el negocio sigue funcionando;
  - `PRESTAMO_INFORMAL`: tiene deudas con un gota a gota;
  - `OBLIGACIONES_PENDIENTES`: detalla cuáles no están al día;
- `processed_messages`: para descartar mensajes duplicados.

Antes del evento conviene copiar `geoaid.db` y `data/` como respaldo. **Después del evento hay que borrarlos**, como promete el texto de autorización.

**Con ngrok gratis**, cada `fetch` debe incluir el encabezado `ngrok-skip-browser-warning: true`; si no, ngrok devuelve su página de advertencia en vez del JSON. Consultar cada 5 a 10 segundos. CORS ya permite `https://geo-aid-coral.vercel.app` y `localhost:3000`.

```js
const res = await fetch(`${BOT_URL}/api/v1/reports/public`, {
  headers: { "ngrok-skip-browser-warning": "true" },
});
```

## Estructura

| Ruta | Qué hace |
|---|---|
| `app/main.py` | Crea la app (`create_app`), las rutas, CORS y `/health` |
| `app/config.py` | Variables de entorno |
| `app/content.py` | **Todos los textos** del bot, los municipios y los enlaces a la web |
| `app/bot/router.py` | Webhook de Meta (`GET` handshake y `POST` eventos) |
| `app/bot/state_manager.py` | Máquina de estados de la conversación |
| `app/bot/meta_client.py` | Envío de mensajes y descarga de fotos (Graph API) |
| `app/api/public.py` | Endpoints anonimizados para la web |
| `app/services/ocr_service.py` | OCR de cédula. **Simulado**: lo reemplaza el equipo de OCR |
| `app/services/vision_service.py` | Semáforo de daño con Claude (ver "Semáforo de daño") |
| `app/services/alerts.py` | Reglas de alertas para el revisor |
| `app/drone/` | Módulo del dron: cuadros del video + GPS del `.SRT` → semáforo → mapa (ver "Módulo del dron") |
| `data/media/` | Fotos guardadas. **Privada**: no se publica y no se sube a git |
| `data/vuelos/` | Resultados del módulo del dron. **Privada**: no se sube a git |

**Integrar el OCR real:** reemplaza el cuerpo de `extract_id_data` manteniendo su firma; el contrato está documentado en el archivo. El bot ejecuta como máximo 2 análisis a la vez y le avisa al ciudadano mientras espera.

## Semáforo de daño

Al recibir las fotos del daño, `analyze_building_damage` se las envía a Claude junto con los criterios del semáforo y guarda en el reporte:

- `damage_level`: `VERDE`, `AMARILLO`, `ROJO` o `null` (sin clasificar).
- `damage_confidence`: de 0 a 1.

Lo que vio el modelo ("grieta diagonal en muro de carga", etc.) queda en los logs del bot.

Es una clasificación **preliminar para priorizar visitas**: el reporte sigue pendiente de revisión humana y el bot **no** le dice el color al ciudadano. Queda sin clasificar si las fotos no muestran la edificación, si la confianza es menor que 0,4, si la API falla o si no hay `ANTHROPIC_API_KEY` en el `.env`.

Para configurarlo, crea una clave en [platform.claude.com](https://platform.claude.com), cárgale créditos y ponla en `ANTHROPIC_API_KEY`. El modelo se cambia con `VISION_MODEL`.

Para probar con fotos sueltas, sin WhatsApp:

```powershell
.\.venv\Scripts\python -m app.services.vision_service foto1.jpg foto2.jpg
```

## Módulo del dron (MVP)

Toma un video del dron, saca un cuadro cada pocos segundos, le pone el GPS del archivo `.SRT` y pasa cada cuadro por el mismo semáforo de las fotos de WhatsApp (en modo "vista aérea"). Al final abre un mapa con la ruta del vuelo y un punto de color por cuadro. Al darle clic a un punto se ve el cuadro y lo que vio el modelo. El mapa es un solo archivo HTML: funciona sin internet, salvo el fondo del mapa.

**Instalar** (una vez, trae ffmpeg):

```powershell
.\.venv\Scripts\python -m pip install -r requirements-dron.txt
```

**Antes de volar (DJI Fly):** activar *Ajustes → Cámara → Subtítulos de video*, para que el dron grabe el `.SRT` con el GPS junto a cada video. Si algún video no abre, grabar en H.264.

**Usar** (desde `backend`):

```powershell
# Gratis: solo saca los cuadros y arma el mapa, sin clasificar
.\.venv\Scripts\python -m app.drone --video C:\ruta\DJI_0001.MP4 --sin-clasificar

# Con el semáforo (pregunta antes de gastar)
.\.venv\Scripts\python -m app.drone --video C:\ruta\DJI_0001.MP4 --cada 5 --max-cuadros 40

# Imágenes públicas de un sismo real, con su crédito (si traen GPS en el EXIF, salen en el mapa)
.\.venv\Scripts\python -m app.drone --imagenes C:\ruta\fotos --credito "UAVs-TEBDE, Turquía 2023 (CC BY 4.0)"
```

El `.SRT` se busca solo junto al video, con el mismo nombre. Se pueden pasar `--video` e `--imagenes` en la misma corrida. El resultado queda en `data/vuelos/<nombre>/`: `mapa.html`, `resultados.geojson` y `cuadros/`.

- **Costo:** cerca de 1 centavo de dólar por cuadro con Sonnet 5.5. Por eso hay un tope de 40 cuadros por video (`--max-cuadros`).
- **Lo que dice el mapa es preliminar.** Verde significa "sin daño visible desde el aire", nunca "habitable": el interior no se ve desde arriba.
- **Privacidad:** los cuadros pueden mostrar personas y placas. No se publican y se borran después de la demo.
- **Vuelos:** con el dron registrado ante la Aerocivil y respetando las distancias del RAC 100.

## Pruebas y migraciones

```bash
pytest
alembic revision --autogenerate -m "descripción"   # si cambian los modelos
alembic upgrade head
```

## Pasar a la versión paga (sin tocar el código)

**Número real con QR** (cada visitante usa su propio celular; los mensajes de la demo siguen saliendo en 0 COP):
1. Conseguir un número sin WhatsApp activo (una línea sin uso, un fijo o una SIM prepago).
2. En WhatsApp Manager: Agregar número → verificar → nombre visible "GeoAid" (Meta lo revisa en horas o días) → agregar un método de pago.
3. Cambiar en `.env` solo `WHATSAPP_PHONE_NUMBER_ID` (y el token, si cambia).
4. Crear el QR desde WhatsApp Manager o con `https://wa.me/57XXXXXXXXXX?text=Hola`.

**Servidor en la nube (Railway, ≈ 5–20 USD/mes):**
1. Subir el repo a GitHub (privado) y crear un proyecto en Railway desde ese repo, con *root directory* `backend` (usa el `Dockerfile`).
2. Agregar un **volumen** montado en `/data`. El Dockerfile ya apunta ahí la base de datos y las fotos.
3. Copiar las variables del `.env` al panel de Railway (con `DEBUG=false`).
4. Cambiar la URL del webhook en Meta por la de Railway.
