# Importing required libraries
import re
import os
import sys
import json
import argparse
from pathlib import Path
from google.cloud import texttospeech

# La raíz del repositorio queda un nivel por encima de esta carpeta
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from nucleo import gcp

# Load JSON configurations
with open(RAIZ / 'config.json') as f:
    config = json.load(f)

# Command line arguments setup
parser = argparse.ArgumentParser(description='Generate audios from text files.')
parser.add_argument('--f', dest='folder_input', required=True, help='Folder containing text files to process.')
parser.add_argument('--o', dest='folder_output', required=True, help='Folder to save generated audio files.')
parser.add_argument('--dryrun', dest='dryrun', action='store_true', help='Estimate cost without making API calls.')
parser.add_argument('--cred', dest='cred', help='Path to a Google service account JSON key. Skipped when ADC or credentials.json already provide access.')
args = parser.parse_args()

# Initialize Text-to-Speech client. A dry run needs no credentials at all, so
# both the resolution and the client are skipped in that case
client_tts = None
if not '--help' in sys.argv and not (hasattr(args, 'dryrun') and args.dryrun):
    print(f'Credenciales de Google: {gcp.preparar_credenciales(args.cred)}', flush=True)
    client_tts = texttospeech.TextToSpeechClient()

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

# Function to generate audio from a text file
def generar_txt_audio(archivo_stem, archivo, config, folder_output, dryrun=False):
    total_cost = 0
    for i, parte_texto in enumerate(dividir_texto(open(archivo, 'r').read())):
        ruta_audio = folder_output / f'{archivo_stem}_{i}.wav'
        if ruta_audio.exists():
            continue

        voice_type = config['TextToSpeechAPI']['voice']['text'].split('-')[2]
        pricing = next((v for k, v in config['TextToSpeechAPI']['Pricing'].items() if k.lower() == voice_type.lower()), 0)

        if dryrun:
            cost = len(parte_texto.encode('utf-8')) * pricing
            total_cost += cost
            continue

        input_text = texttospeech.SynthesisInput(text=parte_texto)
        voz = texttospeech.VoiceSelectionParams(
            language_code=config['TextToSpeechAPI']['voice']['language_code'],
            name=config['TextToSpeechAPI']['voice']['text']
        )
        configuracion_audio = texttospeech.AudioConfig(
            audio_encoding=config['TextToSpeechAPI']['audio_config']['audio_encoding'],
            effects_profile_id=config['TextToSpeechAPI']['audio_config']['effects_profile_id'],
            pitch=config['TextToSpeechAPI']['audio_config']['pitch'],
            speaking_rate=config['TextToSpeechAPI']['audio_config']['speaking_rate']
        )

        respuesta_tts = client_tts.synthesize_speech(input=input_text, voice=voz, audio_config=configuracion_audio)
        with open(ruta_audio, 'wb') as archivo_audio:
            archivo_audio.write(respuesta_tts.audio_content)

    if dryrun:
        print(f'Total estimated cost for {archivo_stem}: ${total_cost:.8f}')
    return total_cost  # Return the total cost

# Function to generate audio from all text files in the input folder
def generar_audio():
    archivos_a_procesar = {archivo.stem: archivo for archivo in sorted(folder_input.iterdir()) if es_pagina(archivo)}
    grand_total_cost = 0
    for archivo_stem, archivo in archivos_a_procesar.items():
        total_cost = generar_txt_audio(archivo_stem, archivo, config, folder_output, args.dryrun)
        grand_total_cost += total_cost if total_cost else 0

    if args.dryrun:
        print(f'Total estimated cost for all pages: ${grand_total_cost:.8f}')

# Run the function to generate audio
generar_audio()
