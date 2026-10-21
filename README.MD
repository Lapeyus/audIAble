# Text-to-Speech Audio Generator

## Overview
These scripts convert text files to audio. They take text files from an input folder and save the generated audio files into an output folder. Three interchangeable text-to-speech engines are available, all sharing the same `--f` / `--o` interface, the same chunking, and the same "skip what already exists" behaviour, so a run can be resumed at any time:

| Script | Engine | Cost | Needs |
| --- | --- | --- | --- |
| `pasos/pro-gcp-tts.py` | Google Cloud Text-to-Speech | paid, per character | credentials + internet |
| `pasos/pro-edge-tts.py` | Microsoft Edge TTS | free | internet |
| `pasos/pro-mac-tts.py` | macOS system speech engine (`say`) | free | macOS only, works offline |

## Requirements
- Python 3.x
- For `pasos/pro-gcp-tts.py`: a Google Cloud Platform account, Text-to-Speech API credentials and the `google-cloud-texttospeech` package
- For `pasos/pro-edge-tts.py`: the `edge-tts` package (no account or credentials needed)
- For `pasos/pro-mac-tts.py`: macOS, nothing else (uses the built-in `say` command)

## Puesta en marcha
```bash
git clone <este-repositorio> && cd audIAble
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python3 -c "import nltk; nltk.download('punkt')"
```

Y para abrir la interfaz, que es la forma recomendada de usarlo:
```bash
streamlit run app.py
```

Se abre sola en http://localhost:8501. Si ese puerto está ocupado, o quieres que no abra el navegador:
```bash
streamlit run app.py --server.port 8555 --server.headless true
```

Para pararla, Ctrl+C en la misma terminal. La interfaz llama por debajo a los scripts de `pasos/`, así que todo lo que hace se puede reproducir a mano desde la línea de comandos.

Lo que necesita cada parte:
- **Nada extra** para extraer texto de un PDF, limpiarlo y generar audio con Edge o con la voz de macOS.
- **OpenCV** (`opencv-python-headless`, ya en `requirements.txt`) para convertir un vídeo del libro en páginas; el OCR de esas páginas lo hace cualquiera de los tres motores.
- **Ollama** corriendo (`ollama serve`) y algún modelo descargado, para corregir el escaneado, detectar capítulos o hacer OCR local. Los modelos se autodetectan.
- **Credenciales de Google**, solo para Google Cloud Vision o su síntesis de voz. Se resuelven solas en este orden: llave JSON explícita (`--cred` o el campo de la interfaz) → variable `GOOGLE_APPLICATION_CREDENTIALS` → `credentials.json` en la raíz → ADC del sistema (`gcloud auth application-default login`). Si ya iniciaste sesión con gcloud, no hay que configurar nada; si no hay ninguna fuente, la interfaz pide la ruta de la llave.

## Estructura del repositorio
```
app.py            interfaz de Streamlit, punto de entrada
config.json       voces, tarifas, umbrales y ritmos de estimación
nucleo/           módulos compartidos e importables
  limpieza.py       reglas deterministas de limpieza de texto
  estimacion.py     medida del volumen y cálculo de tiempo y coste
  ollama_local.py   autodetección de los modelos instalados
pasos/            los scripts del pipeline, uno por etapa, todos con --f y --o
  pre-video.py      de un vídeo del libro a una imagen por página
  vision_pagina.swift  localización de la página y orientación del texto con Vision (macOS)
nucleo/calidad_video.py, nucleo/ocr_calidad.py  nitidez, alineación, enderezado y consenso de OCR
tests/            pruebas automatizadas (python -m unittest discover -s tests)
utiles/           herramientas sueltas: demos de voces, unir y resumir
  traer-videos.py   copia por USB (adb) los vídeos recientes del teléfono
  indicadores-calidad.py  indicadores de calidad de un libro hecho desde vídeo
  poc-typesafe.py   POC de la API de imágenes de TypeSafe (clasificar páginas, mano, deduplicar, Box)
  comparar-multiframe.py  banco de pruebas: OCR de una imagen frente a OCR multifotograma
```

## Configuration
1. Only for the Google engines: sign in once with `gcloud auth application-default login`, or pass a service account JSON key with `--cred` (a `credentials.json` in the project root also works).
2. Update the `config.json` file to set your desired voice and audio configurations. Each engine reads its own section:
   - `TextToSpeechAPI`: voice, audio encoding and pricing used by `pasos/pro-gcp-tts.py`.
   - `EdgeTTS`: `voice`, `rate`, `volume` and `pitch` (Edge notation, e.g. `"+10%"`, `"-5Hz"`), `max_bytes` per audio part and `audio_format`.
   - `MacTTS`: `voice` (`null` keeps the voice selected in System Settings), `rate` in words per minute (`null` keeps the system rate), `data_format` passed to `say`, `max_bytes` per audio part and `audio_format`.

## Usage
1. Place your text files into an input folder.
2. Run one of the TTS scripts with the following command-line arguments:
    ```bash
    python3 pasos/pro-edge-tts.py --f <path-to-folder-containing-text-files> --o <path-to-folder-to-save-generated-audio-files>
    ```
   - `--f`: Folder containing the text files to be processed.
   - `--o`: Folder to save the generated audio files.
   - `--dryrun`: Report what would be generated without calling the engine (the Google script estimates the cost, the free engines report the pending characters).
   - `--v`: (Edge and macOS only) voice to use for this run, overriding `config.json`.
   - `--voices`: (Edge and macOS only) list the available voices and exit.

To pick a voice, list what is available and pass it with `--v`, or set it permanently in `config.json`:
```bash
python3 pasos/pro-edge-tts.py --voices | grep es-
python3 pasos/pro-mac-tts.py --voices | grep es_
python3 pasos/pro-edge-tts.py --f cap1/ocr/ --o cap1/audio --v es-MX-DaliaNeural
python3 pasos/pro-mac-tts.py --f cap1/ocr/ --o cap1/audio --v Monica
```

## Choosing a voice by ear
`utiles/demo-voices.py` reads the same sample sentence with every available voice, so you can listen instead of guessing from a name. It writes one file per voice plus a single joined demo where each voice announces its own name first:
```bash
python3 utiles/demo-voices.py --e edge --l es-MX,es-ES,en-US
python3 utiles/demo-voices.py --e mac --l es-MX,es-ES
```
- `--e`: engine to demo, `edge` or `mac`.
- `--l`: comma separated locales to include (`es-MX` and `es_MX` both work). All of them if omitted, which is over 300 voices for Edge.
- `--o`: folder for the demo files, defaults to `./demos`.
- `--t`: sample sentence to read, overriding the built-in one for each language.
- `--nojoin`: write only one file per voice, skipping the joined demo.

The result is `demos/demo_<engine>.<ext>` to listen straight through, and `demos/<engine>/<voice>.<ext>` to replay a single candidate. The sample sentence follows the language of each voice, and existing files are skipped, so a second run only adds what is missing. Copy the file name of the voice you liked into `--v` or into `config.json`.

`pasos/pro-mac-tts.py` uses the voice selected in System Settings > Accessibility > Spoken Content when no voice is given, so leaving `MacTTS.voice` as `null` in `config.json` keeps the system default engine.

the pdf processing script has two modes: split creates a TXT file for each one of the pages in the range, and the other mode PHOTO, creates one image for each one of the pages in the selected range.


   - `--m`: mode: create a txt or a photo for each page in the pdf (photo is meant as preparation step for to use OCR)
   - `--p`: pages to be processed. can be a single page, comma separated list or a range using -


For example:
```bash
python3 pasos/pre-pdf.py --f book.pdf --o ./cap1 --m split --p 19-43
python3 pasos/pre-pdf.py --f book.pdf --o ./cap1 --m photo --p 19-43
python3 pasos/pre-cleanup.py --f cap1/txt_files/
python3 pasos/pro-gcp-ocr.py  --f cap1/img/ --o cap1/ocr
python3 pasos/pro-gcp-tts.py  --f cap1/ocr/ --o cap1/audio
```

The last step can be swapped for any of the free engines, the rest of the pipeline stays the same:
```bash
python3 pasos/pro-edge-tts.py --f cap1/ocr/ --o cap1/audio
python3 pasos/pro-mac-tts.py  --f cap1/ocr/ --o cap1/audio
```

### Saltos de línea y pausas
La limpieza distingue dos clases de cambio de línea, con una puerta previa: **si el renglón siguiente empieza en minúscula, nunca hay corte** — la frase continúa abajo y se une, incluso si la línea termina en un punto (ese punto suele ser el guion de corte de una palabra partida que el OCR leyó mal, y se retira al unir). Solo cuando el siguiente renglón arranca en mayúscula, cifra, apertura o raya de diálogo se evalúa el corte: una línea ya rematada conserva su salto, y una con forma de título, pie o atribución (corta, con palabra clave de encabezado o en versales, sin terminar en palabra de enlace) se conserva y se remata con punto, para que el TTS haga la pausa: `DÍA 42⏎«…libertad».⏎William Wallace (Braveheart)` queda como `DÍA 42.` / `«…libertad».` / `William Wallace (Braveheart).` en párrafos propios. Las abreviaturas se expanden antes, para que un `Dr.` a fin de línea no se confunda con un fin de oración

El pipeline completo, con corrección por LLM y división en capítulos:
```bash
python3 pasos/pre-pdf.py --f book.pdf --o ./cap1 --m split --p 1-58
python3 pasos/pre-cleanup.py --f cap1/
python3 pasos/pre-ollama.py --f cap1/
python3 pasos/pre-capitulos.py --f cap1/
python3 pasos/pro-edge-tts.py --f cap1/ --o cap1/audio --v es-MX-DaliaNeural
```

Si el PDF no trae capa de texto, los dos primeros pasos se cambian por el render de páginas y el OCR. En Mac, el motor recomendado es el del propio sistema (framework Vision, vía `pasos/vision_ocr.swift`):
```bash
python3 pasos/pre-pdf.py --f book.pdf --o cap1/img --m photo --dpi 300
python3 pasos/pro-mac-ocr.py --f cap1/img --o cap1/ocr --idioma es
```

## Desde un vídeo del libro
Si el libro no está escaneado, basta con grabarlo: el móvil fijo (un trípode, o apoyado en algo), el libro quieto debajo, y se van pasando las páginas una a una dejando cada una quieta un par de segundos. `pasos/pre-video.py` convierte ese vídeo en una imagen por página, con el mismo nombre (`pag_N.png`) que el render de un PDF, así que a partir de ahí el pipeline es el de un escaneo: OCR, limpieza, PDF enriquecido y voz.

```bash
python3 pasos/pre-video.py --f libro.mp4 --o cap1/img
python3 pasos/pro-mac-ocr.py --f cap1/img --o cap1/ocr --idioma es
python3 pasos/pre-cleanup.py --f cap1/ocr/
```

Un móvil que graba en 4K u 8K corta la grabación en segmentos de unos diez minutos. Se le dan todos, o la carpeta que los contiene, y salen como un solo libro: `--f` admite varios vídeos o carpetas, los ordena por nombre (`--orden fecha` usa la fecha del archivo) y encadena sus tomas en una única secuencia, así que la página en la que se cortó la grabación, que aparece al final de un segmento y al principio del siguiente, se funde como cualquier otra repetida. En la interfaz basta con dar la carpeta de los segmentos, o subirlos todos a la vez.

```bash
python3 pasos/pre-video.py --f grabacion/ --o cap1/img --doble
python3 pasos/pre-video.py --f PXL_0001.mp4 PXL_0002.mp4 PXL_0003.mp4 --o cap1/img --doble
```

Cómo decide qué es una página, y cómo la limpia:
- Analiza unos pocos fotogramas por segundo (`--fps`, 4 por omisión) y mide cuánto cambia la imagen entre uno y el siguiente, **después de alinearlos** (correlación de fase), para que el temblor de un móvil en la mano no cuente como movimiento. Una pasada de hoja es un pico; el **reposo** entre dos picos, una página, si dura al menos `--quietud` segundos (0,8). El umbral del pico es el mayor entre `--umbral` (2,5, para un trípode) y `--factor` veces el movimiento mediano del vídeo (1,4): con la cámara en mano sube solo. Es un umbral bajo a propósito: un reposo partido en dos se vuelve a fundir después, pero una pasada que no se detecta pierde la página.
- De cada reposo se guarda el fotograma **más nítido** (varianza del laplaciano) entre los más calmados, así un autoenfoque a medio tramo nunca acaba en el OCR. Y además se leen varias **capturas** más del mismo reposo (`--capturas`, 5) y de los instantes justo anteriores y posteriores, cuando la mano llega o se aparta.
- La **mano se borra** con esas capturas: en la página más nítida se detecta la piel (umbrales YCrCb, la regla clásica) y cada mancha se sustituye por la mediana de las demás capturas que, alineadas localmente sobre esa zona, muestran página y no piel. La alineación gruesa la dan puntos SIFT emparejados con RANSAC, porque sobre líneas de texto, que se repiten, una correlación cae con facilidad en la línea equivocada; la ECC solo afina. Lo que queda fuera de la mano no se toca, así que el texto nunca se emborrona. Si la mano no se mueve en todo el reposo ni en su entorno, no hay captura con la página libre debajo y la mancha se queda: el registro lo dice («mano borrada en un 0%»).
- Cada página se **endereza** además por el ángulo de sus líneas de texto (el que hace más nítido el perfil de filas, ±4°), porque las esquinas fijan el contorno pero las líneas siguen algo inclinadas por la curvatura del libro.
- En Mac, la página la localiza **Vision** (`pasos/vision_pagina.swift`, el mismo detector de documentos que usa Notas para escanear un papel), fotograma a fotograma, porque la cámara puede moverse; todas las páginas se enderezan al mismo tamaño. Fuera de Mac se usa la región clara más grande, que solo funciona sobre un fondo oscuro y liso. `--recorte no` guarda el fotograma entero.
- El texto se gira solo: Vision prueba las cuatro orientaciones sobre tres tomas y se queda con la que lee más (`--rotar` lo fija a mano).
- Dos reposos seguidos con la misma página se funden: en Mac se leen las páginas candidatas y se compara su texto por **cuatrigramas de caracteres** (`--similitud`, fracción en común, 0,45), que aguantan las palabras mal leídas a resolución de vídeo, y se queda la toma en la que se leyeron más palabras, que es la que menos mano y menos desenfoque tiene. Las páginas con poco texto, y los demás sistemas, se comparan por correlación de imagen.
- Con `--doble` cada toma se parte por la mitad en página izquierda y derecha, para grabar el libro abierto.
- `--brutos` guarda además los fotogramas sin recortar en `img/brutos/`, para comprobar qué eligió el detector. La interfaz lo activa siempre.

Cada página impresa sale con el tramo del vídeo del que viene (`pag_3.png (10.4-12.5 s, 918x1496)`) y en la carpeta queda `paginas_detectadas.jpg`, una hoja de contactos numerada que la interfaz muestra al terminar la detección: de un vistazo se ve si sobra una toma. Lo que sobra casi siempre es una **pausa a mitad de vuelta de hoja**: el detector no distingue una página torcida de una plana, así que si te paras con la hoja en el aire, esa toma sale como página. Se borra su `pag_N.png` (y su `.txt` si el OCR ya pasó) y se vuelve a ejecutar sin «Empezar de cero»: el paso deja en la carpeta un `origen.json` con la huella del vídeo y los ajustes, y si coinciden reutiliza las páginas ya detectadas en vez de repetir la media hora de detección de un libro entero. Si faltan páginas, baja `--quietud` o `--factor`. Los valores por omisión viven en la sección `Video` de `config.json`.

Sobre la resolución: un vídeo 1080p del libro abierto deja cada página en unos 950 píxeles de alto, unos 100 dpi, que Vision lee con errores sueltos. Grabar en 4K, o encuadrar una sola página, multiplica la calidad del OCR.

Al enriquecido de un vídeo no se le puede dar un dpi, así que sus páginas se maquetan con la altura de un A4. Y la estimación previa no puede contar páginas que aún no se han detectado: supone una página cada `video_s_por_pagina` segundos con `video_caracteres_por_pagina` caracteres (sección `Estimacion`), y el recuento real se muestra en cuanto termina la detección.

Consejos de grabación que marcan la diferencia: luz uniforme y sin reflejos, la página ocupando la mayor parte del encuadre, enfoque bloqueado en la app de cámara si lo permite, cada página quieta un par de segundos, y las manos fuera del encuadre mientras lo está. Pasar la hoja de un solo gesto, sin pararse a mitad, evita las páginas torcidas.

### Traer los vídeos del teléfono por USB
Un Pixel (o cualquier Android) conectado por USB con la **depuración USB** activada (Ajustes → Sistema → Opciones para desarrolladores → Depuración por USB; la primera vez el teléfono pide confirmar el ordenador, marca «Permitir siempre») se puede vaciar sin abrir Android File Transfer. `utiles/traer-videos.py` usa `adb` (lo busca en el PATH y en el SDK de Android, `~/Library/Android/sdk/platform-tools/adb`; si no hay ninguno, `brew install --cask android-platform-tools`), lista los vídeos de la cámara, copia los grabados en los últimos días (`--desde 7d`, o `90m`, `12h`, o una fecha) a `trabajo/entrada/telefono/`, comprueba cada copia por tamaño y apunta lo copiado en `manifiesto.json` para no repetirlo. Los segmentos de una misma grabación (`PXL_…521.mp4`, `PXL_…521~2.mp4`, …) quedan juntos en una carpeta con el nombre de la grabación, que es justo lo que pide «Vídeo del libro».

```bash
python3 utiles/traer-videos.py                 # una pasada: copia lo nuevo de los últimos 7 días
python3 utiles/traer-videos.py --desde 24h
python3 utiles/traer-videos.py --vigilar       # se queda esperando: cada vez que conectes el teléfono, copia lo nuevo
```

`--vigilar` es lo más parecido a «al conectar el teléfono, tráete los vídeos»: déjalo corriendo en una terminal y, al enchufar el USB, copia y avisa; tras copiar espera a que lo desconectes y vuelvas a conectarlo. No borra nada del teléfono. En la interfaz, la opción «Vídeo del libro» tiene el botón «Traer del teléfono por USB» (una pasada, con el rango de días al lado) y un selector con las grabaciones ya copiadas que rellena la ruta. El emulador de Android se ignora salvo con `--incluir-emulador`, que sirve para probar.

### Biblioteca en el disco externo y libros automáticos
Los vídeos y sus salidas pesan decenas de GB, así que viven en la **biblioteca** del disco externo: `Rutas.biblioteca` en `config.json` (`/Volumes/Seagate/audIAble`). Cuando el disco está montado, `traer-videos.py` copia a `<biblioteca>/entrada/telefono/` y la interfaz propone `<biblioteca>/salida/` como carpeta de salida; si no lo está, todo cae en `trabajo/` como antes (`nucleo/rutas.py`).

`utiles/procesar-biblioteca.py` convierte esa biblioteca en libros sin intervención, y `traer-videos.py --procesar` (también con `--vigilar`) lo lanza en cuanto termina de copiar:

```bash
python3 utiles/traer-videos.py --vigilar --procesar     # conecta el teléfono: copia, agrupa, OCR, TXT y PDF
python3 utiles/procesar-biblioteca.py --solo-agrupar     # solo ver cómo se agrupan las grabaciones en libros
```

Cómo agrupa las grabaciones en libros, en orden cronológico (la fecha va en el nombre `PXL_AAAAMMDD_HHMMSS…`):
1. Cada grabación (una carpeta con sus segmentos; de Video Boost se toma el `VB-02.MAIN` a resolución completa y se ignora la previa `VB-01.COVER`) pasa por `pre-video.py`, que además del contorno deja en `calidad.json` el texto que leyó en cada página.
2. Dos grabaciones seguidas son el mismo libro si se grabaron con menos de `--pausa` horas de separación (`Rutas.pausa_entre_grabaciones_h`, 3), o si la última página de una es la primera de la otra (cuatrigramas, `--similitud`), o si comparten el vocabulario (palabras de cinco letras o más, Jaccard ≥ 0,3: nombres, lugares, el léxico del libro). Si no se cumple ninguno, empieza otro libro.
3. Las páginas de cada libro se copian en orden a `<salida>/libros/libro_<fecha>_<hora>/imagenes/`, y en cada juntura se saltan las dobles páginas que la grabación siguiente repite del final de la anterior. `libro.json` guarda de qué grabación y página viene cada una.
4. OCR de macOS, limpieza por reglas, `libro_….txt` y `libro_… (enriquecido).pdf`. Un libro ya hecho con las mismas grabaciones se salta; la corrección con LLM y el audio se lanzan después desde la interfaz sobre esa carpeta.

### Calidad de extracción y validación
Esta parte la revisó también otro asistente (Codex), que dejó pruebas, un informe de calidad por página y un OCR por consenso. De su trabajo se conserva lo que mejoró el resultado y se ha vuelto a la versión anterior en tres puntos donde las medidas empeoraban; aquí queda el estado final:

- **Nitidez**: Tenengrad por bloques con reducción de ruido (`nucleo/calidad_video.py`), que ignora un borde de mesa o una mano aislada al elegir el fotograma de referencia de cada reposo.
- **Movimiento**: compensado con flujo óptico (ida y vuelta) y ajuste afín robusto, a 320 píxeles, con descuento de los cambios globales de exposición. Separa páginas de texto pequeño que a 160 píxeles se fundían (prueba automatizada). A cambio lee un autoenfoque momentáneo como movimiento, así que un pico de uno o dos fotogramas analizados en el que la nitidez se desploma respecto a su entorno no corta el reposo; sin ese filtro el vídeo sintético perdía tres de sus siete páginas.
- **Capturas donantes**: del reposo y de hasta dos fotogramas analizados antes y después de él, donde la mano llega o se aparta. Restringirlas al reposo dejaba el borrado de la mano en el 0 % en todas las páginas del vídeo real.
- **Recorte**: las esquinas de Vision se validan (`cuadro_seguro`: convexidad, ángulos, lados, y coherencia de área con la mediana del libro), todas las páginas salen con el mismo tamaño mediano, y una toma sin esquinas fiables hereda las de la toma válida más cercana en el tiempo; conservar el fotograma entero dejaba páginas inservibles. `calidad.json` registra por página si su recorte fue propio o heredado (`recorte_fiable`).
- **Fusión de la mano**: alineación local por ventana (SIFT con RANSAC y afinado ECC en dos escalas) y sustitución de cada mancha de piel por la mediana de las capturas donantes que coinciden con la referencia por encima de 0,5. Exigir un único donante con correlación 0,93 a resolución completa, que sobre una página curvada no se alcanza nunca, también dejaba el borrado en el 0 %. Pero un parche equivocado (texto desalineado bajo la mano) es peor que la mano, y en un libro real apareció: ahora hacen falta dos donantes que coincidan, o uno solo por encima de 0,75.
- **Parches con texto duplicado**: el recorte de una toma envuelve todas sus capturas, así que junto al borde de la hoja hay zona que en unas capturas es página y en otras es mesa o dedos. Un donante alineado ahí pegaba los finales de línea una segunda vez («su asomsu asom»). Dos defensas: los donantes tienen que parecerse entre sí dentro de la mancha (correlación ≥ 0,6), y fuera de la **caja del texto** de la referencia (medida con `tinta_de`, solo manchas del tamaño de una letra, entre los percentiles 2 y 98 en los dos ejes, porque la fusión ocurre antes de girar el texto) un parche solo puede ser papel: los píxeles donde trae tinta se dejan sin parchear. Medir la caja con un umbral de gris simple no servía: la mesa oscura y las sombras la extendían a toda la hoja.
- **Hoja levantada**: la referencia de cada reposo ya no es simplemente la captura más nítida, porque una hoja a mitad de vuelta, girada 10-15°, es nítida y salía como página torcida. Se mide la **planitud** (cuánto mejora el perfil de líneas al girar la imagen hasta ±20°; una página plana no mejora) y la referencia es la más nítida entre las planas.
- **Curvatura**: un libro sujeto con la mano no queda plano y las líneas se curvan hacia el lomo. `desdoblar` divide la página en franjas verticales, mide por correlación de perfiles cuánto sube o baja el texto de una franja a la siguiente (acotado a medio interlineado, medido en la propia página, para no engancharse al renglón equivocado), suaviza ese desplazamiento con un polinomio y lo deshace fila a fila. Es conservador: sin evidencia clara devuelve la imagen intacta, y su ganancia en las páginas probadas fue modesta, porque la curvatura se concentra junto al lomo.
- **Enderezado** de cada página con lienzo ampliado para no cortar letras, y solo cuando el perfil de líneas mejora con el giro.
- **Repetidas**: contención de cuatrigramas sobre el conjunto menor (`--similitud`, 0,45), sin exigir que coincidan los números leídos, que el OCR a resolución de vídeo confunde.

**OCR por consenso** (`pro-mac-ocr.py --calidad alta`, o la casilla «Tres lecturas por página» del paso 2): lee cada página tres veces (original; iluminación uniformada dividiendo por el fondo estimado; contraste local CLAHE) y sustituye una línea de baja confianza solo cuando las otras dos lecturas coinciden, tienen más confianza y están en la misma posición. Deja `pag_N.ocr.json` con las lecturas alternativas y las líneas a revisar. Cuesta el triple, y en la evaluación sintética (`utiles/evaluar-calidad-ocr.py`, cuatro casos con texto conocido: limpio, sombra, baja resolución y desenfoque de movimiento) no redujo el error de caracteres respecto a una sola lectura, así que va desactivado por omisión (`--calidad base`); `--calidad auto` lo activa solo para páginas que vienen de un vídeo (carpeta con `origen.json`). La confianza del motor y el acuerdo entre variantes no garantizan exactitud: las lecturas están correlacionadas, y las líneas ausentes no se inventan.

`utiles/indicadores-calidad.py --f <carpeta>` resume la calidad de un libro hecho desde vídeo y deja `indicadores.json` con el detalle por página: del detector (recortes fiables, fracción de mano borrada, nitidez, tamaños), del OCR (confianza media por línea de Vision, líneas por debajo de 0,5, páginas con confianza baja) y del texto (caracteres y palabras, páginas casi vacías, palabras sospechosas —cifras pegadas a letras, cinco consonantes, letras triplicadas, mayúscula dentro de palabra— y **fragmentos duplicados**, el rastro de un parche mal alineado). Sirve para comparar dos corridas del mismo vídeo antes de fiarse del texto.

Todos los motores de OCR excluyen `paginas_detectadas.jpg`. La versión del preprocesamiento forma parte de la huella del vídeo (`origen.json`), así que un cambio de algoritmo invalida las páginas reutilizables. Pruebas: `python -m unittest discover -s tests -v` (perspectiva con iluminación desigual, movimiento, nitidez, páginas distintas y vacías, geometría degenerada, filtro de autoenfoque, reglas de consenso). No sustituyen a un corpus de vídeos reales con transcripción verificada para medir CER y WER, que sigue sin existir.

Referencias: [homografías en OpenCV](https://docs.opencv.org/4.12.0/d9/dab/tutorial_homography.html), [estimadores robustos USAC](https://arxiv.org/abs/2104.05044), [tamaño mínimo de texto en Vision](https://developer.apple.com/documentation/vision/vnrecognizetextrequest/minimumtextheight), [confianza de reconocimiento en Vision](https://developer.apple.com/documentation/vision/vnrecognizedtext). Quedan como candidatos a comparar, no integrados, [PP-OCRv5](https://arxiv.org/abs/2603.24373) y [PaddleOCR-VL-1.5](https://arxiv.org/abs/2601.21957) para la rectificación de páginas curvas.

## Interfaz gráfica
`app.py` es una interfaz de Streamlit que conduce el pipeline entero sin tocar la línea de comandos:

```bash
streamlit run app.py
```

Los siete pasos de la página son, en orden:
1. **Entrada**: tres orígenes: un archivo suelto (PDF o TXT), un **vídeo del libro** (uno solo, o la carpeta con todos sus segmentos, o varios subidos a la vez), o una carpeta completa; por ruta o arrastrando el archivo. Un TXT se entiende como texto ya extraído. Con un vídeo aparecen sus ajustes: libro abierto (dos páginas por toma), recorte automático y, plegado, el ajuste fino del detector; el OCR del paso 2 pasa a ser obligatorio. Aquí se elige también el **idioma del libro**, que guía todo lo que se genera después: las descripciones de figuras y tablas salen en ese idioma, las instrucciones del corrector LLM lo mencionan, y el selector de voces del paso 5 se filtra con él, de modo que descripción y narrador siempre casan.
2. **OCR**: opcional. Tres motores: `macOS (Vision)` (el del sistema, el mismo de Vista Previa: gratis, local, ~4 s por página, el recomendado en Mac), `Ollama local` (modelos de visión, lento) o `Google Cloud Vision` (gratis hasta 1.000 páginas al mes, con ADC o llave JSON). Resolución de render configurable.
3. **Limpieza**: ninguna, solo reglas deterministas, solo corrección con el LLM local (el texto extraído va directo al modelo, sin reglas previas), o reglas más corrección con LLM.
4. **Texto limpio**: tres formatos combinables, siempre con el nombre del libro de entrada. `TXT` (el texto plano), `PDF solo texto` (el texto limpio maquetado en un PDF nuevo) y `PDF enriquecido` (las páginas originales como imagen con el texto limpio superpuesto en una capa invisible: el libro se ve tal cual era, pero se puede buscar, seleccionar y copiar — el clásico escaneo con OCR incorporado). El enriquecido necesita un PDF o un vídeo de entrada; en modo OCR usa las imágenes ya renderizadas (o las páginas sacadas del vídeo) y, sin OCR, renderiza las páginas del original.
5. **Voz**: una casilla «Generar audio» decide si el pipeline llega hasta la síntesis. Desmarcada, se detiene tras la limpieza y entrega solo el TXT o PDF del paso 4 (con aviso si no hay ningún formato marcado). Marcada, aparecen el motor de voz y la voz, filtrada por el idioma elegido en el paso 1, con un botón para escuchar una muestra antes de decidir.
6. **Formato del audio**: un único archivo largo, o un archivo por división lógica (los capítulos y secciones que detecta `pasos/pre-capitulos.py`).
7. **Ejecutar**: muestra la salida de cada script según avanza y deja los archivos intermedios y finales en la carpeta de trabajo, con reproductores y botones de descarga. Los archivos finales (texto, PDF y audiolibro único) llevan el nombre del archivo de entrada.

## Voces Siri en macOS
`say` no puede abrir las voces de Siri: pasarle el nombre (`say -v Simone`) cae en silencio a Samantha, y pasarle el identificador (`say -v com.apple.siri.natural.Simone`) falla con `Open speech channel failed: -244`. `AVSpeechSynthesisVoice` tampoco las expone, así que sustituir `say` por Swift o pyobjc no ayuda. La única vía es la voz de sistema de Contenido Hablado, que `say` sí usa cuando se le llama sin `-v`.

Por eso `MacTTS.voice` está a `null` en `config.json`: sin voz, manda la del sistema. Y para fijar una voz Siri concreta solo durante una ejecución existe `--vsiri`:

```bash
python3 pasos/pro-mac-tts.py --f cap1/ --o cap1/audio --vsiri com.apple.siri.natural.Simone
```

Guarda la preferencia actual, escribe la pedida, sintetiza sin `-v` y la restaura al terminar, también si la síntesis falla o si llega un SIGTERM. `--vsiri-idioma` fija el idioma al que se ata la voz; por omisión conserva el que ya hubiera configurado, o `en`.

Tres advertencias que van en serio:
- El cambio es **de todo el sistema** mientras dura: cualquier cosa que hable usará esa voz.
- La preferencia está bajo TCC. Si la escritura no cuaja, el script aborta diciéndolo, y la solución es dar Acceso Total al Disco al terminal.
- Para saber qué identificadores valen no hay API: ni `say -v '?'` ni `AVSpeechSynthesisVoice` listan las voces de Siri. El camino es elegir la voz una vez en Ajustes del Sistema y leerla:

```bash
defaults read com.apple.Accessibility SpokenContentDefaultVoiceSelectionsByLanguage
```

## Progreso en vivo
Durante la ejecución, además del registro de cada script, la interfaz muestra una barra de progreso por etapa con el conteo de elementos procesados y una proyección del tiempo restante medida sobre el ritmo real de esa corrida («Corrección con LLM: 12 de ~58 · quedan ~9 min de esta etapa»). Los totales con `~` son aproximados: las partes de audio dependen del troceado.

## Figuras y tablas narradas (avanzado)
Para libros con imágenes o tablas, la casilla «Avanzado: describir imágenes y tablas con el LLM» del paso 2 cambia la extracción a `pasos/pre-figuras.py`: recorre cada página en orden de lectura y, en el punto exacto donde aparece cada objeto, inserta una descripción generada por el LLM local («A continuación hay una tabla. Esta tabla compara…»), de modo que el audiolibro se entiende sin verlas.

```bash
python3 pasos/pre-figuras.py --f libro.pdf --o cap1/ --p 10-25
```

- Las tablas se detectan con PyMuPDF y las describe el modelo de texto a partir de sus celdas; si el modelo falla, se lee al menos su tamaño.
- Las descripciones y sus frases conectoras («A continuación hay una tabla…» / «There is a table here…») salen en el idioma del libro elegido en el paso 1 (`--idioma` en CLI: es, en, fr, it, pt, de).
- Las imágenes las describe un modelo con visión: uno local autodetectado (`Figuras.model_vision` en `config.json`) o un Gemini de Vertex, elegible en el selector que aparece al marcar la casilla (`--mv`/`--mt` en CLI). Con Gemini cada página baja de ~20 a ~6 segundos, con un coste pequeño por imagen. Los adornos minúsculos se ignoran (`min_lado`), y una imagen a página completa sin texto se trata como escaneo, no como figura.
- Cada descripción pasa por el saneado anti-repeticiones y sin markdown antes de entrar al texto.
- Con un PDF con capa de texto, la descripción se inserta en el punto exacto de lectura. Combinado con el modo OCR, cada página escaneada se inspecciona con el modelo de visión (`--img` en CLI): si contiene figuras, sus descripciones se añaden al final del texto de esa página; si es solo texto, queda intacta. Cuenta unos 10-30 segundos por objeto (o por página en modo OCR).
- La limpieza determinista expande abreviaturas según el idioma del libro: tablas propias para español e inglés («Mr.» → «Mister», «Baker St.» → «Baker Street» pero «St. Mary» → «Saint Mary», «&» → «and»/«y»). En otros idiomas las abreviaturas se dejan tal cual.

## Estimación de tiempo y coste
Antes de ejecutar nada, la interfaz mide el trabajo real (abre el PDF y cuenta las páginas y los caracteres de las que hayas seleccionado) y desglosa por etapa cuánto va a tardar y cuánto va a costar. `nucleo/estimacion.py` también se puede usar desde código:

```python
from nucleo import estimacion
paginas, caracteres = estimacion.medir_volumen(['book.pdf'], '1-58')
calculo = estimacion.estimar(paginas, caracteres, nivel_limpieza='Reglas + corrección con LLM',
                             motor_tts='Microsoft Edge', por_divisiones=True)
print(estimacion.formatear_duracion(calculo['segundos']), calculo['coste'])
```

El coste solo aparece con los motores de Google: la síntesis se cobra por carácter según la tarifa de la voz elegida en `config.json`, y Vision descuenta las primeras mil imágenes gratuitas del mes. Edge, macOS y Ollama salen a cero.

Los ritmos viven en la sección `Estimacion` de `config.json` y son los medidos en esta máquina, así que conviene recalibrarlos en otra. Para las 58 páginas de la novela de prueba, 341.921 caracteres:

| Configuración | Tiempo | Coste | Audio |
| --- | --- | --- | --- |
| Reglas + Edge | 32 min | gratis | 6 h 07 min |
| Reglas + LLM + Edge + capítulos | 14 h 20 min | gratis | 6 h 07 min |
| Reglas + LLM + macOS | 13 h 50 min | gratis | 6 h 07 min |
| OCR de Google + voz de Google | 34 min | $5,47 | 6 h 07 min |

La síntesis local de macOS es unas seis veces más rápida que Edge (1177 frente a 178 caracteres por segundo), porque no depende de la red.

El ritmo del LLM es con diferencia el más variable y el que domina el total: midiendo un fragmento suelto con el modelo ya cargado salen 72 caracteres por segundo, pero una página entera de punta a punta dio 6,9, que es el valor calibrado en `config.json`. La diferencia viene de la presión de memoria del modelo de 27B. Si vas a corregir un libro completo, mide primero una página con `pasos/pre-ollama.py` y ajusta `llm_caracteres_s` con tu número.

## Los agentes de línea de comandos como corrector
Las CLI de agentes instaladas en la máquina sirven como motor del paso de corrección, y con una ventaja sobre Ollama y Gemini: pueden **mirar la imagen de la página**. `pasos/pre-ollama.py` acepta como modelo `claude` (Claude Code), `codex` (OpenAI Codex), `agy` (Antigravity) y `gemini-cli`, y con `--img <carpeta>` manda a cada página su `pag_N.png`: el agente transcribe la página usando el OCR como borrador y la imagen como fuente de verdad, quita lo que el OCR inventó (restos de otra página, finales de línea repetidos) y marca `[ilegible]` lo que no se lee, sin inventarlo.

```bash
python3 pasos/pre-ollama.py --f cap1/texto --o cap1/texto_claude --m claude --img cap1/imagenes
python3 pasos/pre-ollama.py --f cap1/texto --o cap1/texto_codex --m codex --img cap1/imagenes
```

`nucleo/agentes.py` invoca cada CLI en su modo no interactivo (`claude -p` con la herramienta Read permitida, `codex exec` con `-i` para la imagen y el prompt por stdin, `agy -p`, `gemini -p --skip-trust`) dentro de una carpeta temporal a la que se copia la imagen, porque la sandbox de Codex no sale de su carpeta y un disco externo queda fuera; sin terminal, Codex espera el prompt por stdin, de ahí el `-`. Los guardarraíles de palabras conservadas y nuevas siguen vigentes, relajados en `Agentes.umbrales` de `config.json` porque quitar basura y marcar ilegibles cambia legítimamente el texto; `Agentes.modelos` fija el modelo de cada CLI (`claude: sonnet`) y `Agentes.timeout` acota una llamada colgada. En el libro de prueba de 116 páginas, Claude tardó unos 20 s por página y Codex unos 6 s; ambos aceptaron todas las páginas. Antigravity (`agy`) también funciona con imagen, pero tarda unos 75 s por página. Gemini CLI se invoca igual (`--skip-trust -y`), pero en esta máquina se queda colgado en cuanto se le adjunta una imagen, incluso en modo automático, así que no está validado. Cada corrección deja su informe de cambios en `informes/`, como con los demás motores.

## POC: la API de imágenes de TypeSafe System One
`utiles/poc-typesafe.py` prueba si las preguntas de imagen de TypeSafe (en fase «Dreamer-ready», no de producción) sirven para las decisiones que hoy toma el detector con heurísticas. Cuatro experimentos, cada uno contra una referencia conocida:

| Experimento | Pregunta | Referencia |
| --- | --- | --- |
| `estado` | Choice: texto plano, hoja a medio pasar, ilustración, en blanco, no es página | etiquetas a mano (`utiles/poc-typesafe/etiquetas_20261018.json`, 29 páginas; lo dudoso va en `null` y no cuenta) |
| `mano` | Noul: una mano tapa parte del texto | las mismas etiquetas |
| `misma` | Noul: dos imágenes son la misma página impresa (la decisión de deduplicar) | la misma página de dos corridas del mismo vídeo es «sí»; dos dobles páginas consecutivas, «no» |
| `box` | Box sobre el fotograma crudo: dónde está el libro abierto | la caja del cuadrilátero de Vision, comparada por IoU |

`--boveda [NOMBRE]` lee la clave de la bóveda passManager (`nucleo/boveda.py`): recorre los secretos `vault-0N` del proyecto `passmanager-jvl-9c2e` con `gcloud`, busca la credencial cuyo nombre contiene `NOMBRE` (por omisión `typesafe`) y toma su campo `api_key` o `token`; la clave solo vive en memoria. Va sobre HTTP directo, sin SDK: multipart con la parte `request` primero y una parte JPEG por imagen, referencias `img-<uuid>`, cabecera `TypeSafe-Danger-Zone-Images: true`, y `jev-preview` para Box (necesita Jev 1.14). Cada imagen se prepara como pide la documentación: píxeles girados (la API descarta el EXIF), lado mayor ≤ 1568, ambos lados ≥ 280, JPEG baseline. Sin `TYPESAFE_API_KEY`, o con `--simular`, construye y valida las peticiones y las deja en disco sin enviar nada.

```bash
python3 utiles/poc-typesafe.py --boveda --comprobar                       # clave desde la bóveda passManager; lista los modelos
TYPESAFE_API_KEY=... python3 utiles/poc-typesafe.py --comprobar          # o con la clave en el entorno
TYPESAFE_API_KEY=... python3 utiles/poc-typesafe.py \
  --img /Volumes/Seagate/audIAble/salida/nuevo_20261018_v5/imagenes \
  --otra-corrida /Volumes/Seagate/audIAble/salida/nuevo_20261018/imagenes \
  --etiquetas utiles/poc-typesafe/etiquetas_20261018.json
```

Deja `respuestas.json` (crudo), `resultados.json` (aciertos por experimento, IoU, latencia y tokens) y `cajas.jpg` (caja de TypeSafe en rojo, la de Vision en azul) en `<img>/../poc_typesafe`. `tests/test_poc_typesafe.py` lo ejecuta contra un servidor simulado que aplica las reglas de la documentación (orden de las partes, cabeceras, referencias, tipos y dimensiones de imagen, Jev 1.14 para Box); no sustituye a la API real, que es la que da la precisión.

### Resultados de la primera corrida (2026-10-19)
Sobre el libro grabado el 18 a las 20:21 (corrida v5), 65 peticiones, `jev-latest` y `jev-preview`:

| Experimento | Resultado |
| --- | --- |
| `estado` | 24 de 24 páginas etiquetadas |
| `mano` | 24 de 24 (tras revisar 4 etiquetas en las que me había equivocado yo, no el modelo) |
| `misma` | 24 de 24, con márgenes amplios: pares iguales entre 0,93 y 0,99 (salvo la cubierta, 0,57), pares distintos por debajo de 0,13 |
| `box` | IoU mediano 0,92 con la caja de Vision; 10 de 12 por encima de 0,8. El único IoU 0 es un fotograma con el libro cerrado: Vision encuadró la mesa y TypeSafe respondió «no hay libro abierto» (0,16) |
| Coste | 200 652 tokens de entrada (unos 3 000 por imagen), latencia mediana 0,6 s, 21 s en total con 4 peticiones a la vez |

Lo que sugiere para el pipeline: la pregunta `misma` puede sustituir o confirmar la deduplicación por cuatrigramas, sobre todo en páginas con poco texto, donde hoy se recurre a la correlación de imagen; `mano` distingue dedos sobre el texto de dedos en el margen, cosa que la máscara de piel no hace, y serviría para elegir la captura de referencia o marcar páginas a corregir; `estado` automatiza la limpieza que hoy se hace a mano con la hoja de contactos (cubierta, mesa, hojas a medio pasar). Box no sustituye a Vision para recortar, porque da una caja alineada con los ejes y no un cuadrilátero con perspectiva, pero su Noul acompañante sirve para vetar fotogramas en los que Vision encuadra cualquier cosa. La muestra es pequeña (un libro, 29 páginas etiquetadas por una sola persona) y la API está en fase de prototipo.

## OCR multifotograma
La página final es una sola imagen fusionada, pero cada página se grabó en varias capturas, cada una con la mano en otro sitio, otro reflejo, otro desenfoque. `pasos/pro-multiframe-ocr.py` las lee todas:

1. `pre-video.py --guardar-capturas` deja las capturas de cada página en `capturas/pag_N/cap_K.png`, recortadas, giradas y partidas por el lomo igual que la página final.
2. Por omisión se usan todas las capturas. Con `--con-typesafe`, TypeSafe las filtra antes, una petición por página con todas en el estado: cuentan las que muestran la misma página que la imagen final y la hoja quieta. Va apagado porque en el libro de prueba no aportó una mejora medible (véanse las repeticiones más abajo) y cuesta 1,5 millones de tokens por libro.
3. Vision lee la imagen final y cada captura válida, con confianza y caja por renglón.
4. Fusión: cada captura se **ancla** a la imagen final por los renglones cuyo texto casi coincide (al menos tres), y con ellos se ajusta un desplazamiento y una escala que llevan todas sus cajas al marco de la imagen final; sin anclas, la captura no aporta. Así se evita el fallo de la primera versión, que agrupaba por posición absoluta: una captura desplazada dos renglones colaba la página entera por duplicado. Cada renglón de la imagen final abre su grupo; cada renglón de captura se une solo al grupo que mejor le encaja; cada grupo se queda con la lectura más fiable. Un renglón que la imagen final no tiene se acepta como recuperado si es fiable, largo o visto por dos capturas, y no está ya en otro sitio de la página.

Deja `pag_N.txt` como el OCR de siempre, e `informes/pag_N.fusion.json` con lo recuperado y lo mejorado. El corrector con agente tiene una variante para estos borradores (`pre-ollama.py --borrador-multiple`): avisa al agente de que el borrador viene de varias fotos y de que, donde la imagen esté tapada, no debe cambiar un texto coherente por `[ilegible]`.

**Es el flujo por omisión para vídeo**: la interfaz y `procesar-biblioteca.py` llaman a `pre-video.py --guardar-capturas` y, con el motor de macOS, al OCR multifotograma en vez de a `pro-mac-ocr.py`; y si el corrector elegido es una CLI de agente (ahora en el selector del paso 3), le pasan la imagen de cada página y el aviso de borrador múltiple.

`utiles/comparar-multiframe.py --video <vídeo> --o <carpeta> --agente claude` es el banco de pruebas: detecta las páginas una vez y corre las dos cadenas sobre las mismas imágenes y con el mismo corrector, A con una imagen por página y B multifotograma, y deja `comparacion.json` y `comparacion.md` con los `[ilegible]` que quedan tras el agente, los renglones dudosos de Vision, el texto recuperado, las palabras sospechosas y los fragmentos duplicados.

### Resultados sobre el libro grabado el 18 a las 20:21 (116 páginas, corrector Claude)

| Indicador | A · una imagen | B · multifotograma |
| --- | --- | --- |
| `[ilegible]` tras el agente | 214 | 32 |
| Páginas con algún `[ilegible]` | 35 | 10 |
| Renglones dudosos de Vision | 41 | 22 |
| Palabras sin respaldo en el OCR | 267 | 229 |

La fusión recuperó 130 renglones y mejoró 574. TypeSafe descartó 118 de 696 capturas: 39 por mostrar otra página y 79 por hoja en movimiento; gastó 1,5 millones de tokens de entrada.

El control importa: corregir el OCR de una sola imagen con la instrucción de B (sin multifotograma) también reduce los ilegibles en las 34 páginas que cambian, de 198 a 62, pero sube las palabras sin respaldo de 107 a 149, porque el agente completa a ciegas. En la página 47 escribe «Karla se reducía», mientras B, que leyó la captura donde la mano estaba más apartada, escribe «Karla se introducía». B llega a 16 ilegibles con 97 palabras sin respaldo: menos ilegibles y menos invención que el método actual. Las palabras sin respaldo son las del texto final que ninguna palabra del borrador del OCR respalda, ni exacta ni con un 80 % de parecido.

### Repeticiones y el papel de Jev (2026-10-20)
El corrector no es determinista: con el mismo borrador, Claude a veces declara ilegible una página entera (22 marcas) que en otra corrida transcribe completa. Para separar señal de ruido se repitió la corrección de A y de B sobre los mismos borradores, y se corrió B sin el filtro de TypeSafe (D, `--sin-typesafe`):

| Corrida | `[ilegible]` | Páginas con 10 o más | `[ilegible]` en el resto | Palabras sin respaldo |
| --- | --- | --- | --- | --- |
| A · 1 | 214 | 8 | 69 | 267 |
| A · 2 | 247 | 9 | 69 | 230 |
| B · 1 | 32 | 1 | 19 | 229 |
| B · 2 | 45 | 2 | 10 | 224 |
| D · B sin Jev | 80 | 3 | 24 | 208 |

La ganancia del multifotograma es robusta: entre 214 y 247 ilegibles con una imagen, entre 32 y 45 con varias, y en el texto que no se declara ilegible entero, 69 frente a 10-19. El filtro de Jev no muestra una ventaja clara: en 95 de 116 páginas el borrador con y sin filtro es idéntico, y la diferencia restante cabe en el ruido del corrector con una sola corrida de D. Antes del corrector, donde no hay azar, los dos borradores son casi iguales (22 renglones dudosos de Vision en ambos). Con 1,5 millones de tokens por libro, Jev no se justifica; por eso el multifotograma va **sin Jev por omisión** (`--con-typesafe` lo activa).

Lo que las repeticiones enseñaron, ya corregido: el corrector a veces declara ilegible una página entera que en otra corrida transcribe (8-9 páginas de 116 con una imagen, 1-2 con multifotograma), y eso explicaba la mayor parte de la varianza. `pre-ollama.py` lo frena con un guardarraíl: si la respuesta trae más de `max(4, 2 × dudosos + 2)` marcas `[ilegible]`, donde `dudosos` son los renglones con confianza menor de 0,5 del informe de fusión de esa página (o, sin informe, los huecos que ya traía el borrador), pide una segunda lectura, y si el agente insiste, **injerta** el borrador: conserva la lectura del agente (sus correcciones y sus párrafos) y rellena solo los tramos marcados `[ilegible]` con las palabras que el OCR leyó en ese mismo tramo, alineando los dos textos palabra a palabra; una marca suelta para la que el OCR no tiene palabras desaparece. Así la página no pierde ni la corrección del agente ni el texto que el OCR sí leyó. Lo apunta en el registro («N tramos ilegibles rellenados con el OCR»).

## Modelos de Google como corrector (Vertex AI)
Con las credenciales de Google resueltas (ADC o llave), el selector «Modelo de corrección» ofrece además los Gemini de Vertex (`GoogleLLM.models` en `config.json`): `gemini-2.5-flash`, `gemini-2.5-flash-lite` y `gemini-2.5-pro`. Sirven tanto para la corrección del escaneado como para la detección de capítulos, con los mismos guardarraíles anti-alucinación que los modelos locales, y por CLI basta el nombre: `python3 pasos/pre-ollama.py --f cap1/ --m gemini-2.5-flash`.

La diferencia es dramática en máquinas donde el modelo local va lento: la misma página que al modelo local de 27B le costó 839 segundos, Gemini Flash la corrigió en 10 (~578 caracteres por segundo, calibrado en `Estimacion.llm_gemini_caracteres_s`). A cambio tiene coste por carácter (tarifas orientativas en `GoogleLLM.usd_por_1000_car`, editables): la novela de prueba completa sale por unos $0.24 con Flash o $0.04 con Flash-Lite, frente a las ~14 horas gratuitas del modelo local. La estimación muestra tiempo y coste de cada opción antes de ejecutar. El razonamiento interno de los modelos flash se desactiva (`thinking_budget=0`): para tareas mecánicas solo añadiría coste y latencia.

## Corrección del escaneado con un LLM local
Las reglas deterministas de `pasos/pre-cleanup.py` arreglan lo que tiene forma fija: envoltura de líneas, guiones de corte, incisos, abreviaturas, espacios y números de página. Lo que no tiene forma fija (palabras que el escáner partió o pegó, letras mal reconocidas, frases entrelazadas fuera de orden) lo repara `pasos/pre-ollama.py` contra un servidor de Ollama en local:

```bash
python3 pasos/pre-ollama.py --check
python3 pasos/pre-ollama.py --f cap1/ocr/ --o cap1/revisado
```

Cada trozo corregido se compara con el original antes de aceptarlo: se miden la variación de longitud, el porcentaje de palabras conservadas y el de palabras nuevas. Un modelo que reordena líneas entrelazadas reutiliza las mismas palabras, mientras que uno que alucina trae las suyas, así que el trozo que se pasa de los umbrales de `config.json` se descarta y se conserva el original. Junto a cada archivo se escribe un `.cambios.txt` con el diff frase a frase para poder auditar qué tocó el modelo.

Ojo con el modelo: en mis pruebas sobre esta novela, `qwen3.5:9b-mlx` dejó el entrelazado sin resolver e inventó texto, mientras que `qwen3.8:27b-mlx` lo reconstruyó correctamente a unos 17 tokens por segundo, alrededor de 80 segundos por página.

## Features
- Command-line interface for easy execution.
- Ability to split large text into smaller parts to manage Text-to-Speech API limitations.
- Checks for existing audio files to avoid redundant processing.
- Audio properties like pitch and speed are customizable via the `config.json` file.

## Function Overview
- `split_text()`: Splits text into smaller parts.
- `generate_text_audio()`: Generates audio for a specific text file.
- `generate_audio()`: Driver function to process all text files in the input folder.


## Inline Comments from Code Files

### pasos/pro-gcp-ocr.py

- Configuring Google Cloud Platform credentials
- Parsing command line arguments
- Importing required libraries
- Setting up Google Cloud Platform credentials
- Setting up command line arguments
- Initializing Vision client
- Setting up file directories
- Creating output directory if it doesn't exist
- Loading JSON configurations
- Function to process images and generate text files
- Iterating over each image in the input folder
- Processing only jpg and png images
- Processing the image only if its corresponding text file doesn't exist
- Opening the image file
- Using the Vision API to detect text in the image
- Extracting the detected text
- Writing the extracted text to a file
- Calling the function to process images

### pasos/pre-pdf.py

- Importing required libraries
- Function to split pages from a PDF and save as text files
- Opening the PDF file
- If no specific pages are provided, processing all pages
- Looping through each page
- Extracting text from the page
- Constructing the output file path
- Writing the extracted text to the output file
- Function to convert pages from a PDF to images
- Opening the PDF document
- If no specific pages are provided, processing all pages
- Looping through each page
- Converting the page to an image
- Saving the image to the output folder
- Function to parse the pages argument
- If a range of pages is provided
- If specific pages are provided
- Main function to handle command line arguments and call the appropriate function
- Adding command line arguments for the pages, PDF file path, output folder, and mode
- Parsing the command line arguments
- Checking if the mode is valid
- Parsing the pages argument if provided
- Creating the output folder if it doesn't exist
- Calling the appropriate function based on the mode

### pasos/pre-cleanup.py

- Importing required libraries
- Function to process all text files in a directory
- Looping through each file in the directory
- Checking if the file is a text file
- Constructing the full filepath
- Opening and reading the file
- Using BeautifulSoup to clean up HTML tags in the text
- Using NLTK for sentence tokenization
- Combining sentences with two line breaks for new paragraphs
- Various text clean-up operations for TTS
- - Removing hyphens between words
- - Replacing multiple spaces with a single space
- - Removing space before commas
-- Replacing '&' with 'and'
- Writing the cleaned up text back to the file
- Printing a success message when all files have been processed
- Printing an error message if something goes wrong
- Main function to handle command line arguments and call the processing function
- Adding a command line argument for the directory path
- Parsing the command line arguments
- Calling the processing function with the directory path argument

### pasos/pro-gcp-tts.py

- Importing required libraries
- Setting up Google Cloud Platform credentials
- Setting up command line arguments
- Initializing Text-to-Speech client
- Setting up file directories
- Creating output folder if it does not exist
- Loading JSON configurations
- Function to split text into parts of maximum size max_bytes
- Function to generate audio from a text file
- Iterating over each part of the text
- Skipping the part if its corresponding audio file already exists
- Setting up the input text, voice and audio configuration for the Text-to-Speech API
- Using the Text-to-Speech API to synthesize speech
- Writing the synthesized speech to an audio file
- Function to generate audio from all text files in the input folder
- Running the function to generate audio

### utiles/demo-voices.py

- Importing required libraries
- Loading JSON configurations
- Sample sentence per language, so every voice is demoed in its own language
- Setting up command line arguments
- Locale filters are normalized so es-MX and es_MX both work for either engine
- Function to build the sentence a voice reads: its own name and then the sample
- Function to turn a voice name into a safe file name
- Function to list the Edge TTS voices
- Function to list the macOS voices
- Function to synthesize one sample with Edge TTS
- Function to synthesize one sample with the "say" command
- Function to join WAV samples into a single file, with a short silence between voices
- Function to join MP3 samples into a single file
- Function to generate one sample per voice and the joined demo
- Running the function to generate the demo

### pasos/pro-edge-tts.py

- Importing required libraries
- Loading JSON configurations
- Setting up command line arguments
- Edge TTS settings, with the command line voice taking precedence over config.json
- Function to print the available voices
- Setting up file directories
- Creating output folder if it does not exist
- Function to split text into parts of maximum size max_bytes
- Function to synthesize a single part, writing to a temporary file so an interrupted run never leaves a truncated audio behind
- Function to generate audio from a text file
- Function to generate audio from all text files in the input folder
- Running the function to generate audio

### pasos/pro-mac-tts.py

- Importing required libraries
- Loading JSON configurations
- Setting up command line arguments
- macOS settings, with the command line voice taking precedence over config.json
- Listing the voices installed in the system
- Setting up file directories
- Creating output folder if it does not exist
- Function to split text into parts of maximum size max_bytes
- Function to synthesize a single part with the "say" command
- Function to generate audio from a text file
- Function to generate audio from all text files in the input folder
- Running the function to generate audio

## Contributing
Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

## License
This project is licensed under the MIT License.
