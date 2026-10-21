# Importing required libraries
import os
import re
import sys
import json
import time
import shutil
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

# La raíz del repositorio queda un nivel por encima de esta carpeta
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from nucleo.rutas import carpeta_telefono
DESTINO = carpeta_telefono()
CARPETAS_CAMARA = ('/sdcard/DCIM/Camera', '/sdcard/Movies', '/sdcard/DCIM/Restored')
EXTENSIONES = ('.mp4', '.mov', '.m4v', '.mkv', '.webm')

# Command line arguments setup
parser = argparse.ArgumentParser(
    description='Pull the book videos recorded recently on an Android phone (a Pixel, say) over USB with adb, '
                'grouping the segments of one recording in a folder ready for pre-video.py.')
parser.add_argument('--desde', dest='desde', default='7d',
                    help='How recent a video must be: 90m, 12h, 7d (default), or a date 2026-09-04.')
parser.add_argument('--o', dest='destino', default=str(DESTINO), help=f'Folder for the copies ({DESTINO}).')
parser.add_argument('--vigilar', dest='vigilar', action='store_true',
                    help='Keep waiting: every few seconds look for the phone and pull whatever is new, until Ctrl+C.')
parser.add_argument('--serie', dest='serie', default=None, help='Serial of the phone if more than one is plugged in.')
parser.add_argument('--incluir-emulador', dest='emulador', action='store_true',
                    help='Also accept an Android emulator as the phone (for testing).')
parser.add_argument('--todo', dest='todo', action='store_true',
                    help='Copy again videos that were already pulled (by default they are skipped).')
parser.add_argument('--adb', dest='adb', default=None, help='Path to adb, if it is not in PATH nor in the Android SDK.')
parser.add_argument('--procesar', dest='procesar', action='store_true',
                    help='After pulling, run utiles/procesar-biblioteca.py: group the recordings into books and turn each into text and PDF.')
args = parser.parse_args()


# Function to find adb: PATH first, then the usual Android SDK locations
def localizar_adb():
    candidatos = [args.adb, shutil.which('adb'),
                  Path.home() / 'Library' / 'Android' / 'sdk' / 'platform-tools' / 'adb',
                  Path(os.environ.get('ANDROID_HOME', '')) / 'platform-tools' / 'adb',
                  Path(os.environ.get('ANDROID_SDK_ROOT', '')) / 'platform-tools' / 'adb',
                  '/opt/homebrew/bin/adb', '/usr/local/bin/adb']
    for candidato in candidatos:
        if candidato and Path(candidato).is_file():
            return str(candidato)
    raise SystemExit('No encuentro adb. Instálalo con «brew install --cask android-platform-tools» o pásalo con --adb.')


ADB = localizar_adb()


# Function to run an adb command and return its output
def adb(*argumentos, serie=None, timeout=120):
    comando = [ADB] + (['-s', serie] if serie else []) + list(argumentos)
    salida = subprocess.run(comando, capture_output=True, text=True, timeout=timeout)
    if salida.returncode != 0:
        raise RuntimeError((salida.stderr or salida.stdout).strip()[:300])
    return salida.stdout


# Function to turn "90m", "12h", "7d" or a date into a datetime
def interpretar_desde(texto):
    coincidencia = re.fullmatch(r'(\d+)([mhd])', texto.strip())
    if coincidencia:
        cantidad, unidad = int(coincidencia.group(1)), coincidencia.group(2)
        return datetime.now() - timedelta(**{{'m': 'minutes', 'h': 'hours', 'd': 'days'}[unidad]: cantidad})
    return datetime.fromisoformat(texto.strip())


# Function to find the phone among the devices adb sees. Returns (serial, state):
# state is 'device' when it is ready, 'unauthorized' while the phone waits for
# the user to accept the debugging prompt, and None when nothing is plugged in
def buscar_telefono():
    lineas = adb('devices', '-l').strip().split('\n')[1:]
    for linea in lineas:
        partes = linea.split()
        if len(partes) < 2:
            continue
        serie, estado = partes[0], partes[1]
        if serie.startswith('emulator-') and not args.emulador:
            continue
        if args.serie and serie != args.serie:
            continue
        modelo = next((p.split(':', 1)[1] for p in partes if p.startswith('model:')), '')
        return serie, estado, modelo
    return None, None, ''


# Function to list the videos on the phone with their size and time. toybox's
# stat prints one line per file; a folder that does not exist just prints an error
def listar_videos(serie):
    videos = []
    for carpeta in CARPETAS_CAMARA:
        try:
            salida = adb('shell', f"stat -c '%s|%Y|%n' {carpeta}/* 2>/dev/null", serie=serie)
        except RuntimeError:
            continue
        for linea in salida.strip().split('\n'):
            partes = linea.split('|', 2)
            if len(partes) != 3 or not partes[2].lower().endswith(EXTENSIONES):
                continue
            videos.append({'ruta': partes[2], 'nombre': Path(partes[2]).name, 'bytes': int(partes[0]),
                           'fecha': datetime.fromtimestamp(int(partes[1]))})
    return videos


# Function to name the recording a segment belongs to: a Pixel cuts a long
# recording in PXL_20260904_175504521.mp4, PXL_20260904_175504521~2.mp4, …
# and Video Boost leaves PXL_….VB-01.COVER.mp4 (a 1080p preview) next to
# PXL_….VB-02.MAIN.mp4 (the full-resolution recording). All of them go to one
# folder, which is what pre-video.py wants
def grabacion_de(nombre):
    return re.sub(r'~\d+$', '', Path(nombre).name.split('.')[0])


# Function to drop the Video Boost previews whose full-resolution file exists:
# same content at a quarter of the resolution, and a gigabyte each
def sin_previas(videos):
    principales = {grabacion_de(v['nombre']) for v in videos if '.VB-02.MAIN' in v['nombre']}
    saltadas = [v for v in videos if '.VB-01.COVER' in v['nombre'] and grabacion_de(v['nombre']) in principales]
    for video in saltadas:
        print(f'  {video["nombre"]}: previa de Video Boost, se salta (está su versión completa)', flush=True)
    return [v for v in videos if v not in saltadas]


# Function to copy the new recent videos, verifying each copy by size
def traer(serie, destino, manifiesto):
    limite = interpretar_desde(args.desde)
    recientes = sin_previas([v for v in listar_videos(serie) if v['fecha'] >= limite])
    pendientes = [v for v in recientes if args.todo or manifiesto.get(v['nombre']) != v['bytes']]
    if not pendientes:
        print(f'  Nada nuevo desde {limite:%Y-%m-%d %H:%M} ({len(recientes)} vídeo(s) recientes ya copiados)', flush=True)
        return []
    copiados = []
    for video in sorted(pendientes, key=lambda v: v['nombre']):
        carpeta = destino / grabacion_de(video['nombre'])
        carpeta.mkdir(parents=True, exist_ok=True)
        ruta = carpeta / video['nombre']
        print(f'  {video["nombre"]} ({video["bytes"] / 1e6:.0f} MB, {video["fecha"]:%Y-%m-%d %H:%M}) → {carpeta.name}/', flush=True)
        inicio = time.time()
        adb('pull', video['ruta'], str(ruta), serie=serie, timeout=3600)
        if not ruta.exists() or ruta.stat().st_size != video['bytes']:
            ruta.unlink(missing_ok=True)
            raise RuntimeError(f'La copia de {video["nombre"]} no coincide en tamaño; se descarta')
        print(f'    copiado en {time.time() - inicio:.0f} s', flush=True)
        manifiesto[video['nombre']] = video['bytes']
        (destino / 'manifiesto.json').write_text(json.dumps(manifiesto, indent=2, ensure_ascii=False))
        copiados.append(ruta)
    grabaciones = sorted({c.parent for c in copiados})
    print(f'{len(copiados)} vídeo(s) copiados en {len(grabaciones)} grabación(es): '
          + ', '.join(g.name for g in grabaciones), flush=True)
    return copiados


# Function to run once, or keep watching for the phone
def principal():
    destino = Path(args.destino)
    destino.mkdir(parents=True, exist_ok=True)
    ruta_manifiesto = destino / 'manifiesto.json'
    manifiesto = json.loads(ruta_manifiesto.read_text()) if ruta_manifiesto.exists() else {}
    avisado = None
    while True:
        serie, estado, modelo = buscar_telefono()
        if estado == 'device':
            print(f'Teléfono conectado: {modelo or serie}', flush=True)
            try:
                copiados = traer(serie, destino, manifiesto)
                if copiados and args.procesar:
                    print('Copia terminada: se procesa la biblioteca', flush=True)
                    subprocess.run([sys.executable, '-u', str(RAIZ / 'utiles' / 'procesar-biblioteca.py'), '--f', str(destino)], cwd=RAIZ)
            except RuntimeError as error:
                print(f'  Error: {error}', flush=True)
                if not args.vigilar:
                    sys.exit(1)
            if not args.vigilar:
                return
            # ya se copió lo que había: se espera a que el teléfono se desconecte
            # y vuelva, para no repetir el listado cada pocos segundos
            while buscar_telefono()[1] == 'device':
                time.sleep(5)
            print('Teléfono desconectado; esperando…', flush=True)
        elif estado == 'unauthorized':
            if avisado != 'unauthorized':
                print('El teléfono pide permiso: acepta en su pantalla «Permitir depuración USB» (marca «Permitir siempre»).', flush=True)
                avisado = 'unauthorized'
            if not args.vigilar:
                sys.exit(1)
        else:
            if not args.vigilar:
                sys.exit('No hay ningún teléfono conectado por USB con la depuración USB activada '
                         '(Ajustes → Sistema → Opciones para desarrolladores → Depuración por USB).')
            if avisado != 'esperando':
                print('Esperando a que conectes el teléfono por USB…', flush=True)
                avisado = 'esperando'
        time.sleep(5)


principal()
