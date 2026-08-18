# Importing required libraries
import sys
import argparse
from pathlib import Path

# La raíz del repositorio queda un nivel por encima de esta carpeta
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from nucleo.limpieza import limpiar_texto



# Function to tell a page of the book from a report written by pre-ollama.py,
# which lives alongside the pages and must never be read out loud
def es_pagina(ruta):
    return ruta.suffix == '.txt' and not ruta.name.endswith('.cambios.txt')


# Function to process all text files in a directory
def procesar_directorio(folder_input, folder_output=None, idioma='es'):
    folder_input = Path(folder_input)
    archivos = sorted(archivo for archivo in folder_input.iterdir() if es_pagina(archivo))
    if folder_output:
        folder_output = Path(folder_output)
        folder_output.mkdir(parents=True, exist_ok=True)

    for archivo in archivos:
        original = archivo.read_text(encoding='utf-8')
        limpio = limpiar_texto(original, idioma)
        destino = (folder_output / archivo.name) if folder_output else archivo
        destino.write_text(limpio, encoding='utf-8')
        print(f'{destino}  ({len(original)} -> {len(limpio)} caracteres)')

    print(f'{len(archivos)} files have been processed.')

# Main function to handle command line arguments and call the processing function
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Clean up extracted text with deterministic rules, ready for TTS.')
    parser.add_argument('--f', dest='folder_input', required=True, help='Folder with the text files to clean up.')
    parser.add_argument('--o', dest='folder_output', help='Folder to write the cleaned files. Overwrites in place if omitted.')
    parser.add_argument('--idioma', dest='idioma', default='es', help='Language of the book: picks the abbreviation table (es, en).')
    args = parser.parse_args()
    procesar_directorio(args.folder_input, args.folder_output, args.idioma)
