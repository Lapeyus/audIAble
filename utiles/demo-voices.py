# Importing required libraries
import re
import sys
import json
import wave
import asyncio
import argparse
import subprocess
import tempfile
from pathlib import Path

# La raíz del repositorio queda un nivel por encima de esta carpeta
RAIZ = Path(__file__).resolve().parent.parent

# Load JSON configurations
with open(RAIZ / 'config.json') as f:
    config = json.load(f)

# Sample sentence per language, so every voice is demoed in its own language
TEXTOS = {
    'es': 'Esta es una muestra de mi voz leyendo un libro en voz alta.',
    'en': 'This is a sample of my voice reading a book out loud.',
    'fr': 'Voici un exemple de ma voix lisant un livre à voix haute.',
    'it': 'Questo è un esempio della mia voce mentre leggo un libro.',
    'pt': 'Esta é uma amostra da minha voz lendo um livro em voz alta.',
    'de': 'Dies ist eine Probe meiner Stimme beim Vorlesen eines Buches.'
}

# Command line arguments setup
parser = argparse.ArgumentParser(description='Generate a demo audio of the available voices so you can pick one.')
parser.add_argument('--e', dest='engine', required=True, choices=['edge', 'mac'], help='Speech engine to demo.')
parser.add_argument('--l', dest='locales', help='Comma separated locales to include, e.g. es-MX,es-ES,en-US. All of them if omitted.')
parser.add_argument('--o', dest='folder_output', default='demos', help='Folder to save the demo audio files. Defaults to ./demos')
parser.add_argument('--t', dest='text', help='Sample sentence to read, overriding the built-in one for each language.')
parser.add_argument('--nojoin', dest='nojoin', action='store_true', help='Only write one file per voice, skipping the single joined demo.')
args = parser.parse_args()

# Locale filters are normalized so es-MX and es_MX both work for either engine
filtros = [f.strip().replace('_', '-').lower() for f in args.locales.split(',')] if args.locales else []

def locale_coincide(locale):
    normalizado = locale.replace('_', '-').lower()
    return not filtros or any(normalizado.startswith(filtro) for filtro in filtros)

# Function to build the sentence a voice reads: its own name and then the sample
def texto_muestra(nombre_hablado, locale):
    texto = args.text or TEXTOS.get(locale.replace('_', '-').split('-')[0], TEXTOS['en'])
    return f'{nombre_hablado}. {texto}'

# Function to turn a voice name into a safe file name
def nombre_archivo(nombre):
    return re.sub(r'[^\w\-]+', '_', nombre).strip('_')

# Function to list the Edge TTS voices as (id, spoken name, locale) tuples
def voces_edge():
    import edge_tts
    voces = asyncio.run(edge_tts.list_voices())
    seleccionadas = []
    for voz in sorted(voces, key=lambda v: (v['Locale'], v['ShortName'])):
        if not locale_coincide(voz['Locale']):
            continue
        # en-US-AriaNeural -> Aria
        nombre = voz['ShortName'].split('-')[-1].replace('Neural', '').replace('Multilingual', ' multilingual')
        seleccionadas.append((voz['ShortName'], nombre, voz['Locale']))
    return seleccionadas

# Function to list the macOS voices as (id, spoken name, locale) tuples
def voces_mac():
    salida = subprocess.run(['say', '-v', '?'], capture_output=True, text=True, check=True).stdout
    seleccionadas = []
    for linea in salida.splitlines():
        # The name can carry its own spaces, the locale is the token right before the comment
        coincidencia = re.match(r'^(.+?)\s+([a-z]{2,3}[_-][A-Z]{2,3})\s+#', linea)
        if not coincidencia:
            continue
        nombre, locale = coincidencia.group(1).strip(), coincidencia.group(2)
        if locale_coincide(locale):
            seleccionadas.append((nombre, nombre, locale))
    return sorted(seleccionadas, key=lambda v: (v[2], v[0]))

# Function to synthesize one sample with Edge TTS
def generar_edge(voz_id, texto, ruta_audio):
    import edge_tts
    settings = config['EdgeTTS']
    comunicacion = edge_tts.Communicate(texto, voz_id, rate=settings['rate'], volume=settings['volume'], pitch=settings['pitch'])
    asyncio.run(comunicacion.save(str(ruta_audio)))

# Function to synthesize one sample with the macOS "say" command
def generar_mac(voz_id, texto, ruta_audio):
    settings = config['MacTTS']
    with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False) as archivo_temporal:
        archivo_temporal.write(texto)
        ruta_texto = Path(archivo_temporal.name)
    try:
        comando = ['say', '-v', voz_id, '-f', str(ruta_texto), '-o', str(ruta_audio)]
        if settings['data_format']:
            comando += [f'--data-format={settings["data_format"]}']
        subprocess.run(comando, check=True)
    finally:
        ruta_texto.unlink(missing_ok=True)

# Function to join WAV samples into a single file, with a short silence between voices
def unir_wav(rutas, ruta_destino):
    with wave.open(str(rutas[0]), 'rb') as primera:
        parametros = primera.getparams()
    silencio = b'\x00' * (parametros.nchannels * parametros.sampwidth * int(parametros.framerate * 0.6))
    with wave.open(str(ruta_destino), 'wb') as destino:
        destino.setparams(parametros)
        for ruta in rutas:
            with wave.open(str(ruta), 'rb') as origen:
                if origen.getparams()[:3] != parametros[:3]:
                    print(f'  skipped in the joined file, different audio format: {ruta.name}')
                    continue
                destino.writeframes(origen.readframes(origen.getnframes()))
            destino.writeframes(silencio)

# Function to join MP3 samples into a single file. Edge TTS returns the same
# codec and sample rate for every voice, so the frames can simply be appended
def unir_mp3(rutas, ruta_destino):
    with open(ruta_destino, 'wb') as destino:
        for ruta in rutas:
            destino.write(ruta.read_bytes())

# Function to generate one sample per voice and the joined demo
def generar_demo():
    if args.engine == 'mac' and sys.platform != 'darwin':
        sys.exit('The mac engine relies on the macOS "say" command and only runs on macOS.')
    if args.engine == 'edge':
        try:
            import edge_tts  # noqa: F401
        except ImportError:
            sys.exit('The edge-tts package is required. Install it with: pip install edge-tts')

    voces = voces_edge() if args.engine == 'edge' else voces_mac()
    if not voces:
        sys.exit(f'No {args.engine} voices matched {args.locales}. Run pro-{args.engine}-tts.py --voices to see them all.')

    extension = config['EdgeTTS']['audio_format'] if args.engine == 'edge' else config['MacTTS']['audio_format']
    folder_output = Path(args.folder_output) / args.engine
    folder_output.mkdir(parents=True, exist_ok=True)

    print(f'Generating {len(voces)} {args.engine} voice samples in {folder_output}')
    rutas = []
    for voz_id, nombre, locale in voces:
        ruta_audio = folder_output / f'{nombre_archivo(voz_id)}.{extension}'
        if not ruta_audio.exists():
            texto = texto_muestra(nombre, locale)
            if args.engine == 'edge':
                generar_edge(voz_id, texto, ruta_audio)
            else:
                generar_mac(voz_id, texto, ruta_audio)
        rutas.append(ruta_audio)
        print(f'  {locale:<8} {voz_id}')

    if not args.nojoin:
        ruta_demo = Path(args.folder_output) / f'demo_{args.engine}.{extension}'
        unir_wav(rutas, ruta_demo) if extension == 'wav' else unir_mp3(rutas, ruta_demo)
        print(f'Joined demo of all the voices above: {ruta_demo}')

# Run the function to generate the demo
generar_demo()
