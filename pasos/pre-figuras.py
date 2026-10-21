# Importing required libraries
import io
import re
import sys
import json
import time
import base64
import argparse
import urllib.request
from pathlib import Path

import fitz

# La raíz del repositorio queda un nivel por encima de esta carpeta
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from nucleo import gemini, ollama_local
from nucleo.limpieza import colapsar_repeticiones

# Load JSON configurations
with open(RAIZ / 'config.json') as f:
    config = json.load(f)

settings = config['Figuras']

# Everything the listener hears must be in the language of the book: the
# connector phrases, the fallbacks, and the language the models answer in
IDIOMAS = {
    'es': {'nombre': 'español',
           'tabla': 'A continuación hay una tabla.', 'imagen': 'A continuación hay una imagen.',
           'sin_imagen': 'Aquí aparece una imagen que no se pudo describir.',
           'sin_tabla': 'una tabla de {filas} filas por {columnas} columnas que no se pudo describir'},
    'en': {'nombre': 'English',
           'tabla': 'There is a table here.', 'imagen': 'There is an image here.',
           'sin_imagen': 'There is an image here that could not be described.',
           'sin_tabla': 'a table of {filas} rows by {columnas} columns that could not be described'},
    'fr': {'nombre': 'français',
           'tabla': 'Voici un tableau.', 'imagen': 'Voici une image.',
           'sin_imagen': "Il y a ici une image qui n'a pas pu être décrite.",
           'sin_tabla': "un tableau de {filas} lignes sur {columnas} colonnes qui n'a pas pu être décrit"},
    'it': {'nombre': 'italiano',
           'tabla': 'Qui c\'è una tabella.', 'imagen': 'Qui c\'è un\'immagine.',
           'sin_imagen': 'Qui appare un\'immagine che non è stato possibile descrivere.',
           'sin_tabla': 'una tabella di {filas} righe per {columnas} colonne che non è stato possibile descrivere'},
    'pt': {'nombre': 'português',
           'tabla': 'A seguir há uma tabela.', 'imagen': 'A seguir há uma imagem.',
           'sin_imagen': 'Aqui aparece uma imagem que não pôde ser descrita.',
           'sin_tabla': 'uma tabela de {filas} linhas por {columnas} colunas que não pôde ser descrita'},
    'de': {'nombre': 'Deutsch',
           'tabla': 'Hier folgt eine Tabelle.', 'imagen': 'Hier folgt ein Bild.',
           'sin_imagen': 'Hier erscheint ein Bild, das nicht beschrieben werden konnte.',
           'sin_tabla': 'eine Tabelle mit {filas} Zeilen und {columnas} Spalten, die nicht beschrieben werden konnte'}
}

# Command line arguments setup
parser = argparse.ArgumentParser(
    description='Extract the text of a PDF replacing its images and tables with spoken descriptions, so the audiobook keeps making sense without them.')
parser.add_argument('--f', dest='pdf', help='PDF file with a text layer.')
parser.add_argument('--img', dest='folder_img', help='Folder of scanned page images: instead of walking a text layer, each page image is inspected and the descriptions are appended to its text file in --o. For books that went through OCR.')
parser.add_argument('--o', dest='folder_output', required=True, help='Folder to write one enriched text file per page.')
parser.add_argument('--p', dest='paginas', help='Pages to process (1, 1-5, 2,7,9). All of them if omitted.')
parser.add_argument('--mv', dest='modelo_vision', help='Vision model for the images, overrides config.json.')
parser.add_argument('--mt', dest='modelo_texto', help='Text model for the tables, overrides config.json.')
parser.add_argument('--idioma', dest='idioma', default='es', choices=sorted(IDIOMAS),
                    help='Language of the book: the descriptions and connector phrases come out in it.')
args = parser.parse_args()

host = config['OllamaCleanup']['host']
pedido_vision = args.modelo_vision or settings['model_vision']
pedido_texto = args.modelo_texto or config['OllamaCleanup']['model']

if gemini.es_modelo_google(pedido_vision):
    modelo_vision = pedido_vision
else:
    modelo_vision, _ = ollama_local.elegir_modelo(host, pedido_vision, 'figuras')

if gemini.es_modelo_google(pedido_texto):
    modelo_texto = pedido_texto
else:
    modelo_texto, _ = ollama_local.elegir_modelo(host, pedido_texto, 'texto')
textos = IDIOMAS[args.idioma]
print(f'Modelos: visión={modelo_vision}, tablas={modelo_texto} | idioma: {textos["nombre"]}', flush=True)


# Function to call the Ollama API once
def pedir(prompt, imagen_b64=None, modelo=None):
    if gemini.es_modelo_google(modelo):
        datos = base64.b64decode(imagen_b64) if imagen_b64 else None
        return gemini.generar(modelo, prompt, imagen_png=datos).strip()
    cuerpo = {'model': modelo, 'prompt': prompt, 'stream': False, 'think': False,
              'options': {'temperature': 0}}
    if imagen_b64:
        cuerpo['images'] = [imagen_b64]
    peticion = urllib.request.Request(f'{host}/api/generate', json.dumps(cuerpo).encode(),
                                      {'Content-Type': 'application/json'})
    with urllib.request.urlopen(peticion, timeout=settings['timeout']) as respuesta:
        return json.loads(respuesta.read())['response'].strip()


# Function to keep a description usable for listening: single paragraph, no
# markdown, no runaway repetition, and a sane length
def sanear(texto, maximo=900):
    texto = re.sub(r'[*_#`]+', '', texto)
    texto = re.sub(r'\s+', ' ', texto).strip()
    texto = colapsar_repeticiones(texto)
    return texto[:maximo].rsplit('.', 1)[0] + '.' if len(texto) > maximo else texto


# Function to describe one image for a listener
def describir_imagen(pixmap):
    imagen = base64.b64encode(pixmap.tobytes('png')).decode()
    try:
        crudo = pedir(f'Describe esta imagen en {textos["nombre"]} para un oyente de audiolibro que no '
                      f'puede verla. De dos a cuatro frases, solo lo que se ve, sin especular ni comentar. '
                      f'Responde únicamente en {textos["nombre"]}.',
                      imagen_b64=imagen, modelo=modelo_vision)
        return sanear(crudo) or textos['sin_imagen']
    except Exception as error:
        print(f'    descripción de imagen fallida: {error}', flush=True)
        return textos['sin_imagen']


# Function to describe one table for a listener. The cells go to a text model,
# no vision involved, with a plain fallback that just reads the table shape
def describir_tabla(tabla):
    filas = tabla.extract()
    limpio = [[(celda or '').strip() for celda in fila] for fila in filas]
    try:
        crudo = pedir(f'Convierte esta tabla en una explicación hablada, breve y natural en {textos["nombre"]}, '
                      f'para un audiolibro. Menciona qué compara y los datos importantes. Sin markdown ni listas. '
                      f'Responde únicamente en {textos["nombre"]}.\n\n'
                      + '\n'.join(' | '.join(fila) for fila in limpio),
                      modelo=modelo_texto)
        return sanear(crudo) or None
    except Exception as error:
        print(f'    descripción de tabla fallida: {error}', flush=True)
        return None


# Function to build the reading-order text of one page, swapping each table for
# its description and appending one description per meaningful image
def procesar_pagina(pagina):
    tablas = list(pagina.find_tables())
    zonas_tabla = [fitz.Rect(t.bbox) for t in tablas]
    descritas = [False] * len(tablas)
    area_pagina = abs(pagina.rect)

    partes, imagenes = [], 0
    for bloque in pagina.get_text('dict', sort=True)['blocks']:
        caja = fitz.Rect(bloque['bbox'])
        if bloque['type'] == 0:
            # un bloque dentro de una tabla no se lee como texto suelto: en su
            # lugar entra la descripción de la tabla, una sola vez
            dentro = next((i for i, zona in enumerate(zonas_tabla) if zona.intersects(caja)
                           and abs(zona & caja) > abs(caja) * 0.5), None)
            if dentro is not None:
                if not descritas[dentro]:
                    descritas[dentro] = True
                    filas = tablas[dentro].extract()
                    descripcion = describir_tabla(tablas[dentro])
                    if not descripcion:
                        descripcion = textos['sin_tabla'].format(filas=len(filas), columnas=len(filas[0]) if filas else 0)
                    partes.append(f'{textos["tabla"]} {descripcion}')
                    print(f'    tabla descrita ({len(filas)} filas)', flush=True)
                continue
            texto = ' '.join(span['text'] for linea in bloque['lines'] for span in linea['spans'])
            if texto.strip():
                partes.append(texto.strip())
        elif bloque['type'] == 1:
            # las imágenes minúsculas son adornos; una imagen que ocupa la página
            # entera en una página sin texto es un escaneo, no una figura
            if caja.width < settings['min_lado'] or caja.height < settings['min_lado']:
                continue
            if abs(caja) > area_pagina * 0.85:
                continue
            imagenes += 1
            pixmap = pagina.get_pixmap(clip=caja, dpi=120)
            partes.append(f'{textos["imagen"]} {describir_imagen(pixmap)}')
            print(f'    imagen descrita ({int(caja.width)}x{int(caja.height)} pt)', flush=True)

    return '\n\n'.join(partes), len(tablas), imagenes


# Function to inspect one scanned page and describe the figures it contains,
# or answer NINGUNA when the page is body text only
def describir_figuras_de_pagina(ruta_imagen):
    imagen = base64.b64encode(ruta_imagen.read_bytes()).decode()
    respuesta = pedir(f'Mira esta página escaneada de un libro. Ignora el texto corrido del cuerpo. '
                      f'Si la página contiene figuras, fotografías, ilustraciones, gráficos o tablas, '
                      f'describe cada una en {textos["nombre"]} en dos o tres frases. '
                      f'Responde únicamente en {textos["nombre"]}. '
                      f'Si no hay ninguna, responde exactamente: NINGUNA.',
                      imagen_b64=imagen, modelo=modelo_vision)
    limpio = sanear(respuesta)
    if re.match(r'^\W*NINGUNA\b', limpio, re.IGNORECASE) or not limpio:
        return None
    return limpio


# Function to walk the scanned pages of a book that went through OCR, appending
# the description of each page's figures to the text the OCR produced
def procesar_imagenes():
    folder_img = Path(args.folder_img)
    folder_output = Path(args.folder_output)
    imagenes = sorted((i for i in folder_img.iterdir() if i.suffix.lower() in ('.png', '.jpg', '.jpeg') and not i.name.startswith('.')),
                      key=lambda r: (int(re.findall(r'\d+', r.stem)[-1]) if re.findall(r'\d+', r.stem) else 0, r.stem))
    descritas = 0
    for imagen in imagenes:
        ruta_texto = folder_output / f'{imagen.stem}.txt'
        inicio = time.time()
        try:
            descripcion = describir_figuras_de_pagina(imagen)
        except Exception as error:
            print(f'{imagen.stem}: inspección fallida ({error})', flush=True)
            continue
        if descripcion:
            descritas += 1
            texto_previo = ruta_texto.read_text(encoding='utf-8').rstrip() if ruta_texto.exists() else ''
            ruta_texto.write_text(f'{texto_previo}\n\n{textos["imagen"]} {descripcion}\n', encoding='utf-8')
        print(f'{imagen.stem}: {"figuras descritas" if descripcion else "sin figuras"} ({time.time() - inicio:.0f}s)', flush=True)
    print(f'{len(imagenes)} páginas inspeccionadas, {descritas} con figuras', flush=True)


# Function to parse the pages argument, same syntax as pre-pdf.py
def parsear_paginas(texto, total):
    if not texto:
        return list(range(total))
    indices = []
    for pieza in texto.split(','):
        pieza = pieza.strip()
        if '-' in pieza:
            inicio, fin = (int(x) for x in pieza.split('-', 1))
            indices += list(range(inicio - 1, fin))
        elif pieza:
            indices.append(int(pieza) - 1)
    return [i for i in indices if 0 <= i < total]


# Function to process the requested pages of the book
def procesar_libro():
    documento = fitz.open(args.pdf)
    folder_output = Path(args.folder_output)
    folder_output.mkdir(parents=True, exist_ok=True)

    indices = parsear_paginas(args.paginas, len(documento))
    for indice in indices:
        ruta = folder_output / f'pag_{indice + 1}.txt'
        if ruta.exists():
            continue
        inicio = time.time()
        texto, tablas, imagenes = procesar_pagina(documento[indice])
        ruta.write_text(texto + '\n', encoding='utf-8')
        print(f'{ruta} ({len(texto)} caracteres, {tablas} tabla(s), {imagenes} imagen(es), {time.time() - inicio:.0f}s)', flush=True)

    print(f'{len(indices)} páginas procesadas con descripciones', flush=True)

if args.folder_img:
    procesar_imagenes()
elif args.pdf:
    procesar_libro()
else:
    parser.error('--f (PDF con capa de texto) o --img (carpeta de páginas escaneadas) es obligatorio.')
