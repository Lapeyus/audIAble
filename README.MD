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
utiles/           herramientas sueltas: demos de voces, unir y resumir
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

## Interfaz gráfica
`app.py` es una interfaz de Streamlit que conduce el pipeline entero sin tocar la línea de comandos:

```bash
streamlit run app.py
```

Los siete pasos de la página son, en orden:
1. **Entrada**: un archivo suelto (PDF o TXT) o una carpeta completa, por ruta o arrastrando el archivo. Un TXT se entiende como texto ya extraído. Aquí se elige también el **idioma del libro**, que guía todo lo que se genera después: las descripciones de figuras y tablas salen en ese idioma, las instrucciones del corrector LLM lo mencionan, y el selector de voces del paso 5 se filtra con él, de modo que descripción y narrador siempre casan.
2. **OCR**: opcional. Tres motores: `macOS (Vision)` (el del sistema, el mismo de Vista Previa: gratis, local, ~4 s por página, el recomendado en Mac), `Ollama local` (modelos de visión, lento) o `Google Cloud Vision` (gratis hasta 1.000 páginas al mes, con ADC o llave JSON). Resolución de render configurable.
3. **Limpieza**: ninguna, solo reglas deterministas, solo corrección con el LLM local (el texto extraído va directo al modelo, sin reglas previas), o reglas más corrección con LLM.
4. **Texto limpio**: tres formatos combinables, siempre con el nombre del libro de entrada. `TXT` (el texto plano), `PDF solo texto` (el texto limpio maquetado en un PDF nuevo) y `PDF enriquecido` (las páginas originales como imagen con el texto limpio superpuesto en una capa invisible: el libro se ve tal cual era, pero se puede buscar, seleccionar y copiar — el clásico escaneo con OCR incorporado). El enriquecido necesita un PDF de entrada; en modo OCR usa las imágenes ya renderizadas y, sin OCR, renderiza las páginas del original.
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
