# Importing required libraries
import re
import sys
import time
import argparse
import subprocess
from pathlib import Path

# La raíz del repositorio queda un nivel por encima de esta carpeta
RAIZ = Path(__file__).resolve().parent.parent

# Vision quiere los idiomas como códigos regionales completos
IDIOMAS_VISION = {'es': 'es-ES', 'en': 'en-US', 'fr': 'fr-FR', 'it': 'it-IT', 'pt': 'pt-BR', 'de': 'de-DE'}

# Command line arguments setup
parser = argparse.ArgumentParser(description='Read scanned page images with the macOS Vision framework: free, local and offline.')
parser.add_argument('--f', dest='folder_input', required=True, help='Folder containing the page images.')
parser.add_argument('--o', dest='folder_output', required=True, help='Folder to save the extracted text files.')
parser.add_argument('--idioma', dest='idioma', default='es', choices=sorted(IDIOMAS_VISION), help='Language of the book, guides the recognition.')
args = parser.parse_args()

if sys.platform != 'darwin':
    sys.exit('Este motor usa el framework Vision de macOS y solo funciona en macOS.')

# Function to run the Swift helper over a batch of images and split its output
def reconocer(imagenes):
    comando = ['swift', str(RAIZ / 'pasos' / 'vision_ocr.swift'),
               f"{IDIOMAS_VISION[args.idioma]},en-US"] + [str(i) for i in imagenes]
    salida = subprocess.run(comando, capture_output=True, text=True, timeout=3600)
    if salida.returncode != 0:
        sys.exit(f'El ayudante de Vision falló: {salida.stderr.strip()[:300]}')
    textos, actual = {}, None
    for linea in salida.stdout.split('\n'):
        if linea.startswith('###FILE:'):
            actual = linea[len('###FILE:'):]
            textos[actual] = []
        elif linea.startswith('###ERROR:'):
            print(f'  {Path(actual).name}: {linea[len("###ERROR:"):]}', flush=True)
        elif actual is not None:
            textos[actual].append(linea)
    return {ruta: '\n'.join(lineas).strip() for ruta, lineas in textos.items()}

# Function to process every image in the input folder, in batches so one swift
# start-up serves many pages
def procesar_imagenes():
    folder_input = Path(args.folder_input)
    folder_output = Path(args.folder_output)
    folder_output.mkdir(parents=True, exist_ok=True)

    pendientes = [i for i in sorted(folder_input.iterdir())
                  if i.suffix.lower() in ('.png', '.jpg', '.jpeg')
                  and not (folder_output / f'{i.stem}.txt').exists()]
    lote = 20
    for inicio_lote in range(0, len(pendientes), lote):
        imagenes = pendientes[inicio_lote:inicio_lote + lote]
        inicio = time.time()
        textos = reconocer(imagenes)
        duracion = (time.time() - inicio) / max(len(imagenes), 1)
        for imagen in imagenes:
            texto = textos.get(str(imagen), '')
            ruta_texto = folder_output / f'{imagen.stem}.txt'
            ruta_texto.write_text(texto + '\n', encoding='utf-8')
            print(f'{ruta_texto} ({len(texto)} caracteres, {duracion:.1f}s)', flush=True)

    print(f'{len(pendientes)} imágenes procesadas con Vision de macOS', flush=True)

procesar_imagenes()
