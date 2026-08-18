# Importing required libraries
import re
import sys
import json
import asyncio
import argparse
from pathlib import Path

# La raíz del repositorio queda un nivel por encima de esta carpeta
RAIZ = Path(__file__).resolve().parent.parent

try:
    import edge_tts
except ImportError:
    sys.exit('The edge-tts package is required. Install it with: pip install edge-tts')

# Load JSON configurations
with open(RAIZ / 'config.json') as f:
    config = json.load(f)

# Command line arguments setup
parser = argparse.ArgumentParser(description='Generate audios from text files using Microsoft Edge TTS (free, no credentials).')
parser.add_argument('--f', dest='folder_input', help='Folder containing text files to process.')
parser.add_argument('--o', dest='folder_output', help='Folder to save generated audio files.')
parser.add_argument('--v', dest='voice', help='Voice to use, overrides the one in config.json (e.g. es-MX-DaliaNeural).')
parser.add_argument('--dryrun', dest='dryrun', action='store_true', help='List the audio parts that would be generated without calling the service.')
parser.add_argument('--voices', dest='list_voices', action='store_true', help='List the available Edge TTS voices and exit.')
args = parser.parse_args()

# Edge TTS settings, with the command line voice taking precedence over config.json
settings = config['EdgeTTS']
voice = args.voice or settings['voice']

# Function to print the available voices
async def listar_voces():
    for voz in await edge_tts.list_voices():
        print(f"{voz['ShortName']:<32} {voz['Locale']:<8} {voz['Gender']}")

if args.list_voices:
    asyncio.run(listar_voces())
    sys.exit(0)

if not args.folder_input or not args.folder_output:
    parser.error('--f and --o are required unless --voices is used.')

# File directories
folder_input = Path(args.folder_input)
folder_output = Path(args.folder_output)

# Create output folder if it does not exist
folder_output.mkdir(parents=True, exist_ok=True)

# Function to tell a page of the book from a report written by pre-ollama.py,
# which lives alongside the pages and must never be read out loud
def es_pagina(ruta):
    return ruta.suffix == '.txt' and not ruta.name.endswith('.cambios.txt')


# Function to split text into parts of maximum size max_bytes. The cut is taken
# at a paragraph break when possible, then at a sentence end, and only as a last
# resort between words, so no audio file ever starts halfway through a sentence
def dividir_texto(texto, max_bytes=5000):
    def cabe(cadena):
        return len(cadena.encode('utf-8')) < max_bytes

    def trocear(piezas):
        partes, actual = [], ''
        for pieza in piezas:
            candidata = f'{actual} {pieza}'.strip() if actual else pieza
            if cabe(candidata):
                actual = candidata
            else:
                if actual:
                    partes.append(actual)
                actual = pieza
        if actual:
            partes.append(actual)
        return partes

    partes_texto = []
    for parrafo in trocear([p.strip() for p in texto.split('\n\n') if p.strip()]):
        if cabe(parrafo):
            partes_texto.append(parrafo)
            continue
        for frase in trocear(re.split(r'(?<=[.!?…])\s+', parrafo)):
            if cabe(frase):
                partes_texto.append(frase)
            else:
                partes_texto.extend(trocear(frase.split()))
    return partes_texto

# Function to synthesize a single part, writing to a temporary file so an
# interrupted run never leaves a truncated audio behind
async def sintetizar_parte(parte_texto, ruta_audio, reintentos=3):
    ruta_parcial = ruta_audio.with_name(f'{ruta_audio.stem}.part{ruta_audio.suffix}')
    for intento in range(1, reintentos + 1):
        try:
            comunicacion = edge_tts.Communicate(
                parte_texto,
                voice,
                rate=settings['rate'],
                volume=settings['volume'],
                pitch=settings['pitch']
            )
            await comunicacion.save(str(ruta_parcial))
            if ruta_parcial.stat().st_size == 0:
                raise RuntimeError('empty audio received')
            ruta_parcial.rename(ruta_audio)
            return
        except Exception as error:
            ruta_parcial.unlink(missing_ok=True)
            if intento == reintentos:
                raise
            print(f'  retry {intento}/{reintentos - 1} for {ruta_audio.name}: {error}')
            await asyncio.sleep(2 * intento)

# Function to generate audio from a text file
async def generar_txt_audio(archivo_stem, archivo, folder_output, dryrun=False):
    total_caracteres = 0
    with open(archivo, 'r') as archivo_texto:
        partes_texto = dividir_texto(archivo_texto.read(), settings['max_bytes'])

    for i, parte_texto in enumerate(partes_texto):
        ruta_audio = folder_output / f'{archivo_stem}_{i}.{settings["audio_format"]}'
        if ruta_audio.exists() or not parte_texto.strip():
            continue

        total_caracteres += len(parte_texto)

        if dryrun:
            continue

        await sintetizar_parte(parte_texto, ruta_audio)
        print(f'{ruta_audio} ({len(parte_texto)} characters)')

    return total_caracteres

# Function to generate audio from all text files in the input folder
async def generar_audio():
    archivos_a_procesar = {archivo.stem: archivo for archivo in sorted(folder_input.iterdir()) if es_pagina(archivo)}
    grand_total_caracteres = 0
    for archivo_stem, archivo in archivos_a_procesar.items():
        total_caracteres = await generar_txt_audio(archivo_stem, archivo, folder_output, args.dryrun)
        grand_total_caracteres += total_caracteres
        if args.dryrun:
            print(f'Pending characters for {archivo_stem}: {total_caracteres}')

    print(f'Total characters {"to synthesize" if args.dryrun else "synthesized"} with {voice}: {grand_total_caracteres} (cost: $0.00)')

# Run the function to generate audio
asyncio.run(generar_audio())
