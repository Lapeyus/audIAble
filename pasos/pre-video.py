# Importing required libraries
import re
import sys
import json
import time
import shutil
import argparse
import warnings
import subprocess
from pathlib import Path

import cv2
import numpy as np

# La raíz del repositorio queda un nivel por encima de esta carpeta
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from nucleo.calidad_video import (calidad, ordenar_cuadro, cuadro_seguro, cuadro_envolvente,
                                  enderezar, movimiento_compensado, planitud, detectar_lomo,
                                  desdoblar, limpiar_iluminacion, tinta_de, VERSION)
with open(RAIZ / 'config.json') as f:
    CONFIG = json.load(f).get('Video', {})

EXTENSIONES_VIDEO = ('.mp4', '.mov', '.m4v', '.avi', '.mkv', '.webm')
IDIOMAS_VISION = {'es': 'es-ES', 'en': 'en-US', 'fr': 'fr-FR', 'it': 'it-IT', 'pt': 'pt-BR', 'de': 'de-DE'}
ROTACIONES = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}

# Command line arguments setup. The defaults come from config.json so the same
# camera set-up can be tuned once and reused
parser = argparse.ArgumentParser(
    description='Turn a video of a book, recorded with a phone while the pages are turned by hand, '
                'into one image per page (pag_N.png), ready for the OCR step.')
parser.add_argument('--f', dest='videos', required=True, nargs='+',
                    help='Video file(s) or folder(s) of videos, all of the same book. A phone that records in 4K '
                         'cuts every ten minutes: give every segment and the pages come out in order, without repeats.')
parser.add_argument('--orden', dest='orden', choices=['nombre', 'fecha'], default='nombre',
                    help='How several videos are ordered: by file name (a phone numbers them in order) or by date.')
parser.add_argument('--o', dest='folder_output', required=True, help='Folder to save the page images.')
parser.add_argument('--fps', dest='fps', type=float, default=CONFIG.get('fps_muestreo', 4),
                    help='Frames analysed per second of video. 4 is enough to tell a resting page from a turning one.')
parser.add_argument('--quietud', dest='quietud', type=float, default=CONFIG.get('quietud_s', 0.8),
                    help='Seconds a page must rest between two turns to count as a page.')
parser.add_argument('--umbral', dest='umbral', type=float, default=CONFIG.get('umbral_movimiento', 2.5),
                    help='Minimum motion (mean pixel change, 0-255, after aligning consecutive frames) that counts as a '
                         'page turn. The real threshold is the larger of this and --factor times the median motion, '
                         'so a hand-held camera raises it by itself.')
parser.add_argument('--factor', dest='factor', type=float, default=CONFIG.get('factor_movimiento', 1.4),
                    help='A turn must move at least this many times the median motion of the whole video. Low on '
                         'purpose: a rest cut in two is merged back later, a turn missed loses a page.')
parser.add_argument('--similitud', dest='similitud', type=float, default=CONFIG.get('similitud_minima', 0.45),
                    help='Share of the read text (character 4-grams, 0-1) two consecutive stills must have in common '
                         'to be the same page and get merged. Without Vision, the image correlation is used instead.')
parser.add_argument('--idioma', dest='idioma', default='es', choices=sorted(IDIOMAS_VISION),
                    help='Language of the book, guides the reading used to compare stills.')
parser.add_argument('--capturas', dest='capturas', type=int, default=CONFIG.get('capturas_por_pagina', 5),
                    help='Captures per resting page. Occlusions are replaced only with a reliably aligned complete patch.')
parser.add_argument('--doble', dest='doble', action='store_true',
                    help='The video shows the open book: every still is split into a left and a right page.')
parser.add_argument('--recorte', dest='recorte', choices=['auto', 'no'], default=CONFIG.get('recorte', 'auto'),
                    help='auto: find the page in the frame and straighten it (Vision on macOS, a brightness heuristic '
                         'elsewhere). no: keep the whole frame.')
parser.add_argument('--rotar', dest='rotar', choices=['auto', '0', '90', '180', '270'], default='auto',
                    help='Clockwise degrees to turn the pages so the text reads upright. auto asks Vision on macOS.')
parser.add_argument('--guardar-capturas', dest='guardar_capturas', action='store_true',
                    help='Also keep every capture of each page, cropped, turned and split like the final page, in '
                         'capturas/pag_N/cap_K.png: the multi-frame OCR reads each one and keeps the best reading of every line.')
parser.add_argument('--brutos', dest='brutos', action='store_true',
                    help='Keep the uncropped stills in a brutos/ subfolder, to check what the detector picked.')
args = None  # Se configura únicamente al ejecutar el programa.


# Function to reduce a frame to a small grey image, which is all the motion
# and similarity measures need and keeps the whole pass cheap
def miniatura(frame, ancho):
    alto = max(1, round(frame.shape[0] * ancho / frame.shape[1]))
    return cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (ancho, alto), interpolation=cv2.INTER_AREA)


# Calidad multibloque con gradientes a mayor resolución y reducción de ruido.
def nitidez(frame):
    return calidad(frame)


# Compensa el movimiento de cámara y la exposición antes de buscar pasos de hoja.
def movimiento(anterior, actual):
    return movimiento_compensado(anterior, actual)


# Function to tell how alike two page images are (0-1), tolerant to a few pixels
# of misalignment: the central part of one is searched inside the other. Used
# for pages with too little text to compare by words, and off macOS
def similitud(a, b):
    a = cv2.GaussianBlur(miniatura(a, 480), (3, 3), 0)
    b = cv2.GaussianBlur(cv2.resize(cv2.cvtColor(b, cv2.COLOR_BGR2GRAY), (a.shape[1], a.shape[0])), (3, 3), 0)
    if min(float(a.std()), float(b.std())) < 3 or a.shape[0] < 12:
        return 0.0
    margen_y, margen_x = max(1, a.shape[0] // 10), max(1, a.shape[1] // 10)
    plantilla = b[margen_y:-margen_y, margen_x:-margen_x]
    return float(cv2.matchTemplate(a, plantilla, cv2.TM_CCOEFF_NORMED).max())


# Function to order four corners as top-left, top-right, bottom-right, bottom-left
def ordenar_esquinas(puntos):
    return ordenar_cuadro(puntos)


# Function to find the page inside a frame without Vision: the largest bright
# region, taken as a quadrilateral. Good enough on a dark, plain background
def detectar_pagina_heuristica(frame):
    escala = 640 / frame.shape[1]
    gris = cv2.GaussianBlur(miniatura(frame, 640), (5, 5), 0)
    _, binaria = cv2.threshold(gris, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    binaria = cv2.morphologyEx(binaria, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    contornos, _ = cv2.findContours(binaria, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contornos:
        return None
    contorno = max(contornos, key=cv2.contourArea)
    area = cv2.contourArea(contorno) / (gris.shape[0] * gris.shape[1])
    if not 0.12 <= area <= 0.98:
        return None
    aproximado = cv2.approxPolyDP(contorno, 0.02 * cv2.arcLength(contorno, True), True)
    if len(aproximado) != 4:
        aproximado = cv2.boxPoints(cv2.minAreaRect(contorno))
    return ordenar_esquinas(aproximado) / escala


# Function to run the Swift helper that asks Vision (the same document detector
# Notes uses to scan a paper) where the page is in each still
def detectar_paginas_vision(rutas):
    comando = ['swift', str(RAIZ / 'pasos' / 'vision_pagina.swift'), 'cuadro'] + [str(r) for r in rutas]
    salida = subprocess.run(comando, capture_output=True, text=True, timeout=3600)
    if salida.returncode != 0:
        print(f'  El ayudante de Vision falló: {salida.stderr.strip()[:300]}', flush=True)
        return {}
    esquinas, actual = {}, None
    for linea in salida.stdout.split('\n'):
        if linea.startswith('###FILE:'):
            actual = linea[len('###FILE:'):]
        elif linea.startswith('###ERROR:') or actual is None or not linea.strip():
            continue
        else:
            esquinas[actual] = ordenar_esquinas([float(v) for v in linea.split()])
    return esquinas


# Function to read every candidate page with Vision (the accurate reader, the
# same one the OCR step uses) and return the text of each. Two stills of the
# same page share most of their text even with a hand over part of them, and
# the still where more words were read is the cleanest one
def palabras_vision(rutas):
    palabras = {str(r): '' for r in rutas}
    for inicio in range(0, len(rutas), 200):
        comando = ['swift', str(RAIZ / 'pasos' / 'vision_ocr.swift'), f'{IDIOMAS_VISION[args.idioma]},en-US'] \
                  + [str(r) for r in rutas[inicio:inicio + 200]]
        salida = subprocess.run(comando, capture_output=True, text=True, timeout=3600)
        actual = None
        for linea in salida.stdout.split('\n'):
            if linea.startswith('###FILE:'):
                actual = linea[len('###FILE:'):]
            elif actual is not None and not linea.startswith('###'):
                palabras[actual] += linea.lower() + ' '
    return palabras


# Function to reduce a text to its character 4-grams. At video resolution the
# reader misreads many words, and the same page read twice shares only half
# of its whole words, but most of its 4-grams; different pages share few
def cuatrigramas(texto):
    texto = re.sub(r'\s+', ' ', texto)
    return {texto[i:i + 4] for i in range(len(texto) - 3)}


# Function to ask Vision how many clockwise degrees the pages need so the text
# reads upright, judged on the image where it recognises the most text
def orientacion_vision(rutas):
    comando = ['swift', str(RAIZ / 'pasos' / 'vision_pagina.swift'), 'orientacion'] + [str(r) for r in rutas]
    salida = subprocess.run(comando, capture_output=True, text=True, timeout=600)
    try:
        return int(salida.stdout.strip().split('\n')[-1])
    except ValueError:
        print(f'  No se pudo determinar la orientación: {salida.stderr.strip()[:200]}', flush=True)
        return 0


# Admite perspectiva oblicua sin aceptar cuadriláteros degenerados.
def cuadro_valido(esquinas, referencia=None):
    if not cuadro_seguro(esquinas):
        return False
    if referencia is not None:
        area = cv2.contourArea(esquinas.reshape(-1, 1, 2))
        return 0.4 <= area / max(referencia, 1) <= 2.5
    return True


# Rectificación proyectiva a la resolución de cada toma.
def recortar(frame, esquinas, tamano):
    ancho, alto = tamano
    destino = np.array([[0, 0], [ancho - 1, 0], [ancho - 1, alto - 1], [0, alto - 1]], dtype=np.float32)
    return cv2.warpPerspective(frame, cv2.getPerspectiveTransform(esquinas, destino), (ancho, alto),
                               flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))


# Function to walk the video once, cheaply, measuring motion and sharpness on
# every analysed frame. Nothing but small numbers is kept in memory
def medir_video(video):
    captura = cv2.VideoCapture(str(video))
    if not captura.isOpened():
        raise SystemExit(f'No se pudo abrir el vídeo: {video}')
    fps_video = captura.get(cv2.CAP_PROP_FPS) or 30
    total = int(captura.get(cv2.CAP_PROP_FRAME_COUNT))
    paso = max(1, round(fps_video / args.fps))
    print(f'{video.name}: {total / fps_video:.0f} s a {fps_video:.0f} fps, analizando 1 de cada {paso} fotogramas', flush=True)

    medidas = []        # [(índice, segundo, movimiento, nitidez)]
    previa = None
    indice = -1
    while captura.grab():
        indice += 1
        if indice % paso:
            continue
        ok, frame = captura.retrieve()
        if not ok:
            break
        # miniatura pequeña y desenfocada: un autoenfoque momentáneo no debe leerse como movimiento
        mini = cv2.GaussianBlur(miniatura(frame, 320), (3, 3), 0).astype(np.float32)
        mov = movimiento(previa, mini) if previa is not None else 0.0
        previa = mini
        medidas.append((indice, indice / fps_video, mov, nitidez(frame)))
        if len(medidas) % 50 == 0:
            print(f'  {indice / fps_video:6.0f} s analizados', flush=True)
    captura.release()
    return medidas


# Function to split the measured frames into rests separated by page turns and
# pick, in each rest, the frames worth reading: the sharpest of its calmest
# ones first, then a few more spread over the rest, so that the hand holding
# the page is caught in different places and can be averaged away
def elegir_fotogramas(medidas):
    movimientos = np.array([m[2] for m in medidas[1:]]) if len(medidas) > 1 else np.array([0.0])
    umbral = max(args.umbral, args.factor * float(np.median(movimientos)))
    print(f'Movimiento mediano {np.median(movimientos):.1f}, umbral de paso de página {umbral:.1f}', flush=True)

    # un autoenfoque momentáneo también supera el umbral, pero dura uno o dos
    # fotogramas analizados y en ellos la nitidez se desploma respecto a los de
    # alrededor; una pasada de hoja dura más. Esos picos no cortan el reposo
    moviendose = [m[2] > umbral for m in medidas]
    inicio_pico = None
    for i, mueve in enumerate(moviendose + [False]):
        if mueve and inicio_pico is None:
            inicio_pico = i
        elif not mueve and inicio_pico is not None:
            # basta con que un fotograma del pico esté desenfocado: el siguiente ya
            # vuelve a estar nítido y su movimiento es solo la salida del desenfoque
            entorno = [m[3] for m in medidas[max(0, inicio_pico - 3):inicio_pico] + medidas[i:i + 3]]
            if i - inicio_pico <= 2 and entorno and min(m[3] for m in medidas[inicio_pico:i]) < 0.5 * float(np.median(entorno)):
                for j in range(inicio_pico, i):
                    moviendose[j] = False
            inicio_pico = None

    # un reajuste breve del pulgar sobre la página quieta (<= 2 fotogramas de
    # movimiento moderado y nitidez estable) no debe malograr un reposo partiéndolo
    # en trozos menores que --quietud
    corridas = []
    inicio_c = 0
    for i in range(1, len(medidas) + 1):
        if i == len(medidas) or moviendose[i] != moviendose[inicio_c]:
            corridas.append([moviendose[inicio_c], inicio_c, i])
            inicio_c = i
    for k in range(1, len(corridas) - 1):
        mueve, ini, fin = corridas[k]
        if not mueve or fin - ini > 2:
            continue
        ant_m, ant_i, ant_f = corridas[k - 1]
        sig_m, sig_i, sig_f = corridas[k + 1]
        if ant_m or sig_m:
            continue
        dur_ant = medidas[ant_f - 1][1] - medidas[ant_i][1]
        dur_sig = medidas[sig_f - 1][1] - medidas[sig_i][1]
        dur_total = medidas[sig_f - 1][1] - medidas[ant_i][1]
        entorno = [m[3] for m in medidas[max(0, ini - 3):ini] + medidas[fin:min(len(medidas), fin + 3)]]
        pico_mov = max(m[2] for m in medidas[ini:fin])
        min_nit = min(m[3] for m in medidas[ini:fin])
        if (min(dur_ant, dur_sig) < args.quietud and dur_total >= args.quietud
                and pico_mov < 2.2 * umbral and entorno and min_nit >= 0.65 * float(np.median(entorno))):
            for j in range(ini, fin):
                moviendose[j] = False
            corridas[k + 1][1] = ant_i

    tramos, actual, cortos = [], [], 0
    for medida, mueve in zip(medidas, moviendose):
        if mueve:
            if actual:
                if actual[-1][1] - actual[0][1] >= args.quietud:
                    tramos.append(actual)
                else:
                    cortos += 1
            actual = []
        else:
            actual.append(medida)
    if actual and actual[-1][1] - actual[0][1] >= args.quietud:
        tramos.append(actual)

    elegidos = []
    posiciones = {m[0]: i for i, m in enumerate(medidas)}
    for tramo in tramos:
        calmados = sorted(tramo, key=lambda m: m[2])[:max(1, len(tramo) // 2)]
        mejor = max(calmados, key=lambda m: m[3])
        indices = [mejor[0]]
        for posicion in np.linspace(0, len(tramo) - 1, min(args.capturas, len(tramo))):
            candidato = tramo[int(round(posicion))][0]
            if candidato not in indices:
                indices.append(candidato)
        # y unas capturas más justo antes y después del reposo, cuando la mano se
        # está apartando o llegando: ahí suele verse la página que tapaba. Una
        # captura de fuera solo parchea si se alinea y coincide con la referencia
        primero, ultimo = posiciones[tramo[0][0]], posiciones[tramo[-1][0]]
        for vecino in (primero - 1, primero - 2, ultimo + 1, ultimo + 2):
            if 0 <= vecino < len(medidas) and medidas[vecino][0] not in indices:
                indices.append(medidas[vecino][0])
        elegidos.append({'indices': indices, 'inicio': tramo[0][1], 'fin': tramo[-1][1]})
    print(f'{len(tramos)} tramos de página quieta ({cortos} demasiado breves descartados)', flush=True)
    return elegidos


# Function to read back the chosen frames at full resolution and leave them on
# disk, where Vision reads them and where the user can check them
def leer_fotogramas(video, tomas, carpeta_brutos, desde=1):
    captura = cv2.VideoCapture(str(video))
    for numero, toma in enumerate(tomas, desde):
        toma['rutas'] = []
        for k, indice in enumerate(toma['indices']):
            captura.set(cv2.CAP_PROP_POS_FRAMES, indice)
            ok, frame = captura.read()
            if not ok:
                continue
            ruta = carpeta_brutos / (f'toma_{numero}.png' if k == 0 else f'toma_{numero}_{k}.png')
            cv2.imwrite(str(ruta), frame)
            toma['rutas'].append(ruta)
        if not toma['rutas']:
            raise SystemExit(f'No se pudo leer ningún fotograma de la toma {numero}')
    captura.release()


# Function to mark the skin in a frame (YCrCb + HSV thresholds while excluding
# bright low-saturation paper): the hand holding the page is the intruder to erase
def mascara_piel(imagen):
    ycrcb = cv2.cvtColor(imagen, cv2.COLOR_BGR2YCrCb)
    hsv = cv2.cvtColor(imagen, cv2.COLOR_BGR2HSV)
    piel_y = cv2.inRange(ycrcb, (0, 133, 77), (255, 180, 135))
    piel_h = cv2.inRange(hsv, (0, 28, 45), (25, 230, 255))
    papel = (hsv[..., 1] < 32) & (ycrcb[..., 0] > 175)
    piel = cv2.bitwise_and(piel_y, piel_h)
    piel[papel] = 0
    piel = cv2.morphologyEx(piel, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8))
    return cv2.dilate(piel, np.ones((25, 25), np.uint8))


# Fracción de piel en el interior de la página (excluyendo el borde exterior,
# donde un dedo sujetando el margen no tapa texto).
def piel_interior(imagen):
    piel = mascara_piel(imagen) > 0
    h, w = piel.shape
    my, mx = max(1, int(0.08 * h)), max(1, int(0.08 * w))
    interior = piel[my:h - my, mx:w - mx]
    return float(interior.mean()) if interior.size else 0.0


# Planitud evaluada en la orientación dominante del texto (horizontal o vertical),
# para funcionar igual de bien antes de que enderezar_tomas gire el vídeo.
def planitud_orientada(imagen):
    p_h = planitud(imagen)
    p_v = planitud(cv2.rotate(imagen, cv2.ROTATE_90_CLOCKWISE))
    return max(p_h, p_v)


# Function to find the coarse alignment between two windows with SIFT points
# matched and filtered by RANSAC: on lines of text, which repeat, a plain
# correlation lands one line off with ease, but words are distinctive
def emparejar_sift(a, b, mascara):
    sift = cv2.SIFT_create(nfeatures=1500)
    puntos_a, desc_a = sift.detectAndCompute(a.astype(np.uint8), mascara)
    puntos_b, desc_b = sift.detectAndCompute(b.astype(np.uint8), None)
    if desc_a is None or desc_b is None or len(puntos_a) < 8 or len(puntos_b) < 8:
        return None
    parejas = cv2.BFMatcher(cv2.NORM_L2).knnMatch(desc_a, desc_b, k=2)
    buenas = [m for m, n in (p for p in parejas if len(p) == 2) if m.distance < 0.75 * n.distance]
    if len(buenas) < 8:
        return None
    origen = np.float32([puntos_a[m.queryIdx].pt for m in buenas])
    destino = np.float32([puntos_b[m.trainIdx].pt for m in buenas])
    matriz, aceptados = cv2.estimateAffinePartial2D(origen, destino, method=cv2.RANSAC, ransacReprojThreshold=3)
    if matriz is None or aceptados.sum() < 8:
        return None
    return matriz.astype(np.float32)


# Function to align a small window of one capture onto the same window of the
# reference: SIFT for the coarse step, ECC (affine, two scales, on the pixels
# around the hand that are page in both) for the fine one. The page is curved,
# so a global alignment never fits everywhere, but a window a few hundred
# pixels wide is flat enough. Returns the aligned window and how well its ring
# around the hand matches the reference's
def alinear_ventana(referencia, captura, ventana, anillo):
    y0, y1, x0, x1 = ventana
    a = cv2.cvtColor(referencia[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.float32)
    b = cv2.cvtColor(captura[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.float32)
    mascara = anillo[y0:y1, x0:x1].astype(np.uint8)
    matriz = emparejar_sift(a, b, mascara)
    if matriz is None:
        return None, 0.0
    try:
        for escala in (0.5, 1.0):
            a_e = cv2.resize(a, None, fx=escala, fy=escala) if escala != 1 else a
            b_e = cv2.resize(b, None, fx=escala, fy=escala) if escala != 1 else b
            m_e = cv2.resize(mascara, (a_e.shape[1], a_e.shape[0]), interpolation=cv2.INTER_NEAREST)
            matriz[:, 2] *= escala if escala != 1 else 1
            cv2.findTransformECC(a_e, b_e, matriz, cv2.MOTION_AFFINE,
                                 (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 80, 1e-5), m_e, 5)
            if escala != 1:
                matriz[:, 2] /= escala
    except cv2.error:
        return None, 0.0
    alineada = cv2.warpAffine(captura[y0:y1, x0:x1], matriz, (x1 - x0, y1 - y0),
                              flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REPLICATE)
    b_alineada = cv2.cvtColor(alineada, cv2.COLOR_BGR2GRAY).astype(np.float32)
    libre = (mascara > 0) & (mascara_piel(alineada) == 0)
    if libre.sum() < 500:
        return None, 0.0
    # la coincidencia se mide algo desenfocada, para tolerar el resto de subpíxel
    a_s, b_s = cv2.GaussianBlur(a, (0, 0), 1.5)[libre], cv2.GaussianBlur(b_alineada, (0, 0), 1.5)[libre]
    if a_s.std() < 1 or b_s.std() < 1:
        return None, 0.0
    return alineada, float(np.corrcoef(a_s, b_s)[0, 1])


# Fusiona las capturas de una página simple (o de una mitad de doble página).
def _fusionar_hoja(capturas):
    # la referencia es la captura más nítida y limpia de mano entre las que tienen
    # las líneas rectas: una hoja levantada a mitad de vuelta está girada, y una
    # con el pulgar dentro del texto obliga a parchear cuando otra captura ya está limpia
    if len(capturas) > 1:
        planitudes = [planitud_orientada(c) for c in capturas]
        tope_p = max(planitudes)
        planas = [c for c, p in zip(capturas, planitudes) if p >= 0.82 * tope_p]
        capturas = (sorted(planas, key=lambda c: nitidez(c) * (1.0 - min(0.45, 2.5 * piel_interior(c))), reverse=True)
                    + [c for c in capturas if not any(c is q for q in planas)])
    referencia = capturas[0]
    piel = mascara_piel(referencia)
    if len(capturas) == 1 or not piel.any():
        return referencia, 0.0
    resultado = referencia.copy()
    reemplazados = 0
    alto, ancho = piel.shape
    # columna de texto de la referencia (tinta fuera de la piel): los dedos
    # sujetan el borde de la hoja, fuera de la columna, y allí un parche solo
    # puede ser papel. Si trae texto es que el donante se alineó sobre la mesa y
    # no sobre la página, y pegaría los finales de línea una segunda vez
    # solo cuentan las manchas del tamaño de una letra (tinta_de descarta la mesa,
    # las sombras y los dedos, que son grandes), y la caja se toma entre los
    # percentiles 2 y 98 para que un resto suelto no la ensanche. La fusión ocurre
    # antes de girar el texto, así que la caja se mide en los dos ejes
    tinta_ref = (tinta_de(referencia, ancho=ancho) > 0) & (piel == 0)
    ys_tinta, xs_tinta = np.nonzero(tinta_ref)
    columna = ((int(np.percentile(xs_tinta, 2)), int(np.percentile(xs_tinta, 98)),
                int(np.percentile(ys_tinta, 2)), int(np.percentile(ys_tinta, 98))) if len(xs_tinta) > 500 else None)
    cuantas, etiquetas, cajas, _ = cv2.connectedComponentsWithStats(piel)
    for etiqueta in range(1, cuantas):
        x, y, w, h, area = cajas[etiqueta]
        if area < 400:
            continue
        margen = 120
        ventana = (max(0, y - margen), min(alto, y + h + margen), max(0, x - margen), min(ancho, x + w + margen))
        mancha = etiquetas == etiqueta
        anillo = (piel == 0)
        donantes = []
        for captura in capturas[1:]:
            alineada, coincidencia = alinear_ventana(referencia, captura, ventana, anillo)
            if alineada is None or coincidencia < 0.58:
                continue
            piel_captura = mascara_piel(alineada) > 0
            donantes.append((coincidencia, nitidez(alineada), alineada.astype(np.float32), piel_captura))
        # un parche equivocado (texto desalineado) es peor que la mano: hace falta
        # que dos donantes coincidan, o uno solo que coincida muy bien
        if not donantes or (len(donantes) == 1 and donantes[0][0] < 0.8):
            continue
        # se ordenan los donantes de mejor a peor (coincidencia y nitidez) y cada píxel
        # se toma del mejor donante libre de piel, evitando promediar textos con 1-2 px de desfase
        donantes.sort(key=lambda d: (round(d[0], 2), d[1]), reverse=True)
        y0, y1, x0, x1 = ventana
        # la coincidencia del anillo no basta: dos donantes alineados sobre el fondo
        # de la mesa y no sobre el texto pegan el mismo renglón dos veces. Dentro de
        # la mancha los donantes tienen que parecerse entre sí; si no, se deja la mano
        if len(donantes) >= 2:
            zona = mancha[y0:y1, x0:x1] & ~donantes[0][3] & ~donantes[1][3]
            if zona.sum() >= 200:
                g0 = cv2.cvtColor(donantes[0][2].astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float32)[zona]
                g1 = cv2.cvtColor(donantes[1][2].astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float32)[zona]
                if g0.std() > 1 and g1.std() > 1 and np.corrcoef(g0, g1)[0, 1] < 0.6:
                    continue
        parche = np.full((y1 - y0, x1 - x0, 3), np.nan, dtype=np.float32)
        for _, _, img_d, piel_d in donantes:
            falta = np.isnan(parche[..., 0]) & ~piel_d
            parche[falta] = img_d[falta]
        mancha_ventana = mancha[y0:y1, x0:x1] & ~np.isnan(parche[..., 0])
        if not mancha_ventana.any():
            continue
        if columna is not None:
            # el recorte de la toma envuelve todas sus capturas, así que junto al borde
            # de la hoja hay zona que en unas capturas es página y en otras es mesa: ahí,
            # fuera de la columna de texto, un donante con tinta pegaría los finales de
            # línea otra vez. Esos píxeles no se parchean; el resto de la mancha sí
            xs, ys = np.arange(x0, x1)[None, :], np.arange(y0, y1)[:, None]
            fuera = (xs < columna[0] - 12) | (xs > columna[1] + 12) | (ys < columna[2] - 12) | (ys > columna[3] + 12)
            gris_parche = cv2.cvtColor(np.nan_to_num(parche, nan=255).astype(np.uint8), cv2.COLOR_BGR2GRAY)
            tinta_parche = cv2.dilate(((gris_parche < 140) & fuera).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
            mancha_ventana = mancha_ventana & ~tinta_parche
            if not mancha_ventana.any():
                continue
        alfa = cv2.GaussianBlur(mancha_ventana.astype(np.float32), (9, 9), 2.0)[..., None]
        alfa = np.where(mancha_ventana[..., None], np.maximum(alfa, 0.85), 0.0)
        destino = resultado[y0:y1, x0:x1].astype(np.float32)
        relleno = np.where(np.isnan(parche), destino, parche)
        resultado[y0:y1, x0:x1] = np.clip(alfa * relleno + (1.0 - alfa) * destino, 0, 255).astype(np.uint8)
        reemplazados += int(mancha_ventana.sum())
    return resultado, reemplazados / float((piel > 0).sum())


# Function to merge the captures of one page (or of each half independently when
# --doble is active, since in an open book one page often finishes settling a
# fraction of a second after the other).
def fusionar(capturas):
    if not capturas:
        return None, 0.0
    if len(capturas) > 1 and getattr(args, 'doble', False):
        h, w = capturas[0].shape[:2]
        if w >= h:
            m = w // 2
            izq, p_izq = _fusionar_hoja([c[:, :m] for c in capturas])
            der, p_der = _fusionar_hoja([c[:, m:] for c in capturas])
            return np.hstack([izq, der]), 0.5 * (p_izq + p_der)
        m = h // 2
        sup, p_sup = _fusionar_hoja([c[:m, :] for c in capturas])
        inf, p_inf = _fusionar_hoja([c[m:, :] for c in capturas])
        return np.vstack([sup, inf]), 0.5 * (p_sup + p_inf)
    return _fusionar_hoja(capturas)


# Function to find the page in every capture and cut it out. On macOS it is
# Vision who finds it; elsewhere a brightness heuristic. Each capture gets its
# own corners, since the phone may be hand-held, all pages share one size, and
# the captures of a rest are aligned and merged into one clean page
def recortar_tomas(tomas):
    if getattr(args, 'recorte', 'auto') == 'no':
        for numero, toma in enumerate(tomas, 1):
            guardar_candidata(toma, numero, *fusionar([cv2.imread(str(r)) for r in toma['rutas']]))
            toma['capturas'] = len(toma['rutas'])
        return
    rutas = [r for t in tomas for r in t['rutas']]
    forma_frame = None
    if rutas:
        muestra = cv2.imread(str(rutas[0]))
        if muestra is not None:
            forma_frame = muestra.shape[:2]
    if sys.platform == 'darwin':
        encontradas = detectar_paginas_vision(rutas)
        origen = 'Vision'
    else:
        encontradas = {str(r): detectar_pagina_heuristica(cv2.imread(str(r))) for r in rutas}
        origen = 'la heurística de brillo'
    # primero se descartan las esquinas con forma imposible, luego las de tamaño
    # discordante con la mediana de las demás
    esquinas = {r: e for r, e in encontradas.items() if e is not None and cuadro_valido(e)}
    if esquinas:
        area_tipica = float(np.median([cv2.contourArea(e.reshape(-1, 1, 2)) for e in esquinas.values()]))
        esquinas = {r: e for r, e in esquinas.items() if cuadro_valido(e, area_tipica)}
    for toma in tomas:
        validas = [esquinas[str(r)] for r in toma['rutas'] if str(r) in esquinas]
        toma['validas'] = validas
        toma['esquinas'] = cuadro_envolvente(validas, forma=forma_frame) if validas else None
        toma['recorte_fiable'] = bool(validas)
    con_pagina = [t for t in tomas if t['esquinas'] is not None]
    if len(con_pagina) < max(1, len(tomas) // 3):
        print(f'{origen} solo localizó la página en {len(con_pagina)} de {len(tomas)} tomas: se guardan enteras', flush=True)
        for numero, toma in enumerate(tomas, 1):
            toma['recorte_fiable'] = False
            guardar_candidata(toma, numero, *fusionar([cv2.imread(str(r)) for r in toma['rutas']]))
            toma['capturas'] = len(toma['rutas'])
        return

    # si en toda una toma el pulgar empujó hacia dentro una esquina, las tomas
    # vecinas (con la cámara en el mismo sitio) permiten restituir esa esquina
    for i, toma in enumerate(tomas):
        if toma['esquinas'] is None:
            continue
        vecinas = [tomas[j]['esquinas'] for j in range(max(0, i - 2), min(len(tomas), i + 3))
                   if j != i and tomas[j].get('esquinas') is not None]
        if vecinas:
            toma['esquinas'] = cuadro_envolvente(toma['validas'] + vecinas[:2], forma=forma_frame)

    # una toma sin página fiable (la mano o una hoja levantada tapándola) hereda
    # las esquinas de la toma válida más cercana en el tiempo: la cámara apenas
    # se mueve entre dos tomas seguidas, y un fotograma entero es inservible
    indices_validos = [i for i, t in enumerate(tomas) if t['esquinas'] is not None]
    for i, toma in enumerate(tomas):
        if toma['esquinas'] is None:
            vecina = min(indices_validos, key=lambda j: abs(j - i))
            toma['esquinas'] = tomas[vecina]['esquinas']
            print(f'  toma {i + 1}: página mal localizada, se recorta como la toma {vecina + 1}', flush=True)
    # todas las páginas del libro salen con el mismo tamaño, el mediano
    anchos = [max(np.linalg.norm(e[1] - e[0]), np.linalg.norm(e[2] - e[3])) for e in (t['esquinas'] for t in tomas)]
    altos = [max(np.linalg.norm(e[3] - e[0]), np.linalg.norm(e[2] - e[1])) for e in (t['esquinas'] for t in tomas)]
    tamano = (int(np.median(anchos)), int(np.median(altos)))
    print(f'Página localizada con {origen} en {len(con_pagina)} de {len(tomas)} tomas; se recorta a {tamano[0]}x{tamano[1]}', flush=True)

    for numero, toma in enumerate(tomas, 1):
        capturas = []
        for ruta in toma['rutas']:
            # si la esquina individual de una captura fue encogida por un dedo respecto
            # al cuadro envolvente de la toma, se usa el cuadro envolvente para no cortar líneas
            propia = esquinas.get(str(ruta))
            if propia is not None:
                propia = cuadro_envolvente([propia, toma['esquinas']], forma=forma_frame, margen=0.0)
            capturas.append(recortar(cv2.imread(str(ruta)), propia if propia is not None else toma['esquinas'], tamano))
        if getattr(args, 'guardar_capturas', False):
            toma['rutas_capturas'] = []
            for k, captura in enumerate(capturas, 1):
                ruta_captura = CARPETA_CANDIDATAS / f'captura_{numero}_{k}.png'
                cv2.imwrite(str(ruta_captura), captura)
                toma['rutas_capturas'].append(ruta_captura)
        guardar_candidata(toma, numero, *fusionar(capturas))
        toma['capturas'] = len(capturas)
        if numero % 25 == 0:
            print(f'  {numero} de {len(tomas)} tomas recortadas y fusionadas', flush=True)


# Function to keep the merged page of a still on disk instead of in memory: a
# 4K page weighs 17 MB and a whole book would not fit
CARPETA_CANDIDATAS = None


def guardar_candidata(toma, numero, imagen, parcheado):
    toma['ruta_imagen'] = CARPETA_CANDIDATAS / f'candidata_{numero}.png'
    toma['parcheado'] = parcheado
    cv2.imwrite(str(toma['ruta_imagen']), imagen)


def cargar(toma):
    return cv2.imread(str(toma['ruta_imagen']))


# Function to straighten a page by the angle of its text lines: the corners
# fix the page outline, but the lines still lean a little with the curve of
# the book, and the angle that makes the row profile sharpest is the fix
def enderezar_texto(imagen):
    return enderezar(imagen)


# Function to turn every page so the text reads upright
def enderezar_tomas(tomas):
    rotar_arg = getattr(args, 'rotar', 'auto')
    if rotar_arg != 'auto':
        grados = int(rotar_arg)
    elif sys.platform == 'darwin':
        # se juzga sobre tres tomas repartidas, no vaya a caer la única en una página vacía
        indices = sorted({len(tomas) // 4, len(tomas) // 2, (3 * len(tomas)) // 4})
        grados = orientacion_vision([tomas[indice]['ruta_imagen'] for indice in indices])
        print(f'Orientación del texto: giro de {grados}° en sentido horario', flush=True)
    else:
        grados = 0
    if grados:
        for toma in tomas:
            cv2.imwrite(str(toma['ruta_imagen']), cv2.rotate(cargar(toma), ROTACIONES[grados]))
            for ruta_captura in toma.get('rutas_capturas', []):
                cv2.imwrite(str(ruta_captura), cv2.rotate(cv2.imread(str(ruta_captura)), ROTACIONES[grados]))


# Descarta tomas espurias (mesa vacía al principio o al final, o giro puro sin página)
# donde no se localizó una página fiable y apenas hay texto ni nitidez.
def depurar_tomas(tomas):
    if len(tomas) <= 1:
        return tomas
    nitideces = [nitidez(cargar(t)) for t in tomas]
    mediana_nit = float(np.median(nitideces)) if nitideces else 0.0
    limpias = []
    for toma, nit in zip(tomas, nitideces):
        sin_texto = len(toma.get('palabras', ())) < 3 and len(toma.get('texto', '').strip()) < 15
        if not toma.get('recorte_fiable', True) and sin_texto and nit < 0.45 * mediana_nit:
            print(f'  {momento(toma)}: descartada por falta de página y texto', flush=True)
            continue
        limpias.append(toma)
    return limpias or tomas


# Function to merge consecutive stills that show the same page (the same page
# with and without the hand, or a rest split by a false turn). On macOS the
# pages are read and compared by their words, keeping the still where more
# words were read; pages with little text, and other systems, compare images
def fundir_repetidas(tomas):
    if sys.platform == 'darwin':
        leidas = palabras_vision([t['ruta_imagen'] for t in tomas])
        for toma in tomas:
            texto = leidas[str(toma['ruta_imagen'])]
            toma['texto'] = texto
            toma['palabras'] = set(re.findall(r'\w{3,}', texto))
            toma['palabras_largas'] = set(re.findall(r'[a-záéíóúüñ]{5,}', texto.lower()))
            toma['trozos'] = cuatrigramas(texto)
    else:
        for toma in tomas:
            toma['palabras'], toma['palabras_largas'], toma['trozos'] = set(), set(), set()

    tomas = depurar_tomas(tomas)
    umbral_sim = getattr(args, 'similitud', 0.45)

    # contención (sobre el conjunto menor), protegida frente a páginas cortas de fin
    # de capítulo cuyos cuatrigramas comunes cabrían por azar en una página llena
    def misma_pagina(a, b):
        na, nb = len(a['palabras']), len(b['palabras'])
        if min(na, nb) >= 15 and a['trozos'] and b['trozos']:
            ta, tb = len(a['trozos']), len(b['trozos'])
            proporcion = min(ta, tb) / max(ta, tb)
            cont_trozos = len(a['trozos'] & b['trozos']) / min(ta, tb)
            la, lb = a.get('palabras_largas', set()), b.get('palabras_largas', set())
            cont_largas = len(la & lb) / min(len(la), len(lb)) if min(len(la), len(lb)) >= 5 else cont_trozos
            if proporcion < 0.28:
                return cont_trozos >= max(0.72, umbral_sim) and cont_largas >= 0.6 and similitud(cargar(a), cargar(b)) >= 0.55
            return cont_trozos >= umbral_sim and cont_largas >= max(0.30, 0.7 * umbral_sim)
        return similitud(cargar(a), cargar(b)) >= 0.6

    def preferir(anterior, nueva):
        mejor = (len(nueva['palabras']), nueva.get('fin', 0) - nueva.get('inicio', 0)) > (
            len(anterior['palabras']), anterior.get('fin', 0) - anterior.get('inicio', 0))
        ganadora, otra = (nueva, anterior) if mejor else (anterior, nueva)
        # si la toma ganadora aún conserva piel visible, la otra toma de la misma
        # página sirve como donante adicional para terminar de borrar la mano
        if ganadora.get('ruta_imagen') and otra.get('ruta_imagen'):
            img_g = cargar(ganadora)
            if img_g is not None and (mascara_piel(img_g) > 0).any():
                img_o = cargar(otra)
                if img_o is not None and img_o.shape == img_g.shape:
                    fusionada, parcheado = fusionar([img_g, img_o])
                    if parcheado > 0:
                        cv2.imwrite(str(ganadora['ruta_imagen']), fusionada)
                        ganadora['parcheado'] = max(ganadora.get('parcheado', 0.0), parcheado)
        return ganadora

    paginas = []
    for toma in tomas:
        if paginas and misma_pagina(paginas[-1], toma):
            paginas[-1] = preferir(paginas[-1], toma)
            continue
        if len(paginas) >= 2 and misma_pagina(paginas[-2], toma):
            paginas[-2] = preferir(paginas[-2], toma)
            continue
        paginas.append(toma)
    print(f'{len(paginas)} páginas distintas entre las {len(tomas)} tomas', flush=True)
    for toma in paginas:
        print(f'  {momento(toma)}: {len(toma["palabras"])} palabras leídas, '
              f'{toma.get("capturas", 1)} capturas, mano borrada en un {100 * toma.get("parcheado", 0):.0f}%', flush=True)
    return paginas


# Function to say where in the recording a still comes from: its seconds, and
# its video when there are several
def momento(toma, corto=False):
    segundos = f'{toma["inicio"]:.0f}s' if corto else f'{toma["inicio"]:.1f}-{toma["fin"]:.1f} s'
    return f'{toma["video"]} {segundos}' if toma.get('video') else segundos


# Function to write the page images, split in two if requested, plus a numbered
# contact sheet so a glance shows which pages to delete before the OCR (a page
# caught half-way through a turn, the empty table at the start)
def guardar_paginas(paginas, carpeta):
    numero, miniaturas, informe = 0, [], []
    doble = getattr(args, 'doble', False)
    for toma in paginas:
        imagen = cargar(toma)
        mitades = [imagen]
        if doble:
            fin_izq, inicio_der = detectar_lomo(imagen)
            mitades = [imagen[:, :fin_izq], imagen[:, inicio_der:]]
        cortes = [(0, imagen.shape[1])] if not doble else [(0, fin_izq), (inicio_der, imagen.shape[1])]
        for (x0, x1), mitad in zip(cortes, mitades):
            numero += 1
            # las capturas comparten tamaño con la imagen fusionada: se parten por el
            # mismo lomo y se enderezan, sin más retoque, para que el OCR las lea tal cual
            if toma.get('rutas_capturas'):
                carpeta_capturas = carpeta / 'capturas' / f'pag_{numero}'
                carpeta_capturas.mkdir(parents=True, exist_ok=True)
                for k, ruta_captura in enumerate(toma['rutas_capturas'], 1):
                    captura = cv2.imread(str(ruta_captura))
                    if captura is not None and captura.shape[:2] == imagen.shape[:2]:
                        cv2.imwrite(str(carpeta_capturas / f'cap_{k}.png'), enderezar_texto(captura[:, x0:x1]))
            mitad = limpiar_iluminacion(enderezar_texto(desdoblar(mitad)))
            ruta = carpeta / f'pag_{numero}.png'
            cv2.imwrite(str(ruta), mitad)
            informe.append({'pagina': numero, 'origen': momento(toma),
                            'dimensiones': [mitad.shape[1], mitad.shape[0]],
                            'nitidez': nitidez(mitad), 'capturas': toma.get('capturas', 1),
                            'recorte_fiable': toma.get('recorte_fiable'),
                            'fraccion_mano_reemplazada': toma.get('parcheado', 0),
                            'video': toma.get('video'), 'segundo': toma['inicio'],
                            # el texto que Vision leyó en la toma (la doble página entera, en
                            # su caso): sirve para agrupar grabaciones por libro sin repetir el OCR
                            'texto': toma.get('texto', '')})
            print(f'{ruta} ({momento(toma)}, {mitad.shape[1]}x{mitad.shape[0]})', flush=True)
            miniatura_pagina = cv2.resize(mitad, (200, int(200 * mitad.shape[0] / mitad.shape[1])))
            miniatura_pagina = cv2.copyMakeBorder(miniatura_pagina, 0, 300 - min(300, miniatura_pagina.shape[0]), 0, 0,
                                                  cv2.BORDER_CONSTANT, value=(40, 40, 40))[:300]
            cv2.putText(miniatura_pagina, f'{numero} ({momento(toma, corto=True)})', (6, 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
            miniaturas.append(miniatura_pagina)
    columnas = 8
    while len(miniaturas) % columnas:
        miniaturas.append(np.full_like(miniaturas[0], 40))
    filas = [np.hstack(miniaturas[i:i + columnas]) for i in range(0, len(miniaturas), columnas)]
    cv2.imwrite(str(carpeta / 'paginas_detectadas.jpg'), np.vstack(filas), [cv2.IMWRITE_JPEG_QUALITY, 80])
    (carpeta / 'calidad.json').write_text(json.dumps(informe, indent=2, ensure_ascii=False), encoding='utf-8')
    return numero


# Function to list the videos to process, in the order they were recorded: a
# phone that cuts a long recording numbers the segments, so the file name
# orders them; the date is the alternative
def listar_videos(rutas):
    videos = []
    for ruta in (Path(r) for r in rutas):
        if ruta.is_dir():
            videos += [v for v in ruta.iterdir() if v.suffix.lower() in EXTENSIONES_VIDEO and not v.name.startswith('.')]
        elif ruta.suffix.lower() in EXTENSIONES_VIDEO:
            videos.append(ruta)
        else:
            raise SystemExit(f'Formato no reconocido: {ruta}. Vale {", ".join(EXTENSIONES_VIDEO)} o una carpeta con vídeos')
    # una previa de Video Boost (VB-01.COVER) sobra si está su versión completa (VB-02.MAIN)
    completas = {re.sub(r'~\d+$', '', v.name.split('.')[0]) for v in videos if '.VB-02.MAIN' in v.name}
    videos = [v for v in videos if not ('.VB-01.COVER' in v.name and re.sub(r'~\d+$', '', v.name.split('.')[0]) in completas)]
    if args.orden == 'fecha':
        return sorted(videos, key=lambda v: v.stat().st_mtime)
    return sorted(videos, key=lambda v: [int(t) if t.isdigit() else t.lower() for t in re.split(r'(\d+)', v.name)])


# Function to run the whole extraction
def procesar_video():
    global CARPETA_CANDIDATAS
    videos = listar_videos(args.videos)
    if not videos:
        raise SystemExit('No hay ningún vídeo que procesar')
    carpeta = Path(args.folder_output)
    carpeta.mkdir(parents=True, exist_ok=True)
    # la detección de un vídeo largo cuesta media hora: si la carpeta ya tiene las
    # páginas de estos mismos vídeos con estos mismos ajustes, se reutilizan, igual
    # que las demás etapas saltan lo que ya existe (la interfaz vacía la carpeta
    # al «empezar de cero», así que solo pasa al reanudar)
    huella = {'version_calidad': VERSION, 'videos': [{'video': str(v.resolve()), 'bytes': v.stat().st_size, 'modificado': v.stat().st_mtime} for v in videos],
              'ajustes': {k: v for k, v in vars(args).items() if k not in ('videos', 'folder_output', 'brutos')}}
    marca = carpeta / 'origen.json'
    existentes = sorted(carpeta.glob('pag_*.png'))
    if existentes and marca.exists() and json.loads(marca.read_text()) == huella:
        print(f'{len(existentes)} páginas ya detectadas de estos vídeos en {carpeta}: se reutilizan '
              '(borra la carpeta o marca «Empezar de cero» para repetir la detección)', flush=True)
        return
    # la numeración es correlativa, así que no puede convivir con restos de otra corrida
    for vieja in existentes:
        vieja.unlink()
    marca.unlink(missing_ok=True)
    carpeta_brutos = carpeta / 'brutos'
    CARPETA_CANDIDATAS = carpeta / 'candidatas'
    for temporal in (carpeta_brutos, CARPETA_CANDIDATAS):
        if temporal.exists():
            shutil.rmtree(temporal, ignore_errors=True)
        temporal.mkdir()

    inicio = time.time()
    if len(videos) > 1:
        print(f'{len(videos)} vídeos del mismo libro, en este orden: ' + ', '.join(v.name for v in videos), flush=True)
    # cada vídeo aporta sus tomas a una única secuencia, en orden: así la última
    # página de un segmento y la primera del siguiente se funden como repetidas
    tomas = []
    for video in videos:
        propias = elegir_fotogramas(medir_video(video))
        # los fotogramas enteros se escriben siempre: Vision los lee desde disco
        leer_fotogramas(video, propias, carpeta_brutos, desde=len(tomas) + 1)
        if len(videos) > 1:
            for toma in propias:
                toma['video'] = video.stem
        tomas += propias
    if not tomas:
        raise SystemExit('No se encontró ningún tramo de página quieta. Baja --quietud o --factor, o graba dejando cada '
                         'página quieta un par de segundos antes de pasarla.')
    recortar_tomas(tomas)
    enderezar_tomas(tomas)
    paginas = fundir_repetidas(tomas)
    total = guardar_paginas(paginas, carpeta)
    marca.write_text(json.dumps(huella, indent=2, ensure_ascii=False))
    shutil.rmtree(CARPETA_CANDIDATAS, ignore_errors=True)
    if not args.brutos:
        shutil.rmtree(carpeta_brutos, ignore_errors=True)
    print(f'{total} páginas extraídas de {len(videos)} vídeo(s) en {time.time() - inicio:.0f} s', flush=True)

if __name__ == '__main__':
    args = parser.parse_args()
    if not np.isfinite([args.fps, args.quietud, args.factor, args.umbral]).all() or args.fps <= 0 or args.quietud < 0 or args.capturas < 1:
        parser.error('fps y capturas deben ser positivos; quietud no puede ser negativa')
    procesar_video()
