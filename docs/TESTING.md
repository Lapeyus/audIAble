# Pruebas de audIAble

## 1. Estrategia

audIAble depende de motores externos (Vision, Ollama, Google, Edge, CLI de agentes) cuyo resultado no es
determinista ni gratuito, así que las pruebas automatizadas se concentran en la **lógica propia** que decide qué
texto llega al audiolibro:

- **Datos sintéticos con verdad conocida**: páginas generadas con OpenCV (`cv2.putText`), lecturas de OCR inventadas
  con cajas y confianzas controladas, y textos cortos escritos para cada regla. Ninguna prueba usa libros reales.
- **Sin red ni credenciales**: los motores se sustituyen por funciones simuladas (por ejemplo,
  `detectar_paginas_vision` devuelve `{}`), `unittest.mock` (lista de modelos de Ollama) o un servidor HTTP local
  en `127.0.0.1` que aplica las reglas documentadas de la API de TypeSafe. La bóveda de secretos se simula
  sustituyendo la llamada a `gcloud`.
- **Scripts con nombre con guion**: los módulos de `pasos/` no son importables por nombre (`pre-video.py`), así que
  las suites los cargan con `importlib` o ejecutan su fuente hasta antes del bloque principal (`exec` del código
  previo a `if args.check:` o a `principal()`), con un `sys.argv` controlado.
- **Mediciones fuera de las pruebas**: la calidad real del OCR y del corrector se mide con las herramientas de
  `utiles/` sobre vídeos reales, cuyos resultados están registrados en
  [ARCHITECTURE §7](ARCHITECTURE.md#7-mediciones-registradas). Esas herramientas sí usan Vision y agentes.

Framework: `unittest` de la biblioteca estándar (no hay `pytest` ni configuración de cobertura en el repo).

## 2. Cómo correr las pruebas

Desde la raíz del repositorio, con el entorno del repo:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Una suite o una prueba concreta:

```bash
.venv/bin/python -m unittest tests.test_logica_pura -v
.venv/bin/python -m unittest tests.test_multiframe.FusionTest.test_captura_sin_anclas_no_aporta
```

Requisitos: las dependencias de `requirements.txt` (en particular `opencv-python-headless`, `numpy`, `PyMuPDF`,
`beautifulsoup4`; `Pillow` y `requests` para la suite de TypeSafe, que hoy llegan como dependencias de Streamlit).
No hacen falta macOS, Ollama, credenciales de Google ni conexión a internet.

### Resultado real (2026-10-25)

Ejecutado en macOS con `.venv` (Python 3.9.6; OpenCV 5.0.0, NumPy 2.0.2, PyMuPDF 1.26.5):

```
Ran 52 tests in 4.210s

OK
```

52 pruebas, 0 fallos, 0 omitidas. La suite del POC emite un `ResourceWarning` por un socket del servidor simulado
que no se cierra explícitamente; no afecta al resultado.

## 3. Inventario de suites

### `tests/test_calidad_video.py` (21 pruebas)

| Clase | Qué cubre |
| --- | --- |
| `CalidadTest` (14) | nitidez que prefiere el texto enfocado; registro de perspectiva con sombra; no registrar páginas distintas; páginas en blanco que no se registran ni rotan; cuadriláteros oblicuos y degenerados (`cuadro_seguro`); `cuadro_envolvente` que restituye una esquina hundida por el pulgar; planitud con inclinación leve y detección del lomo; iluminación aplanada sin perder contraste; movimiento compensado con rotación y exposición; capturas del reposo y de su entorno; un autoenfoque que no parte el reposo; reajuste de la mano que no descarta un reposo partido; cambio de página con texto pequeño; conservación del fotograma sin detección |
| `ConsensoTest` (5) | consenso de OCR: dos variantes corrigen una lectura débil; artefacto intrapalabra corregido aun con confianza alta; el desacuerdo no sustituye; se preserva el original confiable; variantes finitas sin modificar el original |
| `LimpiezaTest` (2) | puntos suspensivos y unión de guiones de renglón; colapso de frases repetidas y de cornisas del libro |

### `tests/test_multiframe.py` (3 pruebas)

`FusionTest`: una captura desplazada no duplica texto y recupera el renglón tapado; una captura sin anclas no aporta;
dos capturas no recuperan dos veces el mismo renglón.

### `tests/test_poc_typesafe.py` (4 pruebas)

| Clase | Qué cubre |
| --- | --- |
| `PocTypeSafeTest` | el POC construye peticiones que cumplen las reglas de la API (orden de partes multipart, cabeceras, referencias de imagen, tipos y dimensiones, versión de modelo para Box) contra un servidor simulado local |
| `BovedaTest` | `nucleo/boveda.py` encuentra la clave por nombre sin mostrarla (llamada a `gcloud` simulada) |
| `IlegiblesExcesivosTest` | guardarraíl de `pre-ollama.py` contra páginas declaradas ilegibles enteras, respetando dudas reales del informe de fusión |
| `InjertoTest` | injerto del borrador del OCR solo en los tramos `[ilegible]`, conservando los párrafos del agente |

### `tests/test_logica_pura.py` (24 pruebas, agregada en esta documentación)

| Clase | Qué cubre |
| --- | --- |
| `AbreviaturasTest` (3) | tablas de abreviaturas en español e inglés (Saint/Street) e idioma sin tabla |
| `SaltosDeLineaTest` (3) | título, cita y atribución rematados con punto; unión cuando el renglón sigue en minúscula; palabra partida por guion |
| `FoliosYGuionesTest` (4) | folios aislados; inciso entre rayas y palabra partida; normalización de pausas; colapso de repeticiones |
| `EstimacionTest` (6) | rangos de páginas; formato de duraciones; franquicia de Vision; motores gratuitos frente a Gemini; tarifa de Google TTS por tipo de voz; total como suma de etapas (las tarifas se leen de `config.json`, no se fijan en la prueba) |
| `GuardarrailesCorrectorTest` (3) | troceo sin partir frases; `validar` acepta reparaciones y rechaza invenciones y vacíos; limpieza de preámbulo y markdown |
| `ModelosTest` (3) | orden de candidatos de Ollama por tarea, autodetección y error sin modelos (lista simulada); clasificación agente/Gemini |
| `CredencialesGoogleTest` (2) | llave explícita, llave inexistente y variable de entorno válida (restaura el entorno al terminar) |

## 4. Herramientas de medición (no automatizadas)

| Herramienta | Qué mide | Necesita |
| --- | --- | --- |
| `utiles/evaluar-calidad-ocr.py` | CER del OCR por consenso frente a una versión anterior del ayudante, sobre cuatro casos sintéticos (limpio, sombra, baja resolución, desenfoque) | macOS (Vision) |
| `utiles/indicadores-calidad.py` | por página: recortes fiables, mano borrada, nitidez, confianza de Vision, páginas casi vacías, palabras sospechosas, fragmentos duplicados → `indicadores.json` | carpeta de un libro hecho desde vídeo; Vision salvo `--sin-vision` |
| `utiles/comparar-multiframe.py` | cadena A (una imagen) frente a B (multifotograma) con el mismo corrector → `comparacion.json` y `comparacion.md` | vídeo real, Vision y una CLI de agente |
| `utiles/poc-typesafe.py` | aciertos por experimento, IoU, latencia y tokens | clave de TypeSafe (o `--simular`, que no envía nada) |

## 5. Verificación manual recomendada

- Interfaz: `streamlit run app.py`, procesar un PDF corto con «Solo reglas deterministas» y Edge o macOS, y
  comprobar TXT, PDF enriquecido y audio en la carpeta de salida.
- Vídeo: revisar `imagenes/paginas_detectadas.jpg` tras la detección; borrar una toma sobrante y reanudar sin
  «Empezar de cero» para comprobar la reutilización por `origen.json`.
- Motores: `python3 pasos/pre-ollama.py --check`, `python3 pasos/pro-gcp-tts.py --f <dir> --o <dir> --dryrun`.

## 6. Brechas conocidas

- **Sin corpus real verificado**: no hay vídeos con transcripción de referencia para medir CER/WER de extremo a
  extremo; las pruebas del detector y de la fusión son sintéticas.
- **Sin pruebas** para: `pre-pdf.py`, `pre-figuras.py`, `pre-capitulos.py`, los tres scripts de TTS (troceo y
  reanudación), `nucleo/exportar.py`, `app.py` (incluida `unir_audios`), `traer-videos.py` y la agrupación en libros
  de `procesar-biblioteca.py` (`mismo_libro`, `contencion`, saltos en las junturas). Son candidatas naturales para
  pruebas de lógica pura, aunque varios scripts ejecutan código al importarse y requieren el mismo truco de carga.
- **Integración con motores reales** (Vision, Ollama, Google, Edge, agentes) no se prueba automáticamente.
- **Sin CI**: no hay flujo de GitHub Actions; las pruebas se corren a mano. `.pre-commit-config.yaml` solo aplica
  verificaciones de formato y seguridad genéricas (JSON/YAML válidos, llaves privadas, archivos grandes, espacios).
- **Dependencias implícitas**: `Pillow` y `requests` (usadas por `nucleo/typesafe.py`) no están listadas en
  `requirements.txt`.
- **Versión de Python**: las pruebas se validaron en 3.9.6; no hay matriz de versiones.
