# Importing required libraries
import re
import json
import tempfile
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
parser.add_argument('--calidad', choices=['base', 'alta', 'auto'], default='base',
                    help='base: una lectura por página. alta: tres lecturas (original, iluminación uniformada y contraste '
                         'local) y consenso línea a línea, con un informe .ocr.json de las líneas dudosas; cuesta el triple '
                         'y en la evaluación sintética no bajó el error, así que es opcional. auto: alta solo para páginas '
                         'que vienen de un vídeo (carpeta con origen.json).')
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
            raise RuntimeError(f'{actual}: {linea[len("###ERROR:"):]}')
        elif actual is not None:
            textos[actual].append(linea)
    if any(str(i) not in textos for i in imagenes):
        raise RuntimeError('Vision no devolvió todas las imágenes; no se guarda un OCR incompleto')
    return {ruta: '\n'.join(lineas).strip() for ruta, lineas in textos.items()}

def reconocer_alta(imagen):
    sys.path.insert(0, str(RAIZ))
    import cv2
    from nucleo.ocr_calidad import variantes, consenso
    original = cv2.imread(str(imagen))
    if original is None:
        raise RuntimeError(f'No se pudo abrir {imagen}')
    with tempfile.TemporaryDirectory(prefix='audIAble-ocr-') as temporal:
        rutas = [imagen]
        for indice, variante in enumerate(variantes(original)):
            ruta = Path(temporal) / f'variante_{indice}.png'
            if not cv2.imwrite(str(ruta), variante):
                raise RuntimeError(f'No se pudo escribir {ruta}')
            rutas.append(ruta)
        comando = ['swift', str(RAIZ / 'pasos' / 'vision_ocr.swift'),
                   f'{IDIOMAS_VISION[args.idioma]},en-US', '--json'] + [str(r) for r in rutas]
        salida = subprocess.run(comando, capture_output=True, text=True, timeout=3600)
        if salida.returncode:
            raise RuntimeError(f'Vision falló: {salida.stderr[:300]}')
        leidas, actual = {}, None
        for linea in salida.stdout.splitlines():
            if linea.startswith('###FILE:'):
                actual = linea[len('###FILE:'):]
            elif linea.startswith('###ERROR:'):
                raise RuntimeError(f'{actual}: {linea}')
            elif actual is not None and linea.strip():
                leidas[actual] = json.loads(linea)
        if any(str(r) not in leidas for r in rutas):
            raise RuntimeError('Vision no devolvió todas las capturas; no se guarda un OCR incompleto')
        base, a, b = [leidas[str(r)] for r in rutas]
        if not base and (a or b):
            raise RuntimeError(f'{imagen.name}: las variantes detectan texto pero la lectura base está vacía; revisar imagen')
        return consenso(base, [a, b])


# Function to process every image in the input folder, in batches so one swift
# start-up serves many pages
def procesar_imagenes():
    folder_input = Path(args.folder_input)
    folder_output = Path(args.folder_output)
    folder_output.mkdir(parents=True, exist_ok=True)

    pendientes = [i for i in sorted(folder_input.iterdir())
                  if i.suffix.lower() in ('.png', '.jpg', '.jpeg') and not i.name.startswith('.')
                  and i.stem != 'paginas_detectadas'
                  and not (folder_output / f'{i.stem}.txt').exists()]
    alta = args.calidad == 'alta' or (args.calidad == 'auto' and (folder_input / 'origen.json').exists())
    if alta:
        for imagen in pendientes:
            texto, informe = reconocer_alta(imagen)
            (folder_output / f'{imagen.stem}.ocr.json').write_text(json.dumps(informe, ensure_ascii=False, indent=2), encoding='utf-8')
            (folder_output / f'{imagen.stem}.txt').write_text(texto + '\n', encoding='utf-8')
            print(f'{imagen.name}: {len(texto)} caracteres, {sum(l["revisar"] for l in informe)} líneas para revisar', flush=True)
        return
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
