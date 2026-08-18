# Importing required libraries
import re
import sys
import json
import argparse
import urllib.request
from pathlib import Path

# La raíz del repositorio queda un nivel por encima de esta carpeta
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from nucleo import gemini, ollama_local


# Load JSON configurations
with open(RAIZ / 'config.json') as f:
    config = json.load(f)

settings = config['OllamaCleanup']

# A heading is usually short, isolated and starts with a chapter word or a
# number. The regex proposes the candidates and the model confirms them
PATRON_TITULO = re.compile(
    r'^\s*((cap[íi]tulo|parte|libro|secci[óo]n|chapter|part)\s+[\w¡!¿?.,:;\-]{1,40}|[IVXLC]{1,6}|\d{1,3})\s*$',
    re.IGNORECASE | re.MULTILINE
)

INSTRUCCIONES = """Este es el comienzo de una página de un libro. Decide si en ella empieza un capítulo o una sección nueva.

Responde SOLO con un JSON de esta forma, sin explicaciones:
{"nuevo": true/false, "titulo": "título corto o cadena vacía"}

TEXTO:
"""

# Command line arguments setup
parser = argparse.ArgumentParser(description='Find the chapter and section boundaries of a book, to split the audio into logical parts.')
parser.add_argument('--f', dest='folder_input', required=True, help='Folder with the text files, one per page, in order.')
parser.add_argument('--o', dest='salida', help='JSON file to write. Defaults to divisiones.json inside the input folder.')
parser.add_argument('--m', dest='model', help='Ollama model, overrides the one in config.json.')
parser.add_argument('--sinllm', dest='sinllm', action='store_true', help='Use only the deterministic heading rules, without asking the model.')
args = parser.parse_args()

modelo = args.model or settings['model']

if not args.sinllm and gemini.es_modelo_google(modelo):
    pass
elif not args.sinllm:
    try:
        modelo, autodetectado = ollama_local.elegir_modelo(settings['host'], modelo, 'texto')
        if autodetectado:
            print(f'El modelo pedido no está instalado, se usa {modelo}', flush=True)
    except Exception as error:
        print(f'No se pudo consultar Ollama ({error}), se seguirá solo con las reglas', flush=True)
        args.sinllm = True

# Function to ask the model whether a page opens a new division
def preguntar_al_modelo(texto):
    if gemini.es_modelo_google(modelo):
        salida = gemini.generar(modelo, INSTRUCCIONES + texto[:700], json_output=True)
        try:
            datos = json.loads(salida)
            return bool(datos.get('nuevo')), str(datos.get('titulo') or '').strip()
        except json.JSONDecodeError:
            return False, ''
    cuerpo = json.dumps({
        'model': modelo,
        'prompt': INSTRUCCIONES + texto[:700],
        'stream': False,
        'think': False,
        'format': 'json',
        'options': {'temperature': 0}
    }).encode()
    peticion = urllib.request.Request(f"{settings['host']}/api/generate", cuerpo, {'Content-Type': 'application/json'})
    with urllib.request.urlopen(peticion, timeout=settings['timeout']) as respuesta:
        salida = json.loads(respuesta.read())['response']
    try:
        datos = json.loads(salida)
        return bool(datos.get('nuevo')), str(datos.get('titulo') or '').strip()
    except json.JSONDecodeError:
        return False, ''

# Function to tell a page of the book from a report written by pre-ollama.py,
# which lives alongside the pages and must never be read out loud
def es_pagina(ruta):
    return ruta.suffix == '.txt' and not ruta.name.endswith('.cambios.txt')


# Function to sort the pages by their number instead of alphabetically
def orden_natural(ruta):
    numeros = re.findall(r'\d+', ruta.stem)
    return (int(numeros[-1]) if numeros else 0, ruta.stem)

# Function to group the pages into chapters and sections
def detectar_divisiones():
    folder_input = Path(args.folder_input)
    archivos = sorted((a for a in folder_input.iterdir() if es_pagina(a)), key=orden_natural)
    if not archivos:
        sys.exit(f'No hay archivos .txt en {folder_input}')

    divisiones = []
    for indice, archivo in enumerate(archivos):
        texto = archivo.read_text(encoding='utf-8')
        candidato = bool(PATRON_TITULO.search(texto[:400])) or indice == 0
        nuevo, titulo = (candidato, '') if args.sinllm else (False, '')

        if candidato and not args.sinllm:
            try:
                nuevo, titulo = preguntar_al_modelo(texto)
            except Exception as error:
                print(f'  {archivo.name}: no se pudo consultar al modelo ({error}), se usa la regla', flush=True)
                nuevo = candidato

        if nuevo or not divisiones:
            titulo = titulo or f'Parte {len(divisiones) + 1}'
            divisiones.append({'titulo': titulo, 'archivos': []})
            print(f'  {archivo.name}: empieza "{titulo}"', flush=True)
        divisiones[-1]['archivos'].append(archivo.name)

    destino = Path(args.salida) if args.salida else folder_input / 'divisiones.json'
    destino.write_text(json.dumps(divisiones, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'{len(divisiones)} división(es) sobre {len(archivos)} páginas -> {destino}', flush=True)
    return divisiones

detectar_divisiones()
