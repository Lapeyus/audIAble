import os
import json
import argparse
from pathlib import Path
from google.cloud import vision_v1p3beta1 as vision

# Configuración de las credenciales de GCP
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'credentials.json'

# Argumentos desde la línea de comando
parser = argparse.ArgumentParser(description='Procesar imágenes y generar archivos de texto.')
parser.add_argument('--f', dest='folder_input', required=True, help='Carpeta con las imágenes a procesar')
parser.add_argument('--o', dest='folder_output', required=True, help='Carpeta donde guardar los archivos de texto generados')
args = parser.parse_args()

# Inicializa el cliente de Vision
client_vision = vision.ImageAnnotatorClient()

# Directorios de archivos
folder_input = Path(args.folder_input)
folder_output = Path(args.folder_output)

# Crea el directorio de salida si no existe
folder_output.mkdir(parents=True, exist_ok=True)

# Cargar configuraciones de JSON
with open('config.json') as f:
    config = json.load(f)


# Función para procesar imágenes y generar archivos de texto
def procesar_imagenes():
    for imagen in folder_input.iterdir():
        if imagen.suffix in ['.jpg', '.png']:
            ruta_texto = folder_output / f'{imagen.stem}.txt'
            if not ruta_texto.exists():
                with open(imagen, 'rb') as imagen_archivo:
                    contenido = imagen_archivo.read()

                respuesta_vision = client_vision.document_text_detection(
                    image=vision.Image(content=contenido),
                    image_context=config['VisionAPI']['image_context'])
                texto_extraido = respuesta_vision.full_text_annotation.text

                with open(ruta_texto, 'w') as archivo_texto:
                    archivo_texto.write(texto_extraido)


# Llamada a la función para procesar imágenes
procesar_imagenes()
