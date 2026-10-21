"""POC: la API de imágenes de TypeSafe System One sobre las páginas que saca pre-video.py.

Cuatro experimentos, cada uno contra una referencia conocida:

  estado    pregunta Choice: ¿la página es texto plano, una hoja a medio pasar, una
            ilustración, una página en blanco o no es una página? Referencia: etiquetas
            puestas a mano (--etiquetas).
  mano      pregunta Noul: ¿una mano o un dedo tapa parte del texto? Referencia: etiquetas.
  misma     pregunta Noul: ¿estas dos imágenes son la misma página impresa? Es la decisión
            que toma la deduplicación del detector. Referencia automática: la misma página
            procesada en dos corridas (--otra-corrida) es «sí»; dos dobles páginas
            consecutivas de una misma corrida son «no».
  box       pregunta Box sobre el fotograma crudo: ¿dónde está el libro abierto? Referencia:
            el cuadrilátero que devuelve Vision de macOS (vision_pagina.swift), comparado
            por IoU de sus cajas.

Sin clave (TYPESAFE_API_KEY) o con --simular, construye y valida las peticiones (tamaños,
referencias, reglas de multipart) y las deja en disco sin enviar nada.

  python3 utiles/poc-typesafe.py --img <carpeta imagenes> --etiquetas etiquetas.json --simular
  TYPESAFE_API_KEY=... python3 utiles/poc-typesafe.py --img <carpeta imagenes> --etiquetas etiquetas.json
"""
# Importing required libraries
import io
import os
import re
import sys
import json
import time
import uuid
import argparse
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageOps

RAIZ = Path(__file__).resolve().parent.parent
CABECERA_IMAGENES = {'TypeSafe-Danger-Zone-Images': 'true'}
LADO_MIN, LADO_MAX = 280, 1568
PIXELES_MIN, PIXELES_MAX = 280 * 280, 1568 * 1568
LIMITE_CUERPO = 32 * 1024 * 1024

ESTADOS = {
    'texto_plano': 'A flat, readable book page that is mostly printed text.',
    'hoja_en_movimiento': 'A page caught while being turned: lifted, curled, tilted or blurred by motion.',
    'ilustracion': 'A page that is mostly a drawing or picture, with little or no text.',
    'en_blanco': 'A blank or almost blank page.',
    'no_es_pagina': 'Not a book page: a cover, a library card or stamp sheet, the table, or only hands.',
}

# Command line arguments setup
parser = argparse.ArgumentParser(description='POC of the TypeSafe System One image API on the pages pre-video.py extracts.')
parser.add_argument('--img', required=True, type=Path, help='Folder of page images (pag_N.png, brutos/, calidad.json).')
parser.add_argument('--etiquetas', type=Path, help='JSON {"pag_N": {"estado": ..., "mano": true|false}} labelled by hand.')
parser.add_argument('--otra-corrida', type=Path, help='Images folder of another run of the same video, for positive "same page" pairs.')
parser.add_argument('--pares', type=int, default=12, help='How many "same page" pairs of each kind.')
parser.add_argument('--tomas', type=int, default=12, help='How many raw frames for the Box experiment.')
parser.add_argument('--experimentos', default='estado,mano,misma,box', help='Comma-separated subset to run.')
parser.add_argument('--modelo', default='jev-latest', help='Model for Choice and Noul questions.')
parser.add_argument('--modelo-box', default='jev-preview', help='Box needs Jev 1.14 (jev-preview or jev-1.14.0).')
parser.add_argument('--hilos', type=int, default=4, help='Requests in flight at once.')
parser.add_argument('--salida', type=Path, default=None, help='Output folder (default <img>/../poc_typesafe).')
parser.add_argument('--simular', action='store_true', help='Build and validate the requests, write them to disk, send nothing.')
parser.add_argument('--comprobar', action='store_true', help='Only check the key: list the models available to the account.')
parser.add_argument('--url', default='https://api.typesafe.ai/v1', help='API base URL (a local mock in the tests).')
parser.add_argument('--boveda', metavar='NOMBRE', nargs='?', const='typesafe', default=None,
                    help='Read the API key from the passManager vault (Google Secret Manager): the credential whose '
                         'name contains NOMBRE (typesafe by default). It is kept in memory only.')
args = parser.parse_args()
URL = args.url.rstrip('/')

CLAVE = os.environ.get('TYPESAFE_API_KEY')
if not CLAVE and args.boveda:
    sys.path.insert(0, str(RAIZ))
    from nucleo.boveda import leer_credencial
    CLAVE = leer_credencial(args.boveda)
    print(f'Clave leída de la bóveda (credencial «{args.boveda}»)', flush=True)
SIMULAR = args.simular or not CLAVE
SALIDA = args.salida or args.img.parent / 'poc_typesafe'


# ---------------------------------------------------------------- imágenes

# Function to make an image the API accepts: upright pixels (the API drops EXIF
# and does not rotate), longest side at most 1568, both sides at least 280
# (scaled up, or padded white when the shape would push the long side over),
# RGB baseline JPEG
def preparar(ruta):
    with Image.open(ruta) as original:
        imagen = ImageOps.exif_transpose(original).convert('RGB')
    imagen.thumbnail((LADO_MAX, LADO_MAX))
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
    ancho, alto = imagen.size
    assert LADO_MIN <= ancho <= LADO_MAX and LADO_MIN <= alto <= LADO_MAX, (ruta, imagen.size)
    assert PIXELES_MIN <= ancho * alto <= PIXELES_MAX, (ruta, imagen.size)
    buffer = io.BytesIO()
    imagen.save(buffer, 'JPEG', quality=90, progressive=False)
    return buffer.getvalue(), imagen.size


# ---------------------------------------------------------------- peticiones

class Peticion:
    """Una petición System One con sus imágenes como partes multipart."""

    def __init__(self, nombre, modelo):
        self.nombre, self.modelo = nombre, modelo
        self.cuerpo = {'model': modelo, 'state': {}, 'questions': {}, 'assets': {}}
        self.partes = {}

    # una referencia que no puede aparecer por accidente en el texto: un UUID nuevo
    def imagen(self, ruta):
        referencia = f'img-{uuid.uuid4().hex}'
        parte = f'parte-{len(self.partes) + 1}'
        datos, tamano = preparar(ruta)
        self.partes[parte] = datos
        self.cuerpo['assets'][referencia] = {'type': 'image', 'part': parte}
        return referencia

    # las reglas de la página de imágenes, comprobadas antes de enviar
    def validar(self):
        texto = json.dumps({k: v for k, v in self.cuerpo.items() if k != 'assets'}, ensure_ascii=False)
        for referencia, activo in self.cuerpo['assets'].items():
            assert referencia in texto, f'{self.nombre}: la referencia {referencia} no se usa (400)'
            assert activo['part'] in self.partes, f'{self.nombre}: falta la parte {activo["part"]}'
        assert len({a['part'] for a in self.cuerpo['assets'].values()}) == len(self.partes), 'partes repetidas o huérfanas'
        assert 'request' not in self.partes, '«request» está reservado para el JSON'
        tamano = len(json.dumps(self.cuerpo).encode()) + sum(len(d) for d in self.partes.values())
        assert tamano < LIMITE_CUERPO, f'{self.nombre}: {tamano / 1e6:.1f} MB supera el límite'
        return tamano

    def guardar(self, carpeta):
        carpeta = carpeta / self.nombre
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / 'request.json').write_text(json.dumps(self.cuerpo, indent=2, ensure_ascii=False))
        for parte, datos in self.partes.items():
            (carpeta / f'{parte}.jpg').write_bytes(datos)

    # multipart: primero la parte «request» con el JSON, después una parte por imagen
    def enviar(self, reintentos=4):
        import requests
        archivos = [('request', (None, json.dumps(self.cuerpo), 'application/json'))]
        archivos += [(parte, (f'{parte}.jpg', datos, 'image/jpeg')) for parte, datos in self.partes.items()]
        for intento in range(reintentos):
            inicio = time.time()
            respuesta = requests.post(f'{URL}/systemone', files=archivos, timeout=180,
                                      headers={'Authorization': f'Bearer {CLAVE}', **CABECERA_IMAGENES})
            if respuesta.status_code in (429, 500, 502, 503, 504) and intento < reintentos - 1:
                time.sleep(2 ** intento)
                continue
            if respuesta.status_code != 200:
                raise RuntimeError(f'{self.nombre}: HTTP {respuesta.status_code}: {respuesta.text[:400]}')
            datos = respuesta.json()
            datos['_segundos'] = round(time.time() - inicio, 2)
            return datos


def peticion_pagina(ruta):
    peticion = Peticion(f'pagina-{ruta.stem}', args.modelo)
    peticion.cuerpo['state'] = {'pagina': peticion.imagen(ruta)}
    if 'estado' in EXPERIMENTOS:
        peticion.cuerpo['questions']['estado'] = {
            'type': 'choice', 'instructions': 'What kind of image is `pagina`, a photo of a book page?', 'criteria': ESTADOS}
    if 'mano' in EXPERIMENTOS:
        peticion.cuerpo['questions']['mano'] = {
            'type': 'noul', 'instructions': 'A hand, finger or thumb covers part of the printed text in `pagina`.'}
    return peticion


def peticion_par(ruta_a, ruta_b, nombre):
    peticion = Peticion(nombre, args.modelo)
    peticion.cuerpo['state'] = {'a': peticion.imagen(ruta_a), 'b': peticion.imagen(ruta_b)}
    peticion.cuerpo['questions']['misma'] = {
        'type': 'noul',
        'instructions': '`a` and `b` are photos of the same printed book page (the same text), possibly with '
                        'different lighting, crop, angle or a hand in a different place.'}
    return peticion


def peticion_toma(ruta):
    peticion = Peticion(f'toma-{ruta.stem}', args.modelo_box)
    peticion.cuerpo['state'] = {'foto': peticion.imagen(ruta)}
    peticion.cuerpo['questions'] = {
        'libro': {'type': 'box', 'instructions': 'The printed pages of the open book in `foto`, both pages, without the table.'},
        'hay_libro': {'type': 'noul', 'instructions': 'There is an open book in `foto`.'},
    }
    return peticion


# ---------------------------------------------------------------- referencias

def numero(ruta):
    return int(re.findall(r'\d+', ruta.stem)[-1])


# Function to get Vision's page quad for each raw frame, as a box in fractions
def cajas_vision(rutas):
    salida = subprocess.run(['swift', str(RAIZ / 'pasos' / 'vision_pagina.swift'), 'cuadro'] + [str(r) for r in rutas],
                            capture_output=True, text=True, timeout=1800)
    cajas, actual = {}, None
    for linea in salida.stdout.splitlines():
        if linea.startswith('###FILE:'):
            actual = linea[len('###FILE:'):]
        elif actual and linea.strip() and not linea.startswith('###'):
            v = [float(x) for x in linea.split()]
            with Image.open(actual) as imagen:
                ancho, alto = ImageOps.exif_transpose(imagen).size
            xs, ys = v[0::2], v[1::2]
            cajas[actual] = {'left': min(xs) / ancho, 'right': max(xs) / ancho, 'top': min(ys) / alto, 'bottom': max(ys) / alto}
    return cajas


def iou(a, b):
    ancho = max(0.0, min(a['right'], b['right']) - max(a['left'], b['left']))
    alto = max(0.0, min(a['bottom'], b['bottom']) - max(a['top'], b['top']))
    interseccion = ancho * alto
    area = lambda c: (c['right'] - c['left']) * (c['bottom'] - c['top'])
    return interseccion / max(area(a) + area(b) - interseccion, 1e-9)


# ---------------------------------------------------------------- ejecución

def construir():
    peticiones, referencias = [], {}
    paginas = sorted(args.img.glob('pag_*.png'), key=numero)
    etiquetas = json.loads(args.etiquetas.read_text()) if args.etiquetas else {}

    if {'estado', 'mano'} & EXPERIMENTOS:
        if not etiquetas:
            sys.exit('Los experimentos estado y mano necesitan --etiquetas')
        for nombre in (n for n in etiquetas if not n.startswith('_')):
            ruta = args.img / f'{nombre}.png'
            peticiones.append(peticion_pagina(ruta))
            referencias[peticiones[-1].nombre] = etiquetas[nombre]

    if 'misma' in EXPERIMENTOS:
        # negativos: la misma cara del libro en dos dobles páginas consecutivas
        paso = max(1, (len(paginas) - 2) // args.pares)
        for i in range(0, min(len(paginas) - 2, paso * args.pares), paso):
            a, b = paginas[i], paginas[i + 2]
            peticiones.append(peticion_par(a, b, f'par-distintas-{a.stem}-{b.stem}'))
            referencias[peticiones[-1].nombre] = {'misma': False}
        # positivos: la misma página de otra corrida del mismo vídeo
        if args.otra_corrida:
            for i in range(0, min(len(paginas), paso * args.pares), paso):
                otra = args.otra_corrida / paginas[i].name
                if otra.exists():
                    peticiones.append(peticion_par(paginas[i], otra, f'par-iguales-{paginas[i].stem}'))
                    referencias[peticiones[-1].nombre] = {'misma': True}

    if 'box' in EXPERIMENTOS:
        tomas = sorted((t for t in (args.img / 'brutos').glob('toma_*.png') if re.fullmatch(r'toma_\d+', t.stem)), key=numero)
        paso = max(1, len(tomas) // args.tomas)
        elegidas = tomas[::paso][:args.tomas]
        vision = cajas_vision(elegidas) if sys.platform == 'darwin' else {}
        for toma in elegidas:
            peticiones.append(peticion_toma(toma))
            referencias[peticiones[-1].nombre] = {'caja_vision': vision.get(str(toma)), 'ruta': str(toma)}
    return peticiones, referencias


def evaluar(resultados, referencias):
    filas, resumen = [], {}
    for nombre, respuesta in resultados.items():
        if 'error' in respuesta:
            filas.append({'peticion': nombre, 'error': respuesta['error']})
            continue
        ref, respuestas, fila = referencias[nombre], respuesta['answers'], {'peticion': nombre}
        if 'estado' in respuestas:
            fila.update(estado_esperado=ref.get('estado'), estado=respuestas['estado']['choice'],
                        estado_confianza=round(respuestas['estado']['confidence'], 2))
        if 'mano' in respuestas:
            fila.update(mano_esperada=ref.get('mano'), mano_prob=round(respuestas['mano']['noul'], 2))
        if 'misma' in respuestas:
            fila.update(misma_esperada=ref['misma'], misma_prob=round(respuestas['misma']['noul'], 2))
        if 'libro' in respuestas:
            caja = respuestas['libro']['box']
            fila.update(caja=caja, caja_confianza=respuestas['libro'].get('confidence'),
                        hay_libro=round(respuestas['hay_libro']['noul'], 2))
            if ref.get('caja_vision'):
                fila['iou_con_vision'] = round(iou(caja, ref['caja_vision']), 3)
        fila.update(segundos=respuesta.get('_segundos'), tokens=respuesta.get('usage', {}).get('input_tokens'))
        filas.append(fila)

    def acierto(clave_esperada, clave_obtenida, convertir=lambda x: x):
        pares = [(f[clave_esperada], convertir(f[clave_obtenida])) for f in filas if f.get(clave_esperada) is not None and clave_obtenida in f]
        return {'casos': len(pares), 'aciertos': sum(e == o for e, o in pares)} if pares else None

    resumen['estado'] = acierto('estado_esperado', 'estado')
    resumen['mano'] = acierto('mano_esperada', 'mano_prob', lambda p: p >= 0.5)
    resumen['misma'] = acierto('misma_esperada', 'misma_prob', lambda p: p >= 0.5)
    ious = [f['iou_con_vision'] for f in filas if 'iou_con_vision' in f]
    if ious:
        resumen['box'] = {'casos': len(ious), 'iou_mediano': sorted(ious)[len(ious) // 2], 'iou_minimo': min(ious),
                          'por_encima_de_0_8': sum(i >= 0.8 for i in ious)}
    segundos = [f['segundos'] for f in filas if f.get('segundos')]
    tokens = [f['tokens'] for f in filas if f.get('tokens')]
    if segundos:
        resumen['latencia_mediana_s'] = sorted(segundos)[len(segundos) // 2]
    if tokens:
        resumen['tokens_totales'] = sum(tokens)
    return filas, resumen


# Function to draw the Box answers next to Vision's, to check them by eye
def dibujar_cajas(filas, referencias):
    from PIL import ImageDraw
    vistas = []
    for fila in filas:
        if 'caja' not in fila:
            continue
        ref = referencias[fila['peticion']]
        with Image.open(ref['ruta']) as original:
            imagen = ImageOps.exif_transpose(original).convert('RGB')
        imagen.thumbnail((400, 400))
        dibujo, (ancho, alto) = ImageDraw.Draw(imagen), imagen.size
        for caja, color in ((ref.get('caja_vision'), (0, 160, 255)), (fila['caja'], (255, 0, 0))):
            if caja:
                dibujo.rectangle([caja['left'] * ancho, caja['top'] * alto, caja['right'] * ancho, caja['bottom'] * alto],
                                 outline=color, width=4)
        vistas.append(imagen)
    if vistas:
        lienzo = Image.new('RGB', (sum(v.width for v in vistas[:6]), max(v.height for v in vistas) * ((len(vistas) + 5) // 6)), 'white')
        for i, vista in enumerate(vistas):
            lienzo.paste(vista, ((i % 6) * vistas[0].width, (i // 6) * max(v.height for v in vistas)))
        lienzo.save(SALIDA / 'cajas.jpg', quality=85)


def principal():
    if args.comprobar:
        import requests
        if not CLAVE:
            sys.exit('Falta TYPESAFE_API_KEY')
        respuesta = requests.get(f'{URL}/models', headers={'Authorization': f'Bearer {CLAVE}'}, timeout=30)
        print(respuesta.status_code, respuesta.text[:2000])
        return

    SALIDA.mkdir(parents=True, exist_ok=True)
    peticiones, referencias = construir()
    total = sum(p.validar() for p in peticiones)
    print(f'{len(peticiones)} peticiones válidas, {total / 1e6:.1f} MB en total', flush=True)

    if SIMULAR:
        for peticion in peticiones:
            peticion.guardar(SALIDA / 'peticiones')
        (SALIDA / 'referencias.json').write_text(json.dumps(referencias, indent=2, ensure_ascii=False))
        motivo = 'sin TYPESAFE_API_KEY' if not CLAVE else '--simular'
        print(f'Simulación ({motivo}): peticiones y referencias en {SALIDA}; no se ha enviado nada', flush=True)
        return

    def una(peticion):
        try:
            return peticion.nombre, peticion.enviar()
        except Exception as error:
            return peticion.nombre, {'error': str(error)}

    with ThreadPoolExecutor(args.hilos) as grupo:
        resultados = dict(grupo.map(una, peticiones))
    (SALIDA / 'respuestas.json').write_text(json.dumps(resultados, indent=2, ensure_ascii=False))
    filas, resumen = evaluar(resultados, referencias)
    (SALIDA / 'resultados.json').write_text(json.dumps({'resumen': resumen, 'filas': filas}, indent=2, ensure_ascii=False))
    dibujar_cajas(filas, referencias)
    print(json.dumps(resumen, indent=2, ensure_ascii=False))
    errores = [f for f in filas if 'error' in f]
    if errores:
        print(f'{len(errores)} petición(es) con error; la primera: {errores[0]["error"]}')
    print(f'Detalle en {SALIDA}/resultados.json' + (' y cajas.jpg' if 'box' in EXPERIMENTOS else ''))


EXPERIMENTOS = set(args.experimentos.split(','))
principal()
