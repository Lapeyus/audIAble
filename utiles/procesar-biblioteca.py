# Importing required libraries
import re
import sys
import json
import shutil
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

import cv2

# La raíz del repositorio queda un nivel por encima de esta carpeta
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from nucleo.rutas import carpeta_telefono, carpeta_salida
from nucleo.exportar import exportar_pdf_enriquecido

with open(RAIZ / 'config.json') as f:
    CONFIG = json.load(f)
EXTENSIONES_VIDEO = ('.mp4', '.mov', '.m4v', '.avi', '.mkv', '.webm')
PASOS = RAIZ / 'pasos'

# Command line arguments setup
parser = argparse.ArgumentParser(
    description='Turn the phone library (one folder per recording, as utiles/traer-videos.py leaves it) into books: '
                'recordings are grouped by time and by the text they share, each book gets its pages in order '
                'without repeats, and then OCR, clean-up, TXT and enriched PDF.')
parser.add_argument('--f', dest='biblioteca', default=str(carpeta_telefono()), help='Folder with the recordings.')
parser.add_argument('--o', dest='salida', default=str(carpeta_salida() / 'libros'), help='Folder for the books.')
parser.add_argument('--pausa', dest='pausa', type=float, default=CONFIG.get('Rutas', {}).get('pausa_entre_grabaciones_h', 3),
                    help='Hours between the end of a recording and the start of the next below which they are the same book.')
parser.add_argument('--simple', dest='simple', action='store_true',
                    help='One page per shot. By default the book is assumed open (two pages per shot).')
parser.add_argument('--idioma', dest='idioma', default='es', help='Language of the books (es, en, fr, it, pt, de).')
parser.add_argument('--similitud', dest='similitud', type=float, default=CONFIG['Video'].get('similitud_minima', 0.45),
                    help='Share of 4-grams two pages must share to be the same page at a joint between recordings.')
parser.add_argument('--solo-agrupar', dest='solo_agrupar', action='store_true',
                    help='Detect the pages and print the grouping into books, without OCR nor exports.')
parser.add_argument('--sin-llm', dest='sin_llm', action='store_true', default=True,
                    help='Clean with the deterministic rules only (default; the LLM pass is run from the interface).')
args = parser.parse_args()


# Function to run one of the pipeline scripts, streaming its output
def ejecutar(comando):
    print('$ ' + ' '.join(str(c) for c in comando), flush=True)
    proceso = subprocess.run([sys.executable, '-u'] + [str(c) for c in comando], cwd=RAIZ)
    if proceso.returncode != 0:
        raise RuntimeError(f'{Path(str(comando[0])).name} terminó con error {proceso.returncode}')


# Function to sort names the way a phone numbers them
def orden_natural(ruta):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', ruta.name)]


# Function to read when a recording started, from its Pixel-style name, or
# from the file date when the name says nothing
def inicio_de(carpeta, videos):
    coincidencia = re.search(r'(\d{8})_(\d{6})', carpeta.name)
    if coincidencia:
        return datetime.strptime(coincidencia.group(1) + coincidencia.group(2), '%Y%m%d%H%M%S')
    return datetime.fromtimestamp(min(v.stat().st_mtime for v in videos))


# Function to measure how long the videos of a recording last, in seconds
def duracion_de(videos):
    total = 0.0
    for video in videos:
        captura = cv2.VideoCapture(str(video))
        fotogramas, fps = captura.get(cv2.CAP_PROP_FRAME_COUNT), captura.get(cv2.CAP_PROP_FPS) or 30
        captura.release()
        total += fotogramas / fps if fotogramas > 0 else 0
    return total


# Function to list the recordings of the library with their videos, skipping
# the Video Boost previews when the full file is there
def listar_grabaciones(biblioteca):
    grabaciones = []
    for carpeta in sorted((c for c in biblioteca.iterdir() if c.is_dir() and not c.name.startswith('.')), key=orden_natural):
        videos = sorted((v for v in carpeta.iterdir() if v.suffix.lower() in EXTENSIONES_VIDEO and not v.name.startswith('.')),
                        key=orden_natural)
        completas = {re.sub(r'~\d+$', '', v.name.split('.')[0]) for v in videos if '.VB-02.MAIN' in v.name}
        videos = [v for v in videos if not ('.VB-01.COVER' in v.name and re.sub(r'~\d+$', '', v.name.split('.')[0]) in completas)]
        if not videos:
            continue
        inicio = inicio_de(carpeta, videos)
        grabaciones.append({'nombre': carpeta.name, 'carpeta': carpeta, 'videos': videos, 'inicio': inicio,
                            'fin': inicio + timedelta(seconds=duracion_de(videos))})
    return sorted(grabaciones, key=lambda g: g['inicio'])


# Function to detect the pages of one recording (reused when already done)
def detectar_paginas(grabacion, carpeta_grabaciones):
    carpeta = carpeta_grabaciones / grabacion['nombre'] / 'imagenes'
    comando = [PASOS / 'pre-video.py', '--f'] + grabacion['videos'] + ['--o', carpeta, '--idioma', args.idioma, '--brutos', '--guardar-capturas']
    if not args.simple:
        comando.append('--doble')
    ejecutar(comando)
    informe = json.loads((carpeta / 'calidad.json').read_text(encoding='utf-8'))
    grabacion['paginas'] = [{'ruta': carpeta / f'pag_{p["pagina"]}.png', 'texto': p.get('texto', ''), 'numero': p['pagina']}
                            for p in informe]
    return grabacion['paginas']


# Function to reduce a text to its character 4-grams, the measure pre-video.py
# uses too: tolerant to the words the OCR misreads at video resolution
def cuatrigramas(texto):
    texto = re.sub(r'\s+', ' ', texto.lower())
    return {texto[i:i + 4] for i in range(len(texto) - 3)}


def contencion(a, b):
    if not a or not b or min(len(a), len(b)) < 25:
        return 0.0
    proporcion = min(len(a), len(b)) / max(len(a), len(b))
    c = len(a & b) / min(len(a), len(b))
    return c * 0.7 if proporcion < 0.25 else c


# Function to decide whether two consecutive recordings are the same book:
# recorded within a few hours of each other, or sharing the page at the cut,
# or sharing the vocabulary of the whole recording (names, places, words of
# the book). Returns the criterion that decided, or None
def mismo_libro(anterior, siguiente):
    pausa = siguiente['inicio'] - anterior['fin']
    if pausa < timedelta(hours=args.pausa):
        return f'grabadas con {pausa.total_seconds() / 3600:.1f} h de separación'
    ultimas = cuatrigramas(' '.join(p['texto'] for p in anterior['paginas'][-2:]))
    primeras = cuatrigramas(' '.join(p['texto'] for p in siguiente['paginas'][:2]))
    if contencion(ultimas, primeras) >= args.similitud:
        return 'la última página de una es la primera de la otra'
    def vocabulario(grabacion):
        return {w for p in grabacion['paginas'] for w in re.findall(r'\w{5,}', p['texto'].lower())}
    va, vb = vocabulario(anterior), vocabulario(siguiente)
    if va and vb:
        jaccard = len(va & vb) / len(va | vb)
        if jaccard >= 0.3:
            return f'comparten el vocabulario (Jaccard {jaccard:.2f})'
    return None


# Function to group the recordings into books, in order
def agrupar(grabaciones):
    libros = []
    for grabacion in grabaciones:
        if libros:
            motivo = mismo_libro(libros[-1][-1], grabacion)
            if motivo:
                print(f'  {grabacion["nombre"]} sigue al mismo libro que {libros[-1][-1]["nombre"]}: {motivo}', flush=True)
                libros[-1].append(grabacion)
                continue
            print(f'  {grabacion["nombre"]} empieza otro libro', flush=True)
        libros.append([grabacion])
    return libros


# Function to lay the pages of a book in order, skipping at each joint the
# pages the next recording repeats from the end of the previous one
def montar_libro(grabaciones, carpeta_libro):
    carpeta_img = carpeta_libro / 'imagenes'
    carpeta_img.mkdir(parents=True, exist_ok=True)
    for vieja in carpeta_img.glob('pag_*.png'):
        vieja.unlink()
    numero, anteriores, origen = 0, [], []
    por_toma = 1 if args.simple else 2
    for grabacion in grabaciones:
        paginas = grabacion['paginas']
        # en la juntura se comparan tomas (dobles páginas), no páginas sueltas
        saltar = 0
        if anteriores:
            cola = [cuatrigramas(p['texto']) for p in anteriores[-3 * por_toma::por_toma]]
            while saltar < len(paginas) and any(contencion(c, cuatrigramas(paginas[saltar]['texto'])) >= args.similitud for c in cola):
                saltar += por_toma
            if saltar:
                print(f'  {grabacion["nombre"]}: sus {saltar} primera(s) página(s) repiten el final de la anterior; se saltan', flush=True)
        for pagina in paginas[saltar:]:
            numero += 1
            shutil.copy(pagina['ruta'], carpeta_img / f'pag_{numero}.png')
            # las capturas de la página viajan con ella, renumeradas, para el OCR multifotograma
            capturas = pagina['ruta'].parent / 'capturas' / pagina['ruta'].stem
            if capturas.is_dir():
                destino = carpeta_img / 'capturas' / f'pag_{numero}'
                shutil.rmtree(destino, ignore_errors=True)
                shutil.copytree(capturas, destino)
            origen.append({'pagina': numero, 'grabacion': grabacion['nombre'], 'pagina_original': pagina['numero']})
        anteriores = paginas
    (carpeta_libro / 'libro.json').write_text(json.dumps({
        'grabaciones': [g['nombre'] for g in grabaciones], 'videos': [v.name for g in grabaciones for v in g['videos']],
        'paginas': numero, 'origen': origen}, indent=2, ensure_ascii=False))
    return numero


# Function to run OCR, clean-up and exports on an assembled book
def producir_libro(carpeta_libro, nombre):
    carpeta_img, carpeta_txt = carpeta_libro / 'imagenes', carpeta_libro / 'texto'
    carpeta_txt.mkdir(exist_ok=True)
    if (carpeta_img / 'capturas').is_dir():
        ejecutar([PASOS / 'pro-multiframe-ocr.py', '--f', carpeta_img, '--o', carpeta_txt, '--idioma', args.idioma])
    else:
        ejecutar([PASOS / 'pro-mac-ocr.py', '--f', carpeta_img, '--o', carpeta_txt, '--idioma', args.idioma, '--calidad', 'base'])
    ejecutar([PASOS / 'pre-cleanup.py', '--f', carpeta_txt, '--idioma', args.idioma])
    paginas_txt = sorted((a for a in carpeta_txt.iterdir() if a.suffix == '.txt' and 'cambios' not in a.name and not a.name.startswith('.')),
                         key=lambda r: int(re.findall(r'\d+', r.stem)[-1]))
    (carpeta_libro / f'{nombre}.txt').write_text('\n\n'.join(a.read_text(encoding='utf-8') for a in paginas_txt), encoding='utf-8')
    exportar_pdf_enriquecido(paginas_txt, carpeta_libro / f'{nombre} (enriquecido).pdf', carpeta_img=carpeta_img, dpi_img=None)
    print(f'Libro listo: {carpeta_libro / nombre}.txt y PDF enriquecido', flush=True)


# Function to run the whole library
def principal():
    biblioteca, salida = Path(args.biblioteca), Path(args.salida)
    grabaciones = listar_grabaciones(biblioteca)
    if not grabaciones:
        raise SystemExit(f'No hay grabaciones en {biblioteca}')
    print(f'{len(grabaciones)} grabación(es) en {biblioteca}:', flush=True)
    for g in grabaciones:
        print(f'  {g["nombre"]}: {len(g["videos"])} vídeo(s), {g["inicio"]:%Y-%m-%d %H:%M} → {g["fin"]:%H:%M}', flush=True)

    carpeta_grabaciones = salida / 'grabaciones'
    for grabacion in grabaciones:
        print(f'\n== Páginas de {grabacion["nombre"]}', flush=True)
        detectar_paginas(grabacion, carpeta_grabaciones)

    print('\n== Agrupación en libros', flush=True)
    libros = agrupar(grabaciones)
    for indice, grupo in enumerate(libros, 1):
        nombre = f'libro_{grupo[0]["inicio"]:%Y-%m-%d_%H%M}'
        print(f'Libro {indice}: {nombre}, {len(grupo)} grabación(es), {sum(len(g["paginas"]) for g in grupo)} páginas antes de fundir junturas', flush=True)
    if args.solo_agrupar:
        return

    for grupo in libros:
        nombre = f'libro_{grupo[0]["inicio"]:%Y-%m-%d_%H%M}'
        carpeta_libro = salida / nombre
        marca = carpeta_libro / 'libro.json'
        # el libro se rehace si cambian sus grabaciones o sus vídeos (por ejemplo, cuando
        # llega la versión completa de Video Boost y sustituye a la previa)
        hecho = json.loads(marca.read_text()) if marca.exists() else {}
        if hecho.get('grabaciones') == [g['nombre'] for g in grupo] \
                and hecho.get('videos') == [v.name for g in grupo for v in g['videos']] \
                and (carpeta_libro / f'{nombre} (enriquecido).pdf').exists():
            print(f'\n== {nombre} ya está hecho con estas mismas grabaciones; se salta', flush=True)
            continue
        print(f'\n== Montando {nombre}', flush=True)
        if (carpeta_libro / 'texto').exists():
            shutil.rmtree(carpeta_libro / 'texto', ignore_errors=True)
        total = montar_libro(grupo, carpeta_libro)
        print(f'{total} páginas; OCR y exportación', flush=True)
        producir_libro(carpeta_libro, nombre)


principal()
