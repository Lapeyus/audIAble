import os
import json
import argparse
from pathlib import Path
from google.cloud import vision_v1p3beta1 as vision

# Configuración de las credenciales de GCP
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'credentials.json'

# Argumentos desde la línea de comando
parser = argparse.ArgumentParser(description='Procesar # Importing required libraries
import os
import json
import argparse
from pathlib import Path
from google.cloud import vision_v1p3beta1 as vision

# Setting up the Google Cloud Platform credentials
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = 'credentials.json'

# Command line arguments setup
parser = argparse.ArgumentParser(description='Process images and generate text files.')
parser.add_argument('--f', dest='folder_input', required=True, help='Folder with images to process')
parser.add_argument('--o', dest='folder_output', required=True, help='Folder to save the generated text files')
args = parser.parse_args()

# Initialize Vision client
client_vision = vision.ImageAnnotatorClient()

# File directories
folder_input = Path(args.folder_input)
folder_output = Path(args.folder_output)

# Create output directory if it doesn't exist
folder_output.mkdir(parents=True, exist_ok=True)

# Load JSON configurations
with open('config.json') as f:
    config = json.load(f)


# Function to process images and generate text files
def procesar_imagenes():
    # Iterate over each image in the input folder
    for imagen in folder_input.iterdir():
        # Process only jpg and png images
        if imagen.suffix in ['.jpg', '.png']:
            ruta_texto = folder_output / f'{imagen.stem}.txt'
            # Process the image only if its corresponding text file doesn't exist
            if not ruta_texto.exists():
                # Open the image file
                with open(imagen, 'rb') as imagen_archivo:
                    contenido = imagen_archivo.read()

                # Use the Vision API to detect text in the image
                respuesta_vision = client_vision.document_text_detection(
                    image=vision.Image(content=contenido),
                    image_context=config['VisionAPI']['image_context'])
                # Extract the detected text
                texto_extraido = respuesta_vision.full_text_annotation.text

                # Write the extracted text to a file
                with open(ruta_texto, 'w') as archivo_texto:
                    archivo_texto.write(texto_extraido)


# Call the function to process images
procesar_imagenes()
imágenes y generar archivos de texto.')
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
