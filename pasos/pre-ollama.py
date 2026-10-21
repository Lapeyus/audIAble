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

from nucleo import gemini, ollama_local, agentes


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

# With the page image in front, the agent corrects against the source instead
# of guessing: it is a transcription, with the OCR as a draft
INSTRUCCIONES_IMAGEN = """Esta imagen es una página de un libro en {idioma}, y debajo va el texto que un OCR leyó de ella, con errores.
Devuelve la transcripción fiel de la página, usando el OCR como borrador y la imagen como fuente de verdad:
- corrige las letras mal leídas, las palabras partidas o pegadas y las tildes
- quita lo que el OCR inventó y no está en la página (restos de otra página, finales de línea repetidos, números sueltos)
- separa en párrafos donde la página los tenga; une las líneas de un mismo párrafo
- si una zona es ilegible en la imagen, escribe [ilegible] en su lugar; no la inventes
PROHIBIDO cambiar el estilo o el vocabulario, resumir, comentar, traducir o usar markdown.
Devuelve SOLO el texto, sin introducción ni explicaciones.

OCR:
"""

# With a multi-frame draft the OCR saw several photos of the page: text that a
# hand covers in this image may be right in the draft, and must not be dropped
INSTRUCCIONES_MULTIPLE = """Esta imagen es una página de un libro en {idioma}, y debajo va un borrador de su texto que un OCR armó leyendo VARIAS fotos de la misma página: donde en esta foto una mano o un reflejo tapa el texto, el borrador puede haberlo leído bien en otra foto.
Devuelve la transcripción fiel de la página:
- corrige las letras mal leídas, las palabras partidas o pegadas y las tildes, comparando con la imagen donde se vea
- donde la imagen esté tapada u oculta y el borrador traiga texto coherente con lo que lo rodea, CONSÉRVALO tal cual: no lo cambies por [ilegible]
- quita lo que no es de la página (restos de la página de enfrente, renglones repetidos, números sueltos)
- separa en párrafos donde la página los tenga; une las líneas de un mismo párrafo
- escribe [ilegible] solo donde ni la imagen ni el borrador permitan leer el texto
PROHIBIDO cambiar el estilo o el vocabulario, resumir, comentar, traducir o usar markdown.
Devuelve SOLO el texto, sin introducción ni explicaciones.

BORRADOR:
"""

# Command line arguments setup
parser = argparse.ArgumentParser(description='Validate and repair OCR damage in the extracted text with a local Ollama model, '
                                             'a Gemini model, or one of the agent CLIs installed on this machine '
                                             f'({", ".join(agentes.AGENTES)}), which can also look at the page image.')
parser.add_argument('--f', dest='folder_input', help='Folder with the cleaned text files to review.')
parser.add_argument('--o', dest='folder_output', help='Folder to write the reviewed files. Overwrites in place if omitted.')
parser.add_argument('--m', dest='model', help='Ollama model to use, overrides the one in config.json.')
parser.add_argument('--dryrun', dest='dryrun', action='store_true', help='Report the chunks that would be sent without calling the model.')
parser.add_argument('--check', dest='check', action='store_true', help='Check that the Ollama server answers and the model is installed, then exit.')
parser.add_argument('--idioma', dest='idioma', default='es', choices=sorted(NOMBRES_IDIOMA), help='Language of the book, used in the correction instructions.')
parser.add_argument('--borrador-multiple', dest='borrador_multiple', action='store_true',
                    help='The text comes from the multi-frame OCR: tell the agent the draft may be right where the image is covered.')
parser.add_argument('--img', dest='carpeta_img', default=None,
                    help='Folder with the page images (pag_N.png). With an agent CLI, each page is corrected looking at its image.')
args = parser.parse_args()

modelo = args.model or settings['model']
if agentes.es_agente(modelo):
    # los agentes transcriben mirando la página: quitan lo que el OCR inventó y
    # marcan lo ilegible, así que los guardarraíles se relajan un poco
    settings = dict(settings, **config.get('Agentes', {}).get('umbrales', {}))
    settings['chunk_chars'] = 100000

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
    if agentes.es_agente(modelo):
        if modelo not in agentes.disponibles():
            sys.exit(f'La CLI de {modelo} no está en el PATH')
        return [modelo]
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
def corregir_trozo(trozo, reintentos=2, imagen=None):
    for intento in range(1, reintentos + 1):
        try:
            if agentes.es_agente(modelo):
                ajustes = config.get('Agentes', {})
                if imagen is not None:
                    plantilla = INSTRUCCIONES_MULTIPLE if args.borrador_multiple else INSTRUCCIONES_IMAGEN
                    prompt = plantilla.format(idioma=NOMBRES_IDIOMA[args.idioma]) + trozo
                else:
                    prompt = INSTRUCCIONES.format(idioma=NOMBRES_IDIOMA[args.idioma]) + trozo
                return limpiar_respuesta(agentes.generar(modelo, prompt, [imagen] if imagen is not None else (),
                                                         modelo=ajustes.get('modelos', {}).get(modelo),
                                                         timeout=ajustes.get('timeout', 300)))
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

# Function to tell whether the agent gave up on a page it could have read: the
# answer carries many more [ilegible] marks than the OCR had doubtful lines.
# The agent is not deterministic, and on the same draft it sometimes declares a
# whole page illegible (20 marks) that another run transcribes in full. The
# multi-frame OCR leaves the number of doubtful lines of each page in its
# fusion report; without it, the OCR reading itself is the reference
def ilegibles_excesivos(archivo, trozo, corregido):
    marcas = len(re.findall(r'\[ilegible\]', corregido, re.I))
    if marcas <= 4:
        return False, marcas, None
    informe = Path(args.folder_input) / 'informes' / f'{archivo.stem}.fusion.json'
    dudosos = None
    if informe.exists():
        try:
            dudosos = json.loads(informe.read_text(encoding='utf-8')).get('dudosos_fusion')
        except (ValueError, OSError):
            dudosos = None
    if dudosos is None:
        # sin informe: el borrador ya traía sus propios huecos, y el agente no
        # debería añadir muchos más que los que el OCR dejó en blanco
        dudosos = len(re.findall(r'\[ilegible\]', trozo, re.I))
    return marcas > max(4, 2 * dudosos + 2), marcas, dudosos


# Function to keep the agent's reading (its corrections and paragraphs) and fill
# only the spans it marked [ilegible] with the OCR draft's words. The two texts
# are aligned word by word; where the agent's side of a difference carries an
# [ilegible], the draft's side goes in its place; a bare [ilegible] the draft
# has no words for is dropped. Paragraph breaks of the agent survive as tokens
def injertar_borrador(borrador, corregido):
    marca = re.compile(r'\[ilegible\]', re.I)
    palabras_borrador = borrador.split()
    tokens = []
    for parrafo in re.split(r'\n\s*\n', corregido.strip()):
        if tokens:
            tokens.append('\u00b6')
        tokens += parrafo.split()
    clave = lambda t: re.sub(r'[^\wáéíóúüñ]', '', t.lower())
    emparejador = difflib.SequenceMatcher(None, [clave(w) for w in palabras_borrador], [clave(t) for t in tokens], autojunk=False)
    salida, injertos = [], 0
    for operacion, i1, i2, j1, j2 in emparejador.get_opcodes():
        bloque = tokens[j1:j2]
        if operacion == 'equal' or not any(marca.search(t) for t in bloque):
            salida += bloque
            continue
        # el agente marcó ilegible aquí: entra lo que el OCR leyó en ese tramo
        sustitutos = palabras_borrador[i1:i2]
        intactos = [t for t in bloque if not marca.search(t) and t != '\u00b6']
        salida += sustitutos if sustitutos else intactos
        if '\u00b6' in bloque:
            salida.append('\u00b6')
        injertos += 1
    texto = ' '.join(salida).replace(' \u00b6 ', '\n\n').replace('\u00b6', '\n\n')
    return re.sub(r'[ \t]+', ' ', texto).strip(), injertos


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
    return ruta.suffix == '.txt' and not ruta.name.endswith('.cambios.txt') and not ruta.name.startswith('.')


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
        imagen = None
        if args.carpeta_img and agentes.es_agente(modelo):
            candidata = Path(args.carpeta_img) / f'{archivo.stem}.png'
            imagen = candidata if candidata.exists() else None
        for i, trozo in enumerate(trozos, 1):
            corregido = corregir_trozo(trozo, imagen=imagen)
            # una página declarada ilegible entera se vuelve a pedir; si el agente
            # insiste, se conserva el borrador, que leía la página
            injertos = 0
            if imagen is not None:
                excesivo, marcas, dudosos = ilegibles_excesivos(archivo, trozo, corregido)
                if excesivo:
                    print(f'  trozo {i}/{len(trozos)}: {marcas} [ilegible] con {dudosos} renglones dudosos en el OCR; se repite la lectura', flush=True)
                    segunda = corregir_trozo(trozo, imagen=imagen)
                    excesivo, marcas, _ = ilegibles_excesivos(archivo, trozo, segunda)
                    corregido = segunda
                    if excesivo:
                        # el agente insiste: se conservan sus correcciones y párrafos, y solo
                        # los tramos que marcó ilegible se rellenan con el borrador del OCR
                        corregido, injertos = injertar_borrador(trozo, segunda)
                        restantes = len(re.findall(r'\[ilegible\]', corregido, re.I))
                        print(f'  trozo {i}/{len(trozos)}: {marcas} [ilegible] también en la segunda lectura; '
                              f'se injerta el borrador en {injertos} tramo(s), quedan {restantes}', flush=True)
            valido, motivo = validar(trozo, corregido)
            if valido and injertos:
                motivo += f'; {injertos} tramo(s) ilegibles rellenados con el OCR'
            # con la imagen delante y un OCR casi vacío (una portadilla, un título, una
            # página que el OCR apenas leyó) el agente devuelve más texto del que había,
            # y eso es lo que se busca: el guardarraíl de longitud no aplica
            if imagen is not None and not valido and len(trozo) < 400 and corregido.strip() and motivo.startswith('longitud'):
                valido, motivo = True, f'{motivo}; se acepta porque el OCR era corto y el agente leyó la imagen'
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
