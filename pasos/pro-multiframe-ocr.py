"""OCR multifotograma: lee cada página en todas sus capturas y combina las lecturas renglón a renglón.

La página final es una sola imagen fusionada; las capturas de su reposo (que pre-video.py deja
en capturas/pag_N/ con --guardar-capturas) son fotos distintas del mismo papel, con la mano en
otro sitio, otro reflejo, otro desenfoque. Un renglón que la mano tapa en una foto suele verse
en otra. El paso:

1. Con --con-typesafe, filtra las capturas con TypeSafe (una petición por página): solo cuentan las
   que muestran la misma página que la imagen final y la hoja quieta. Por omisión se usan todas:
   en el libro de prueba el filtro no aportó una mejora medible.
2. Lee con Vision la imagen final y cada captura válida, con la confianza y la caja de cada renglón.
3. Agrupa los renglones de todas las lecturas por posición y parecido de texto, y en cada grupo se
   queda con la lectura más fiable (confianza, y a igualdad, la más completa). Un grupo sin
   renglón en la imagen final es texto recuperado de las capturas.

Escribe pag_N.txt como el OCR de siempre, e informes/pag_N.fusion.json con lo que cambió.
"""
# Importing required libraries
import re
import sys
import json
import argparse
import subprocess
from pathlib import Path
from difflib import SequenceMatcher
from concurrent.futures import ThreadPoolExecutor

import cv2

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from nucleo.calidad_video import calidad

IDIOMAS_VISION = {'es': 'es-ES', 'en': 'en-US', 'fr': 'fr-FR', 'it': 'it-IT', 'pt': 'pt-BR', 'de': 'de-DE'}

parser = argparse.ArgumentParser(description='Multi-frame OCR: read every capture of each page and keep the best reading of every line.')
parser.add_argument('--f', dest='carpeta_img', required=True, type=Path, help='Images folder (pag_N.png and capturas/pag_N/).')
parser.add_argument('--o', dest='carpeta_txt', required=True, type=Path, help='Folder for the text files.')
parser.add_argument('--idioma', default='es', choices=sorted(IDIOMAS_VISION))
parser.add_argument('--max-capturas', type=int, default=6, help='Sharpest captures considered per page.')
parser.add_argument('--con-typesafe', dest='con_typesafe', action='store_true',
                    help='Filter the captures with TypeSafe (Jev) before reading them. Off by default: on the test book it '
                         'changed the draft of 21 pages out of 116 and brought no measurable gain for 1.5 M input tokens.')
parser.add_argument('--sin-typesafe', dest='sin_typesafe', action='store_true', help=argparse.SUPPRESS)  # compatibilidad: ya es lo normal
parser.add_argument('--umbral-typesafe', type=float, default=0.5, help='Minimum probability for "same page" and "still page".')
parser.add_argument('--hilos', type=int, default=4, help='TypeSafe requests in flight.')
parser.add_argument('--confianza-minima', type=float, default=0.5, help='A line read only in captures needs at least this confidence.')
args = parser.parse_args()


def numero(ruta):
    return int(re.findall(r'\d+', ruta.stem)[-1])


# ---------------------------------------------------------------- 1. filtro con TypeSafe

# Function to ask TypeSafe, in one request per page, which captures show the
# same page as the final image and the sheet still. The captures go in the state
# once, as an array, and every question points at one of them by path
def filtrar(pagina, capturas):
    from nucleo.typesafe import Peticion
    peticion = Peticion('jev-latest', lado_max=1024)
    peticion.cuerpo['state'] = {'pagina': peticion.imagen(pagina), 'capturas': [peticion.imagen(c) for c in capturas]}
    for i in range(len(capturas)):
        peticion.noul(f'misma_{i}', f'`capturas[{i}]` shows the same printed book page as `pagina` (the same text).')
        peticion.noul(f'quieta_{i}', f'`capturas[{i}]` shows the page lying still: not being turned, lifted, or blurred by motion.')
    respuesta = peticion.enviar()
    respuestas = respuesta['answers']
    veredictos = []
    for i, captura in enumerate(capturas):
        misma, quieta = respuestas[f'misma_{i}']['noul'], respuestas[f'quieta_{i}']['noul']
        veredictos.append({'captura': captura.name, 'misma': round(misma, 3), 'quieta': round(quieta, 3),
                           'valida': misma >= args.umbral_typesafe and quieta >= args.umbral_typesafe})
    return veredictos, respuesta.get('usage', {}).get('input_tokens', 0)


# ---------------------------------------------------------------- 2. lectura con Vision

def leer_vision(rutas):
    lecturas = {}
    for inicio in range(0, len(rutas), 40):
        comando = ['swift', str(RAIZ / 'pasos' / 'vision_ocr.swift'), f'{IDIOMAS_VISION[args.idioma]},en-US', '--json'] \
                  + [str(r) for r in rutas[inicio:inicio + 40]]
        salida = subprocess.run(comando, capture_output=True, text=True, timeout=3600)
        actual = None
        for linea in salida.stdout.splitlines():
            if linea.startswith('###FILE:'):
                actual = linea[len('###FILE:'):]
            elif actual and linea.startswith('['):
                lecturas[actual] = json.loads(linea)
        print(f'  Vision: {min(inicio + 40, len(rutas))} de {len(rutas)} imágenes leídas', flush=True)
    return lecturas


# ---------------------------------------------------------------- 3. fusión

def normalizar(texto):
    return re.sub(r'\s+', ' ', texto.lower()).strip()


# Function to tell whether two lines are the same printed line: same height on
# the page (the captures share the crop of the final image), overlapping
# horizontally, and similar text. Short lines rely on position alone
def mismo_renglon(a, b):
    xa, ya, wa, ha = a['caja']
    xb, yb, wb, hb = b['caja']
    alto = max(ha, hb, 1e-6)
    if abs((ya + ha / 2) - (yb + hb / 2)) > 0.6 * alto:
        return False
    solape = min(xa + wa, xb + wb) - max(xa, xb)
    if solape < 0.3 * min(wa, wb):
        return False
    ta, tb = normalizar(a['texto']), normalizar(b['texto'])
    if min(len(ta), len(tb)) < 6:
        return True
    return SequenceMatcher(None, ta, tb, autojunk=False).ratio() >= 0.35


# Function to bring a capture's line boxes into the final image's frame. The
# captures are cropped like the final image, but not identically (its own
# corners, a different deskew, the final image's dewarp), so absolute positions
# can be off by more than a line. Lines whose text nearly matches a final line
# are anchors; a robust fit of y and x through them moves every box. Without
# three anchors the capture cannot be placed and contributes nothing
def anclar(lectura_final, lectura_captura):
    pares = []
    for r in lectura_captura:
        tr = normalizar(r['texto'])
        if len(tr) < 10:
            continue
        mejor, puntuacion = None, 0.0
        for f in lectura_final:
            tf = normalizar(f['texto'])
            if len(tf) < 10:
                continue
            ratio = SequenceMatcher(None, tr, tf, autojunk=False).ratio()
            if ratio > puntuacion:
                mejor, puntuacion = f, ratio
        if mejor is not None and puntuacion >= 0.8:
            pares.append((r, mejor))
    if len(pares) < 3:
        return None

    def ajuste(origen, destino):
        # recta robusta: pendiente mediana entre pares de anclas, ordenada mediana
        import statistics
        pendientes = [(destino[j] - destino[i]) / (origen[j] - origen[i])
                      for i in range(len(origen)) for j in range(i + 1, len(origen)) if abs(origen[j] - origen[i]) > 0.02]
        pendiente = statistics.median(pendientes) if pendientes else 1.0
        if not 0.8 <= pendiente <= 1.25:
            pendiente = 1.0
        ordenada = statistics.median(d - pendiente * o for o, d in zip(origen, destino))
        residuos = [abs(d - (pendiente * o + ordenada)) for o, d in zip(origen, destino)]
        return pendiente, ordenada, statistics.median(residuos)

    centro = lambda caja, eje: caja[eje] + caja[eje + 2] / 2
    py, oy, ry = ajuste([centro(r['caja'], 1) for r, _ in pares], [centro(f['caja'], 1) for _, f in pares])
    px, ox, _ = ajuste([r['caja'][0] for r, _ in pares], [f['caja'][0] for _, f in pares])
    alto_tipico = sorted(f['caja'][3] for _, f in pares)[len(pares) // 2]
    if ry > 0.5 * alto_tipico:
        return None  # las anclas no cuadran entre sí: no es la misma geometría
    movidas = []
    for r in lectura_captura:
        x, y, w, h = r['caja']
        cy = py * (y + h / 2) + oy
        movidas.append(dict(r, caja=[px * x + ox, cy - py * h / 2, px * w, py * h]))
    return movidas


# Function to merge the readings of one page. The final image's reading goes
# first, so every one of its lines anchors a group; capture lines join a group
# or open a new one. Each group keeps its most confident, most complete line
def fusionar(lectura_final, lecturas_capturas):
    ancladas, sin_anclar = [], []
    for origen, lectura in lecturas_capturas:
        movida = anclar(lectura_final, lectura) if lectura_final else None
        if movida is None:
            sin_anclar.append(origen)
        else:
            ancladas.append((origen, movida))
    lecturas_capturas = ancladas
    # cada renglón de la imagen final abre su propio grupo y nunca se funde con otro;
    # un renglón de captura se une solo al grupo que mejor le encaja, comparado con el
    # primer renglón del grupo, para que un renglón intermedio no encadene dos grupos
    grupos = [[dict(r, origen='final')] for r in lectura_final]

    def encaje(renglon, grupo):
        cabeza = grupo[0]
        if not mismo_renglon(renglon, cabeza):
            return None
        distancia = abs((renglon['caja'][1] + renglon['caja'][3] / 2) - (cabeza['caja'][1] + cabeza['caja'][3] / 2))
        return (SequenceMatcher(None, normalizar(renglon['texto']), normalizar(cabeza['texto']), autojunk=False).ratio(), -distancia)

    for origen, lectura in lecturas_capturas:
        for renglon in lectura:
            renglon = dict(renglon, origen=origen)
            candidatos = [(encaje(renglon, g), g) for g in grupos]
            candidatos = [(e, g) for e, g in candidatos if e is not None and not any(r['origen'] == origen for r in g)]
            if candidatos:
                max(candidatos, key=lambda c: c[0])[1].append(renglon)
            else:
                grupos.append([renglon])

    elegidos, informe = [], {'renglones_final': len(lectura_final), 'recuperados': [], 'mejorados': [], 'descartados': 0,
                             'capturas_sin_anclar': sin_anclar}
    textos_final = [normalizar(r['texto']) for r in lectura_final]
    for grupo in grupos:
        del_final = [r for r in grupo if r['origen'] == 'final']
        mejor = max(grupo, key=lambda r: (round(r['confianza'], 1), len(r['texto'])))
        if not del_final:
            # texto que la imagen final no tenía: se exige confianza, y si solo lo vio una
            # captura, confianza alta, para no colar restos de la página de enfrente
            capturas_que_lo_ven = {r['origen'] for r in grupo}
            # y que sea un renglón de verdad: largo, o visto por dos capturas (los restos
            # cortos suelen ser bordes de la página de enfrente)
            if mejor['confianza'] < args.confianza_minima or (len(capturas_que_lo_ven) == 1 and mejor['confianza'] < 0.8) \
                    or (len(capturas_que_lo_ven) == 1 and len(normalizar(mejor['texto'])) < 15):
                informe['descartados'] += 1
                continue
            # red de seguridad: si ya está casi igual en otro sitio de la página, no es nuevo
            nuevo = normalizar(mejor['texto'])
            if any(SequenceMatcher(None, nuevo, t, autojunk=False).ratio() >= 0.75 for t in textos_final if len(t) >= 6) \
                    or nuevo in textos_final:
                informe['descartados'] += 1
                continue
            textos_final.append(nuevo)
            informe['recuperados'].append({'texto': mejor['texto'], 'de': mejor['origen'], 'confianza': round(mejor['confianza'], 2)})
        elif mejor['origen'] != 'final' and normalizar(mejor['texto']) != normalizar(del_final[0]['texto']):
            informe['mejorados'].append({'antes': del_final[0]['texto'], 'despues': mejor['texto'], 'de': mejor['origen'],
                                         'confianza_antes': round(del_final[0]['confianza'], 2),
                                         'confianza_despues': round(mejor['confianza'], 2)})
        elegidos.append(mejor)

    # orden de lectura: de arriba abajo (Vision mide desde abajo) y de izquierda a derecha
    elegidos.sort(key=lambda r: (-round((r['caja'][1] + r['caja'][3] / 2) * 60), r['caja'][0]))
    informe['renglones_fusion'] = len(elegidos)
    informe['confianza_media_final'] = round(sum(r['confianza'] for r in lectura_final) / max(len(lectura_final), 1), 3)
    informe['confianza_media_fusion'] = round(sum(r['confianza'] for r in elegidos) / max(len(elegidos), 1), 3)
    informe['dudosos_final'] = sum(1 for r in lectura_final if r['confianza'] < 0.5)
    informe['dudosos_fusion'] = sum(1 for r in elegidos if r['confianza'] < 0.5)
    return '\n'.join(r['texto'] for r in elegidos), informe


# ---------------------------------------------------------------- ejecución

def principal():
    carpeta_img, carpeta_txt = args.carpeta_img, args.carpeta_txt
    (carpeta_txt / 'informes').mkdir(parents=True, exist_ok=True)
    paginas = sorted((p for p in carpeta_img.glob('pag_*.png') if not p.name.startswith('.')), key=numero)
    candidatas = {}
    for pagina in paginas:
        carpeta = carpeta_img / 'capturas' / pagina.stem
        capturas = sorted((c for c in carpeta.glob('cap_*.png') if not c.name.startswith('.')), key=numero) if carpeta.exists() else []
        capturas = sorted(capturas, key=lambda c: calidad(cv2.imread(str(c))), reverse=True)[:args.max_capturas]
        candidatas[pagina] = capturas
    total_capturas = sum(len(c) for c in candidatas.values())
    print(f'{len(paginas)} páginas, {total_capturas} capturas candidatas', flush=True)
    if not total_capturas:
        sys.exit(f'No hay capturas en {carpeta_img}/capturas: repite la detección con pre-video.py --guardar-capturas')

    veredictos, tokens = {}, 0
    if not args.con_typesafe:
        for pagina, capturas in candidatas.items():
            veredictos[pagina] = [{'captura': c.name, 'valida': True} for c in capturas]
    else:
        def una(pagina):
            if not candidatas[pagina]:
                return pagina, [], 0
            try:
                return (pagina, *filtrar(pagina, candidatas[pagina]))
            except Exception as error:
                print(f'  {pagina.name}: TypeSafe falló ({error}); se usan todas sus capturas', flush=True)
                return pagina, [{'captura': c.name, 'valida': True, 'error': str(error)[:120]} for c in candidatas[pagina]], 0
        with ThreadPoolExecutor(args.hilos) as grupo:
            for pagina, veredicto, gastados in grupo.map(una, paginas):
                veredictos[pagina], tokens = veredicto, tokens + gastados
        validas = sum(v['valida'] for vs in veredictos.values() for v in vs)
        print(f'TypeSafe: {validas} de {total_capturas} capturas válidas, {tokens} tokens de entrada', flush=True)

    lecturas = leer_vision(paginas + [c for p in paginas for c, v in zip(candidatas[p], veredictos[p]) if v['valida']])
    resumen = {'paginas': len(paginas), 'capturas': total_capturas, 'tokens_typesafe': tokens,
               'recuperados': 0, 'mejorados': 0, 'dudosos_final': 0, 'dudosos_fusion': 0}
    for pagina in paginas:
        de_capturas = [(c.name, lecturas.get(str(c), [])) for c, v in zip(candidatas[pagina], veredictos[pagina]) if v['valida']]
        texto, informe = fusionar(lecturas.get(str(pagina), []), de_capturas)
        informe['capturas'] = veredictos[pagina]
        (carpeta_txt / f'{pagina.stem}.txt').write_text(texto + '\n', encoding='utf-8')
        (carpeta_txt / 'informes' / f'{pagina.stem}.fusion.json').write_text(json.dumps(informe, indent=2, ensure_ascii=False), encoding='utf-8')
        for clave in ('dudosos_final', 'dudosos_fusion'):
            resumen[clave] += informe[clave]
        resumen['recuperados'] += len(informe['recuperados'])
        resumen['mejorados'] += len(informe['mejorados'])
        print(f'{pagina.stem}: {informe["renglones_final"]} → {informe["renglones_fusion"]} renglones, '
              f'{len(informe["recuperados"])} recuperados, {len(informe["mejorados"])} mejorados', flush=True)
    (carpeta_txt / 'informes' / 'fusion_resumen.json').write_text(json.dumps(resumen, indent=2, ensure_ascii=False))
    print(json.dumps(resumen, ensure_ascii=False), flush=True)


principal()
