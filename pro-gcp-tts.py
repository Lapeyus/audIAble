# Importing required libraries
import os
import json
import argparse
from pathlib import Path
from google.cloud import texttospeech

# Load JSON configurations
with open('config.json') as f:
    config = json.load(f)

# Setting up the Google Cloud Platform credentials
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'credentials.json'

# Command line arguments setup
parser = argparse.ArgumentParser(description='Generate audios from text files.')
parser.add_argument('--f', dest='folder_input', required=True, help='Folder containing text files to process.')
parser.add_argument('--o', dest='folder_output', required=True, help='Folder to save generated audio files.')
parser.add_argument('--dryrun', dest='dryrun', action='store_true', help='Estimate cost without making API calls.')
args = parser.parse_args()

# Initialize Text-to-Speech client
client_tts = texttospeech.TextToSpeechClient()

# File directories
folder_input = Path(args.folder_input)
folder_output = Path(args.folder_output)

# Create output folder if it does not exist
folder_output.mkdir(parents=True, exist_ok=True)

# Function to split text into parts of maximum size max_bytes
def dividir_texto(texto, max_bytes=5000):
    partes_texto = []
    parte = ''
    for palabra in texto.split():
        nueva_parte = f'{parte} {palabra}' if parte else palabra
        if len(nueva_parte.encode('utf-8')) < max_bytes:
            parte = nueva_parte
        else:
            partes_texto.append(parte)
            parte = palabra
    if parte:
        partes_texto.append(parte)
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
    archivos_a_procesar = {archivo.stem: archivo for archivo in folder_input.iterdir() if archivo.suffix == '.txt'}
    grand_total_cost = 0
    for archivo_stem, archivo in archivos_a_procesar.items():
        total_cost = generar_txt_audio(archivo_stem, archivo, config, folder_output, args.dryrun)
        grand_total_cost += total_cost if total_cost else 0

    if args.dryrun:
        print(f'Total estimated cost for all pages: ${grand_total_cost:.8f}')

# Run the function to generate audio
generar_audio()
