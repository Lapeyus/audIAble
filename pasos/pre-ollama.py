# Importing required libraries
import re
import sys
import json
import time
import difflib
import argparse
import urllib.error
import urllib.request
from pathlib import Path
from collections import Counter

# La raíz del repositorio queda un nivel por encima de esta carpeta
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from nucleo.limpieza import colapsar_repeticiones, normalizar_pausas

from nucleo import gemini, ollama_local


# Load JSON configurations
with open(RAIZ / 'config.json') as f:
    config = json.load(f)

settings = config['OllamaCleanup']

# The instructions are deliberately narrow: the model is a proof reader of scan
# damage, not an editor. Everything it is allowed to touch is listed one by one
NOMBRES_IDIOMA = {'es': 'español', 'en': 'inglés', 'fr': 'francés', 'it': 'italiano', 'pt': 'portugués', 'de': 'alemán'}

INSTRUCCIONES = """Eres un corrector de textos extraídos por OCR de un libro en {idioma}.

Corrige ÚNICAMENTE los daños del escaneado:
- palabras pegadas ("abuscar" -> "a buscar") o partidas ("fa llones" -> "fallones")
- letras mal reconocidas ("ALEAGUARA" -> "ALFAGUARA") y tildes que falten ("Fotografia" -> "Fotografía")
- trozos de frases entrelazados fuera de orden: reordénalos para que las frases recuperen su sentido
- números de página sueltos en medio del texto: elimínalos
- separa en párrafos donde corresponda

PROHIBIDO: cambiar el estilo o el vocabulario, añadir o quitar contenido, resumir, comentar o traducir.
PROHIBIDO también usar markdown: nada de asteriscos, guiones bajos ni almohadillas, porque el texto se lee en voz alta.
Si un fragmento es irrecuperable, déjalo tal cual.
Devuelve SOLO el texto corregido, sin introducción ni explicaciones.

TEXTO:
"""

# Command line arguments setup
parser = argparse.ArgumentParser(description='Validate and repair OCR damage in the extracted text with a local Ollama model.')
parser.add_argument('--f', dest='folder_input', help='Folder with the cleaned text files to review.')
parser.add_argument('--o', dest='folder_output', help='Folder to write the reviewed files. Overwrites in place if omitted.')
parser.add_argument('--m', dest='model', help='Ollama model to use, overrides the one in config.json.')
parser.add_argument('--dryrun', dest='dryrun', action='store_true', help='Report the chunks that would be sent without calling the model.')
parser.add_argument('--check', dest='check', action='store_true', help='Check that the Ollama server answers and the model is installed, then exit.')
parser.add_argument('--idioma', dest='idioma', default='es', choices=sorted(NOMBRES_IDIOMA), help='Language of the book, used in the correction instructions.')
args = parser.parse_args()

modelo = args.model or settings['model']

# Function to talk to the Ollama HTTP API
def pedir_a_ollama(ruta, cuerpo=None, timeout=30):
    url = f"{settings['host']}{ruta}"
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    peticion = urllib.request.Request(url, datos, {'Content-Type': 'application/json'})
    with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
        return json.loads(respuesta.read())

# Function to make sure the server is up and settle on a model. The one in
# config.json is used when it is installed, and otherwise the best installed
# candidate for this task is picked instead of failing
def comprobar_servidor():
    global modelo
    if gemini.es_modelo_google(modelo):
        return [modelo]
    try:
        disponibles = ollama_local.modelos_para(settings['host'], 'texto')
    except Exception as error:
        sys.exit(f"No responde Ollama en {settings['host']}: {error}\nArráncalo con: ollama serve")
    try:
        modelo, autodetectado = ollama_local.elegir_modelo(settings['host'], modelo, 'texto')
    except RuntimeError as error:
        sys.exit(str(error))
    if autodetectado:
        print(f'El modelo pedido no está instalado, se usa {modelo} (detectado entre: {", ".join(disponibles)})', flush=True)
    return disponibles

# Function to split the text into chunks the model can hold, never cutting a
# sentence in two: whole paragraphs first, then sentences, then words
def dividir_en_trozos(texto, max_chars):
    partes = []
    for parrafo in [p for p in texto.split('\n\n') if p.strip()]:
        if len(parrafo) <= max_chars:
            partes.append(parrafo)
            continue
        frase = ''
        for pieza in re.split(r'(?<=[.!?…])\s+', parrafo):
            if len(frase) + len(pieza) + 1 <= max_chars:
                frase = f'{frase} {pieza}'.strip()
            else:
                if frase:
                    partes.append(frase)
                frase = pieza
        if frase:
            partes.append(frase)

    trozos, actual = [], ''
    for parte in partes:
        if actual and len(actual) + len(parte) + 2 > max_chars:
            trozos.append(actual)
            actual = parte
        else:
            actual = f'{actual}\n\n{parte}' if actual else parte
    if actual:
        trozos.append(actual)
    return trozos

# Function to reduce a text to its bag of words, to compare what the model did
def palabras(texto):
    return Counter(re.findall(r"[0-9a-záéíóúüñç']+", texto.lower()))

# Function to decide whether a correction is a repair or an invention. A model
# that reorders scrambled lines reuses the same words, one that hallucinates
# brings its own, so the words are compared as multisets instead of by position
def validar(original, corregido):
    if not corregido.strip():
        return False, 'respuesta vacía'

    proporcion = len(corregido) / max(len(original), 1)
    minimo, maximo = settings['length_range']
    if not minimo <= proporcion <= maximo:
        return False, f'longitud {proporcion:.0%} del original'

    original_palabras, corregidas = palabras(original), palabras(corregido)
    total_original = max(sum(original_palabras.values()), 1)
    total_corregido = max(sum(corregidas.values()), 1)
    conservadas = sum((original_palabras & corregidas).values()) / total_original
    nuevas = sum((corregidas - original_palabras).values()) / total_corregido

    if conservadas < settings['min_word_retention']:
        return False, f'solo conserva el {conservadas:.0%} de las palabras'
    if nuevas > settings['max_new_words']:
        return False, f'introduce un {nuevas:.0%} de palabras nuevas'
    return True, f'{conservadas:.0%} conservadas, {nuevas:.0%} nuevas'

# Function to strip the preamble and the markdown a chatty model may add despite
# the instructions. The emphasis marks matter: a TTS engine reads them out loud
def limpiar_respuesta(respuesta):
    respuesta = re.sub(r'^```[a-z]*\n|\n```$', '', respuesta.strip())
    lineas = respuesta.split('\n')
    if lineas and len(lineas[0]) < 80 and lineas[0].rstrip().endswith(':'):
        respuesta = '\n'.join(lineas[1:])
    respuesta = re.sub(r'\*\*([^*\n]+)\*\*', r'\1', respuesta)
    respuesta = re.sub(r'(?<!\w)\*([^*\n]+)\*(?!\w)', r'\1', respuesta)
    respuesta = re.sub(r'(?<!\w)_([^_\n]+)_(?!\w)', r'\1', respuesta)
    respuesta = re.sub(r'(?m)^#{1,6}\s+', '', respuesta)
    # el modelo devuelve el texto troceado en muchas líneas, y cada salto suelto
    # es una pausa de más al leerlo en voz alta
    return normalizar_pausas(colapsar_repeticiones(respuesta))

# Function to send one chunk to the model and get the corrected text back
def corregir_trozo(trozo, reintentos=2):
    for intento in range(1, reintentos + 1):
        try:
            if gemini.es_modelo_google(modelo):
                return limpiar_respuesta(gemini.generar(
                    modelo, INSTRUCCIONES.format(idioma=NOMBRES_IDIOMA[args.idioma]) + trozo,
                    temperatura=settings['temperature']))
            respuesta = pedir_a_ollama('/api/generate', {
                'model': modelo,
                'prompt': INSTRUCCIONES.format(idioma=NOMBRES_IDIOMA[args.idioma]) + trozo,
                'stream': False,
                'think': False,
                'options': {'temperature': settings['temperature']}
            }, timeout=settings['timeout'])
            return limpiar_respuesta(respuesta['response'])
        except Exception as error:
            if intento == reintentos:
                raise
            print(f'    reintento {intento}: {error}', flush=True)
            time.sleep(2 * intento)

# Function to write a readable report of what the model changed
def escribir_informe(ruta_informe, original, corregido, incidencias):
    frases = lambda t: [f for f in re.split(r'(?<=[.!?…])\s+', t.replace('\n\n', '\n')) if f.strip()]
    diferencias = difflib.unified_diff(frases(original), frases(corregido), 'antes', 'después', lineterm='', n=0)
    with open(ruta_informe, 'w', encoding='utf-8') as informe:
        informe.write(f'Modelo: {modelo}\n')
        for incidencia in incidencias:
            informe.write(f'{incidencia}\n')
        informe.write('\n')
        informe.write('\n'.join(diferencias))
        informe.write('\n')

# Function to tell a page of the book from a report left by a previous run
def es_pagina(ruta):
    return ruta.suffix == '.txt' and not ruta.name.endswith('.cambios.txt')


# Function to review every text file in the input folder
def revisar_directorio():
    folder_input = Path(args.folder_input)
    folder_output = Path(args.folder_output) if args.folder_output else folder_input
    folder_output.mkdir(parents=True, exist_ok=True)

    archivos = sorted(a for a in folder_input.iterdir() if es_pagina(a))
    aceptados = rechazados = 0

    for archivo in archivos:
        original = archivo.read_text(encoding='utf-8')
        if len(original.strip()) < 20:
            # una página vacía no tiene nada que corregir y gastaría una llamada
            # al modelo; se copia tal cual y se sigue
            (folder_output / archivo.name).write_text(original, encoding='utf-8')
            print(f'{archivo.name}: prácticamente vacía, se salta', flush=True)
            continue
        trozos = dividir_en_trozos(original, settings['chunk_chars'])
        print(f'{archivo.name}: {len(original)} caracteres en {len(trozos)} trozo(s)', flush=True)

        if args.dryrun:
            continue

        inicio = time.time()
        resultado, incidencias = [], []
        for i, trozo in enumerate(trozos, 1):
            corregido = corregir_trozo(trozo)
            valido, motivo = validar(trozo, corregido)
            if valido:
                aceptados += 1
                resultado.append(corregido)
            else:
                rechazados += 1
                resultado.append(trozo)
                incidencias.append(f'  trozo {i}/{len(trozos)} RECHAZADO ({motivo}), se conserva el original')
            print(f'  trozo {i}/{len(trozos)}: {"ok" if valido else "RECHAZADO"} - {motivo}', flush=True)

        texto_final = '\n\n'.join(resultado) + '\n'
        (folder_output / archivo.name).write_text(texto_final, encoding='utf-8')
        # el informe va a una subcarpeta: si se quedara junto a las páginas, el
        # TTS lo tomaría por texto del libro y lo leería en voz alta
        carpeta_informes = folder_output / 'informes'
        carpeta_informes.mkdir(parents=True, exist_ok=True)
        escribir_informe(carpeta_informes / f'{archivo.stem}.cambios.txt', original, texto_final, incidencias)
        print(f'  -> {folder_output / archivo.name} ({time.time() - inicio:.0f}s, informe en informes/{archivo.stem}.cambios.txt)', flush=True)

    print(f'\nTrozos aceptados: {aceptados} | rechazados: {rechazados}', flush=True)

if args.check:
    instalados = comprobar_servidor()
    print(f"Ollama responde en {settings['host']}, se usará el modelo {modelo}.")
    print(f"Candidatos detectados: {', '.join(instalados)}")
    sys.exit(0)

if not args.folder_input:
    parser.error('--f es obligatorio salvo con --check.')

if not args.dryrun:
    comprobar_servidor()

revisar_directorio()
