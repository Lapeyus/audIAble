"""Cliente mínimo de TypeSafe System One con imágenes, sobre HTTP (multipart).

La clave sale de TYPESAFE_API_KEY o, si no está, de la bóveda passManager (credencial
«jev — API key»). Las imágenes se preparan como pide la documentación: píxeles girados
(la API descarta el EXIF), lado mayor de 1568 como máximo, ambos lados de 280 como mínimo,
JPEG baseline. Las preguntas de imagen están en fase de prototipo («Dreamer-ready»).
"""
import io
import os
import json
import time
import uuid

from PIL import Image, ImageOps

URL = os.environ.get('TYPESAFE_URL', 'https://api.typesafe.ai/v1')
LADO_MIN, LADO_MAX = 280, 1568
CREDENCIAL_BOVEDA = 'jev — API key'
_CLAVE = None


def clave():
    global _CLAVE
    if _CLAVE is None:
        _CLAVE = os.environ.get('TYPESAFE_API_KEY')
        if not _CLAVE:
            from nucleo.boveda import leer_credencial
            _CLAVE = leer_credencial(CREDENCIAL_BOVEDA)
    return _CLAVE


# Function to make an image the API accepts. lado_max below 1568 trades detail
# for tokens: every image is billed by its size
def preparar(ruta_o_imagen, lado_max=LADO_MAX):
    if isinstance(ruta_o_imagen, Image.Image):
        imagen = ruta_o_imagen.convert('RGB')
    else:
        with Image.open(ruta_o_imagen) as original:
            imagen = ImageOps.exif_transpose(original).convert('RGB')
    imagen.thumbnail((lado_max, lado_max))
    ancho, alto = imagen.size
    if min(ancho, alto) < LADO_MIN:
        escala = LADO_MIN / min(ancho, alto)
        nuevo = (round(ancho * escala), round(alto * escala))
        if max(nuevo) <= LADO_MAX:
            imagen = imagen.resize(nuevo, Image.LANCZOS)
        else:
            lienzo = Image.new('RGB', (max(ancho, LADO_MIN), max(alto, LADO_MIN)), 'white')
            lienzo.paste(imagen, (0, 0))
            imagen = lienzo
    buffer = io.BytesIO()
    imagen.save(buffer, 'JPEG', quality=90, progressive=False)
    return buffer.getvalue()


class Peticion:
    """Una petición System One: estado, preguntas e imágenes como partes multipart."""

    def __init__(self, modelo='jev-latest', lado_max=LADO_MAX):
        self.cuerpo = {'model': modelo, 'state': {}, 'questions': {}, 'assets': {}}
        self.partes, self.lado_max = {}, lado_max

    # devuelve la referencia que se escribe donde va la imagen: un UUID nuevo, que
    # no puede aparecer por accidente en el texto
    def imagen(self, ruta_o_imagen):
        referencia, parte = f'img-{uuid.uuid4().hex}', f'parte-{len(self.partes) + 1}'
        self.partes[parte] = preparar(ruta_o_imagen, self.lado_max)
        self.cuerpo['assets'][referencia] = {'type': 'image', 'part': parte}
        return referencia

    def noul(self, nombre, instrucciones):
        self.cuerpo['questions'][nombre] = {'type': 'noul', 'instructions': instrucciones}

    def enviar(self, reintentos=4, timeout=180):
        import requests
        archivos = [('request', (None, json.dumps(self.cuerpo), 'application/json'))]
        archivos += [(parte, (f'{parte}.jpg', datos, 'image/jpeg')) for parte, datos in self.partes.items()]
        for intento in range(reintentos):
            respuesta = requests.post(f'{URL}/systemone', files=archivos, timeout=timeout,
                                      headers={'Authorization': f'Bearer {clave()}', 'TypeSafe-Danger-Zone-Images': 'true'})
            if respuesta.status_code in (429, 500, 502, 503, 504) and intento < reintentos - 1:
                time.sleep(2 ** intento)
                continue
            if respuesta.status_code != 200:
                raise RuntimeError(f'TypeSafe HTTP {respuesta.status_code}: {respuesta.text[:300]}')
            return respuesta.json()
