# Importing required libraries
import re
import sys
import json
import signal
import argparse
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

# La raíz del repositorio queda un nivel por encima de esta carpeta
RAIZ = Path(__file__).resolve().parent.parent

# Load JSON configurations
with open(RAIZ / 'config.json') as f:
    config = json.load(f)

# Command line arguments setup
parser = argparse.ArgumentParser(description='Generate audios from text files using the local macOS speech engine (offline, free).')
parser.add_argument('--f', dest='folder_input', help='Folder containing text files to process.')
parser.add_argument('--o', dest='folder_output', help='Folder to save generated audio files.')
parser.add_argument('--v', dest='voice', help='Voice to use, overrides the one in config.json. Omitted by default so the system voice is used.')
parser.add_argument('--dryrun', dest='dryrun', action='store_true', help='List the audio parts that would be generated without running the speech engine.')
parser.add_argument('--voices', dest='list_voices', action='store_true', help='List the voices installed in the system and exit.')
parser.add_argument('--vsiri', dest='voz_siri', help='Voice id of a Siri voice, for example com.apple.siri.natural.Simone. It is set as the system voice for the run and restored afterwards, which is the only way to reach a Siri voice from say.')
parser.add_argument('--vsiri-idioma', dest='vsiri_idioma', help='Language the Siri voice is bound to. Keeps the one already configured, or en, when omitted.')
args = parser.parse_args()

# macOS settings, with the command line voice taking precedence over config.json
settings = config['MacTTS']
voice = args.voice or settings['voice']

# The system voice lives in this preference, as an array that alternates the
# language and a typed dictionary
DOMINIO_VOZ = 'com.apple.Accessibility'
CLAVE_VOZ = 'SpokenContentDefaultVoiceSelectionsByLanguage'

if args.voz_siri and args.voice:
    parser.error('--vsiri y --v son incompatibles: la voz de Siri se usa llamando a say sin voz.')

if sys.platform != 'darwin':
    sys.exit('This script relies on the macOS "say" command and only runs on macOS.')

if args.list_voices:
    subprocess.run(['say', '-v', '?'])
    sys.exit(0)

if not args.folder_input or not args.folder_output:
    parser.error('--f and --o are required unless --voices is used.')

# File directories
folder_input = Path(args.folder_input)
folder_output = Path(args.folder_output)

# Create output folder if it does not exist
folder_output.mkdir(parents=True, exist_ok=True)

# Function to read the system voice preference as defaults prints it
def leer_preferencia():
    resultado = subprocess.run(['defaults', 'read', DOMINIO_VOZ, CLAVE_VOZ], capture_output=True, text=True)
    return resultado.stdout.strip() if resultado.returncode == 0 else None


# Function to pull the voice id out of that preference
def voz_configurada(preferencia):
    coincidencia = re.search(r'voiceId\s*=\s*"?([^";\n]+)"?', preferencia or '')
    return coincidencia.group(1).strip() if coincidencia else None


# Function to pull the language the voice is bound to
def idioma_configurado(preferencia):
    coincidencia = re.search(r'boundLanguage\s*=\s*"?([^";\n]+)"?', preferencia or '')
    return coincidencia.group(1).strip() if coincidencia else None


# Function to build the preference in the old style plist syntax defaults takes
def construir_preferencia(voz_id, idioma):
    return (f'("{idioma}", {{"_type" = "Speech.VoiceSelection"; "_version" = 0; '
            f'"boundLanguage" = "{idioma}"; "voiceId" = "{voz_id}"; }})')


# Function to leave the preference exactly as it was found, deleting it when it
# did not exist before
def restaurar_preferencia(anterior):
    if anterior is None:
        subprocess.run(['defaults', 'delete', DOMINIO_VOZ, CLAVE_VOZ], capture_output=True)
    else:
        subprocess.run(['defaults', 'write', DOMINIO_VOZ, CLAVE_VOZ, anterior], capture_output=True)
    subprocess.run(['killall', 'cfprefsd'], capture_output=True)


# Context manager that borrows the system voice for the length of the run. It is
# the only route to a Siri voice, because say -v cannot open them, and it is a
# system wide change: while this runs, everything that speaks uses this voice
@contextmanager
def voz_de_sistema_prestada(voz_id, idioma_pedido):
    anterior = leer_preferencia()
    idioma = idioma_pedido or idioma_configurado(anterior) or 'en'
    previa = voz_configurada(anterior)
    print(f'Voz del sistema actual: {previa or "sin configurar"}')
    print(f'Se cambia temporalmente a {voz_id} ({idioma}). Afecta a todo el sistema mientras dure.')

    # SIGTERM debe pasar por el finally, o la voz del sistema se quedaría cambiada
    def al_terminar(numero, marco):
        raise SystemExit(f'interrumpido por la señal {numero}')
    anterior_sigterm = signal.signal(signal.SIGTERM, al_terminar)

    try:
        subprocess.run(['defaults', 'write', DOMINIO_VOZ, CLAVE_VOZ,
                        construir_preferencia(voz_id, idioma)], check=True)
        subprocess.run(['killall', 'cfprefsd'], capture_output=True)
        if voz_configurada(leer_preferencia()) != voz_id:
            raise SystemExit('El cambio no se aplicó: la preferencia siguió igual al releerla. '
                             'Suele ser TCC: da Acceso Total al Disco a tu terminal y repite.')
        yield
    finally:
        signal.signal(signal.SIGTERM, anterior_sigterm)
        restaurar_preferencia(anterior)
        recuperada = voz_configurada(leer_preferencia())
        if recuperada == previa:
            print(f'Voz del sistema restaurada a {previa or "sin configurar"}')
        else:
            print(f'ATENCIÓN: no se pudo restaurar la voz del sistema (quedó {recuperada}). '
                  f'Arréglalo en Ajustes del Sistema o con:\n'
                  f'  defaults write {DOMINIO_VOZ} {CLAVE_VOZ} \'{anterior}\'', file=sys.stderr)


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

# Function to synthesize a single part with the "say" command. The text is passed
# through a temporary file and the audio is written to a temporary name, so no
# truncated audio survives an interrupted run
def sintetizar_parte(parte_texto, ruta_audio):
    ruta_parcial = ruta_audio.with_name(f'{ruta_audio.stem}.part{ruta_audio.suffix}')
    with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False) as archivo_temporal:
        archivo_temporal.write(parte_texto)
        ruta_texto = Path(archivo_temporal.name)

    comando = ['say', '-f', str(ruta_texto), '-o', str(ruta_parcial)]
    if voice:
        comando += ['-v', voice]
    if settings['rate']:
        comando += ['-r', str(settings['rate'])]
    if settings['data_format']:
        comando += [f'--data-format={settings["data_format"]}']

    try:
        subprocess.run(comando, check=True)
        ruta_parcial.rename(ruta_audio)
    except Exception:
        ruta_parcial.unlink(missing_ok=True)
        raise
    finally:
        ruta_texto.unlink(missing_ok=True)

# Function to generate audio from a text file
def generar_txt_audio(archivo_stem, archivo, folder_output, dryrun=False):
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

        sintetizar_parte(parte_texto, ruta_audio)
        print(f'{ruta_audio} ({len(parte_texto)} characters)')

    return total_caracteres

# Function to generate audio from all text files in the input folder
def generar_audio():
    archivos_a_procesar = {archivo.stem: archivo for archivo in sorted(folder_input.iterdir()) if es_pagina(archivo)}
    grand_total_caracteres = 0
    for archivo_stem, archivo in archivos_a_procesar.items():
        total_caracteres = generar_txt_audio(archivo_stem, archivo, folder_output, args.dryrun)
        grand_total_caracteres += total_caracteres
        if args.dryrun:
            print(f'Pending characters for {archivo_stem}: {total_caracteres}')

    print(f'Total characters {"to synthesize" if args.dryrun else "synthesized"} with {voice or "the system voice"}: {grand_total_caracteres} (cost: $0.00)')

# Run the function to generate audio
if args.voz_siri:
    with voz_de_sistema_prestada(args.voz_siri, args.vsiri_idioma):
        generar_audio()
else:
    generar_audio()
