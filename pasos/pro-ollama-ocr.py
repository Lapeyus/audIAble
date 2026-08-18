# Importing required libraries
import re
import sys
import json
import time
import base64
import argparse
import urllib.request
from pathlib import Path
from collections import Counter

# La raíz del repositorio queda un nivel por encima de esta carpeta
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from nucleo.limpieza import colapsar_repeticiones

from nucleo import ollama_local


# Load JSON configurations
with open(RAIZ / 'config.json') as f:
    config = json.load(f)

settings = config['OllamaOCR']

# Command line arguments setup
parser = argparse.ArgumentParser(description='Read the text of page images with a local Ollama vision model.')
parser.add_argument('--f', dest='folder_input', help='Folder containing the page images.')
parser.add_argument('--o', dest='folder_output', help='Folder to save the extracted text files.')
parser.add_argument('--m', dest='model', help='Ollama vision model, overrides the one in config.json.')
parser.add_argument('--check', dest='check', action='store_true', help='Check that the server answers and the model is installed, then exit.')
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
    try:
        disponibles = ollama_local.modelos_para(settings['host'], 'ocr')
    except Exception as error:
        sys.exit(f"No responde Ollama en {settings['host']}: {error}\nArráncalo con: ollama serve")
    try:
        modelo, autodetectado = ollama_local.elegir_modelo(settings['host'], modelo, 'ocr')
    except RuntimeError as error:
        sys.exit(str(error))
    if autodetectado:
        print(f'El modelo pedido no está instalado, se usa {modelo} (detectado entre: {", ".join(disponibles)})', flush=True)
    return disponibles

# Function to strip the wrappers a vision model likes to add around the page
def limpiar_respuesta(respuesta):
    respuesta = re.sub(r'^```[a-z]*\n|\n```$', '', respuesta.strip())
    respuesta = re.sub(r'</?\|?[a-z_]+\|?>', '', respuesta)
    lineas = respuesta.split('\n')
    if lineas and len(lineas[0]) < 80 and lineas[0].rstrip().endswith(':'):
        respuesta = '\n'.join(lineas[1:])
    return respuesta.strip()

# Function to spot a vision model that has fallen into a loop or started
# talking to itself. A real page uses many different words; a degenerate answer
# repeats a handful, and read out loud it becomes minutes of the same word
def parece_degenerado(texto):
    palabras = re.findall(r"[0-9a-záéíóúüñç']+", texto.lower())
    if len(palabras) < 40:
        return False
    diversidad = len(set(palabras)) / len(palabras)
    frecuencia_maxima = max(Counter(palabras).values()) / len(palabras)
    if diversidad < 0.25 or frecuencia_maxima > 0.3:
        return True
    # una frase larga repetida literalmente en la misma página casi nunca es del
    # libro: es el modelo repitiéndose o comentando lo que acaba de leer
    largas = [f.strip() for f in re.split(r'(?<=[.!?…])\s+', texto) if len(f.strip()) > 60]
    return any(veces > 1 for veces in Counter(largas).values())


# Function to read one page image
def leer_imagen(ruta_imagen, reintentos=2):
    imagen = base64.b64encode(ruta_imagen.read_bytes()).decode()
    for intento in range(1, reintentos + 1):
        try:
            respuesta = pedir_a_ollama('/api/generate', {
                'model': modelo,
                'prompt': settings['prompt'],
                'images': [imagen],
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

# Function to process every image in the input folder
def procesar_imagenes():
    folder_input = Path(args.folder_input)
    folder_output = Path(args.folder_output)
    folder_output.mkdir(parents=True, exist_ok=True)

    imagenes = sorted(i for i in folder_input.iterdir() if i.suffix.lower() in ('.png', '.jpg', '.jpeg'))
    degeneradas = []
    for imagen in imagenes:
        ruta_texto = folder_output / f'{imagen.stem}.txt'
        if ruta_texto.exists():
            continue
        inicio = time.time()
        texto = leer_imagen(imagen)
        crudo = len(texto)
        texto = colapsar_repeticiones(texto)
        ruta_texto.write_text(texto, encoding='utf-8')
        aviso = ''
        if crudo != len(texto):
            aviso = f' [se colapsó una repetición: {crudo} -> {len(texto)}]'
        if parece_degenerado(texto):
            aviso += ' [AVISO: la respuesta parece degenerada, revisa esta página o cambia de modelo]'
            degeneradas.append(imagen.name)
        print(f'{ruta_texto} ({len(texto)} caracteres, {time.time() - inicio:.0f}s){aviso}', flush=True)

    print(f'{len(imagenes)} imágenes procesadas con {modelo}', flush=True)
    if degeneradas:
        print(f'ATENCIÓN: {len(degeneradas)} página(s) con salida degenerada ({", ".join(degeneradas[:5])}). '
              f'Este modelo no está leyendo bien: prueba otro, o extrae el texto sin OCR si el PDF ya trae capa de texto.', flush=True)

if args.check:
    instalados = comprobar_servidor()
    print(f"Ollama responde en {settings['host']}, se usará el modelo {modelo}.")
    sys.exit(0)

if not args.folder_input or not args.folder_output:
    parser.error('--f y --o son obligatorios salvo con --check.')

comprobar_servidor()
procesar_imagenes()
