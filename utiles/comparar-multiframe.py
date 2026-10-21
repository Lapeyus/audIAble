"""Banco de pruebas: OCR de una imagen por página (el método de siempre) frente a OCR multifotograma.

Detecta las páginas una sola vez, guardando las capturas, y corre las dos cadenas sobre
exactamente las mismas imágenes y con el mismo corrector:

  A (base)          Vision sobre la imagen fusionada → limpieza → agente con la imagen
  B (multifotograma) TypeSafe filtra capturas → Vision sobre todas → fusión por renglones
                     → limpieza → agente con la imagen y el aviso de borrador múltiple

Compara cuánto texto queda [ilegible] tras el agente, renglones dudosos de Vision, texto
recuperado, palabras sospechosas y fragmentos duplicados. Escribe comparacion.json y .md.

  python3 utiles/comparar-multiframe.py --video libro.mp4 --o /ruta/prueba --agente codex
"""
# Importing required libraries
import re
import sys
import json
import time
import argparse
import subprocess
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PASOS = RAIZ / 'pasos'

parser = argparse.ArgumentParser(description='Compare single-image OCR against multi-frame OCR on the same book.')
parser.add_argument('--video', nargs='+', required=True, type=Path, help='Video(s) of the book.')
parser.add_argument('--o', dest='carpeta', required=True, type=Path, help='Work folder for the comparison.')
parser.add_argument('--agente', default='codex', help='Correction agent for both chains (codex, claude, agy).')
parser.add_argument('--idioma', default='es')
parser.add_argument('--simple', action='store_true', help='One page per shot (by default the book is open, two pages).')
parser.add_argument('--con-typesafe', action='store_true', help='Multi-frame with the TypeSafe (Jev) capture filter.')
parser.add_argument('--sin-control', action='store_true',
                    help='Skip the control branch (single-image OCR corrected with the multi-frame prompt), which tells '
                         'how much of the gain comes from the prompt alone.')
parser.add_argument('--solo-medir', action='store_true', help='Do not run anything: recompute the comparison from the existing folders.')
args = parser.parse_args()


def ejecutar(nombre, comando, registro):
    print(f'\n== {nombre}', flush=True)
    inicio = time.time()
    with open(registro, 'a', encoding='utf-8') as salida:
        salida.write(f'\n$ {" ".join(str(c) for c in comando)}\n')
        salida.flush()
        proceso = subprocess.run([sys.executable, '-u', '-W', 'ignore'] + [str(c) for c in comando], cwd=RAIZ,
                                 stdout=salida, stderr=subprocess.STDOUT)
    if proceso.returncode != 0:
        raise SystemExit(f'{nombre} terminó con error {proceso.returncode}; mira {registro}')
    segundos = round(time.time() - inicio)
    print(f'   {segundos} s', flush=True)
    return segundos


def paginas_de(carpeta):
    return sorted((p for p in carpeta.glob('pag_*.txt') if not p.name.startswith('.') and 'cambios' not in p.name),
                  key=lambda p: int(re.findall(r'\d+', p.stem)[-1]))


def sospechosa(token):
    t = token.strip('.,;:¡!¿?()"«»“”\'-—–')
    if len(t) < 3 or t.isdigit():
        return False
    return bool(re.search(r'[A-Za-zÁÉÍÓÚÑáéíóúñ]\d|\d[A-Za-zÁÉÍÓÚÑáéíóúñ]', t)
                or re.search(r'[bcdfghjklmnpqrstvwxz]{5}', t.lower())
                or re.search(r'[a-záéíóúñ][A-ZÁÉÍÓÚÑ]', t))


# Function to measure a folder of page texts
def medir(carpeta):
    paginas = paginas_de(carpeta)
    textos = {p.stem: p.read_text(encoding='utf-8', errors='ignore') for p in paginas}
    todo = '\n'.join(textos.values())
    palabras = re.findall(r'\S+', todo)
    ilegibles = {k: len(re.findall(r'\[ilegible\]', v, re.I)) for k, v in textos.items()}
    duplicados = sum(1 for v in textos.values() for m in re.finditer(r'(\S[^\n]{5,}?)\1', v)
                     if not m.group(1).strip().isdigit() and '[ilegible]' not in m.group(1))
    return {
        'paginas': len(paginas),
        'caracteres': len(todo),
        'palabras': len(palabras),
        'vocabulario': len({w.lower().strip('.,;:¡!¿?()"«»“”\'-—–') for w in palabras}),
        'ilegibles': sum(ilegibles.values()),
        'paginas_con_ilegibles': sum(1 for n in ilegibles.values() if n),
        'palabras_sospechosas': sum(1 for w in palabras if sospechosa(w)),
        'fragmentos_duplicados': duplicados,
    }, textos


# Function to count the whole words of the agent's output that no token of the
# OCR draft supports (exact, or 80 % similar): what the agent wrote without the
# OCR having seen it. Fragments glued to an [ilegible] do not count
def tokens(texto):
    texto = re.sub(r'-\s*\n\s*', '', texto)
    return [w.lower().strip('.,;:¡!¿?()"«»“”\'-—–') for w in re.findall(r'\S+', texto)]


def sin_respaldo(salida, borrador):
    from difflib import SequenceMatcher
    base = list(set(tokens(borrador)))
    return sum(1 for w in tokens(salida)
               if len(w) >= 4 and 'ilegible' not in w and w not in base
               and not any(SequenceMatcher(None, w, b, autojunk=False).ratio() >= 0.8 for b in base if abs(len(b) - len(w)) <= 3))


def rechazos(registro):
    texto = Path(registro).read_text(encoding='utf-8', errors='ignore') if Path(registro).exists() else ''
    return len(re.findall(r'RECHAZADO', texto))


def principal():
    carpeta = args.carpeta
    carpeta.mkdir(parents=True, exist_ok=True)
    img = carpeta / 'imagenes'
    registro = carpeta / 'registro.log'
    tiempos = {}

    a, b, c = carpeta / 'A_base', carpeta / 'B_multifotograma', carpeta / 'C_control'
    if args.solo_medir:
        return comparar(carpeta, a, b, c, tiempos)

    deteccion = [PASOS / 'pre-video.py', '--f'] + args.video + ['--o', img, '--idioma', args.idioma, '--guardar-capturas']
    if not args.simple:
        deteccion.append('--doble')
    tiempos['deteccion'] = ejecutar('Detección de páginas (con capturas)', deteccion, registro)

    tiempos['A_ocr'] = ejecutar('A · OCR de la imagen fusionada',
                                [PASOS / 'pro-mac-ocr.py', '--f', img, '--o', a / 'texto_ocr', '--idioma', args.idioma, '--calidad', 'base'], registro)
    multi = [PASOS / 'pro-multiframe-ocr.py', '--f', img, '--o', b / 'texto_ocr', '--idioma', args.idioma]
    if args.con_typesafe:
        multi.append('--con-typesafe')
    tiempos['B_ocr'] = ejecutar('B · OCR multifotograma', multi, registro)

    for rama in (a, b):
        ejecutar(f'{rama.name} · limpieza', [PASOS / 'pre-cleanup.py', '--f', rama / 'texto_ocr', '--idioma', args.idioma], registro)
    # las dos correcciones van a la vez: son independientes y el agente es la etapa lenta
    from concurrent.futures import ThreadPoolExecutor
    def corregir(rama, extra):
        return rama.name, ejecutar(
            f'{rama.name} · corrección con {args.agente}',
            [PASOS / 'pre-ollama.py', '--f', rama / 'texto_ocr', '--o', rama / 'texto', '--m', args.agente,
             '--img', img, '--idioma', args.idioma] + extra, rama / 'registro_agente.log')
    with ThreadPoolExecutor(2) as grupo:
        for nombre, segundos in grupo.map(lambda r: corregir(*r), ((a, []), (b, ['--borrador-multiple']))):
            tiempos[f'{nombre}_agente'] = segundos

    # control: el OCR de una imagen corregido con la instrucción de B, en las páginas
    # donde A y B difieren en ilegibles. Separa lo que aporta el multifotograma de lo
    # que aporta solo la instrucción (que anima al agente a completar, y a veces a inventar)
    if not args.sin_control:
        _, ta = medir(a / 'texto')
        _, tb = medir(b / 'texto')
        cambian = [k for k in ta if ta[k].lower().count('[ilegible]') != tb.get(k, '').lower().count('[ilegible]')]
        (c / 'texto_ocr').mkdir(parents=True, exist_ok=True)
        for k in cambian:
            (c / 'texto_ocr' / f'{k}.txt').write_text((a / 'texto_ocr' / f'{k}.txt').read_text(encoding='utf-8'), encoding='utf-8')
        if cambian:
            tiempos['C_control_agente'] = ejecutar(
                f'C_control · {args.agente} con la instrucción de B sobre el OCR de A ({len(cambian)} páginas)',
                [PASOS / 'pre-ollama.py', '--f', c / 'texto_ocr', '--o', c / 'texto', '--m', args.agente,
                 '--img', img, '--idioma', args.idioma, '--borrador-multiple'], c / 'registro_agente.log')
    comparar(carpeta, a, b, c, tiempos)


def comparar(carpeta, a, b, c, tiempos):
    resultado = {'agente': args.agente, 'tiempos_s': tiempos}
    for rama in (a, b):
        ocr, textos_ocr = medir(rama / 'texto_ocr')
        corregido, textos = medir(rama / 'texto')
        corregido['paginas_rechazadas_por_el_agente'] = rechazos(rama / 'registro_agente.log')
        resultado[rama.name] = {'ocr': ocr, 'corregido': corregido}
    fusion = json.loads((b / 'texto_ocr' / 'informes' / 'fusion_resumen.json').read_text())
    resultado['fusion'] = fusion

    # palabras que el multifotograma aporta y la base no tiene (en el texto corregido)
    _, ta = medir(a / 'texto')
    _, tb = medir(b / 'texto')
    limpio = lambda t: {w.lower().strip('.,;:¡!¿?()"«»“”\'-—–') for w in re.findall(r'\S+', t)} - {'[ilegible]', ''}
    ganadas = sorted({w for k in tb for w in limpio(tb[k]) - limpio(ta.get(k, ''))})
    perdidas = sorted({w for k in ta for w in limpio(ta[k]) - limpio(tb.get(k, ''))})
    resultado['palabras_solo_en_B'] = len(ganadas)
    resultado['palabras_solo_en_A'] = len(perdidas)
    # por página: dónde cambia el número de ilegibles
    por_pagina = []
    for k in ta:
        ia, ib = len(re.findall(r'\[ilegible\]', ta[k], re.I)), len(re.findall(r'\[ilegible\]', tb.get(k, ''), re.I))
        if ia != ib:
            por_pagina.append({'pagina': k, 'ilegibles_A': ia, 'ilegibles_B': ib})
    resultado['paginas_que_cambian'] = sorted(por_pagina, key=lambda f: f['ilegibles_B'] - f['ilegibles_A'])
    # respaldo: en todas las páginas, y el control en las suyas
    leer = lambda carpeta_txt, k: (carpeta_txt / f'{k}.txt').read_text(encoding='utf-8', errors='ignore') if (carpeta_txt / f'{k}.txt').exists() else ''
    for rama in (a, b):
        resultado[rama.name]['corregido']['palabras_sin_respaldo'] = sum(
            sin_respaldo(leer(rama / 'texto', k), leer(rama / 'texto_ocr', k)) for k in ta)
    paginas_control = [p.stem for p in paginas_de(c / 'texto')] if (c / 'texto').exists() else []
    if paginas_control:
        cuenta = lambda carpeta_txt, carpeta_borrador: {
            'ilegibles': sum(leer(carpeta_txt, k).lower().count('[ilegible]') for k in paginas_control),
            'palabras_sin_respaldo': sum(sin_respaldo(leer(carpeta_txt, k), leer(carpeta_borrador, k)) for k in paginas_control)}
        resultado['control'] = {'paginas': len(paginas_control),
                                'A': cuenta(a / 'texto', a / 'texto_ocr'),
                                'C_instruccion_sola': cuenta(c / 'texto', a / 'texto_ocr'),
                                'B': cuenta(b / 'texto', b / 'texto_ocr')}
    (carpeta / 'comparacion.json').write_text(json.dumps(resultado, indent=2, ensure_ascii=False), encoding='utf-8')

    fila = lambda nombre, clave, etapa: f'| {nombre} | {resultado["A_base"][etapa][clave]} | {resultado["B_multifotograma"][etapa][clave]} |'
    lineas = ['| Indicador | A · una imagen | B · multifotograma |', '| --- | --- | --- |',
              fila('[ilegible] tras el agente', 'ilegibles', 'corregido'),
              fila('Páginas con algún [ilegible]', 'paginas_con_ilegibles', 'corregido'),
              fila('Palabras tras el agente', 'palabras', 'corregido'),
              fila('Caracteres del OCR (antes del agente)', 'caracteres', 'ocr'),
              fila('Palabras sospechosas del OCR', 'palabras_sospechosas', 'ocr'),
              fila('Fragmentos duplicados del OCR', 'fragmentos_duplicados', 'ocr'),
              fila('Páginas rechazadas por el agente', 'paginas_rechazadas_por_el_agente', 'corregido'),
              fila('Palabras sin respaldo en el OCR (puestas por el agente)', 'palabras_sin_respaldo', 'corregido'),
              f'| Renglones dudosos de Vision (confianza < 0,5) | {fusion["dudosos_final"]} | {fusion["dudosos_fusion"]} |',
              '', f'Renglones recuperados de las capturas: {fusion["recuperados"]}; mejorados: {fusion["mejorados"]}.',
              f'Palabras distintas solo en B: {len(ganadas)}; solo en A: {len(perdidas)}.',
              f'TypeSafe: {fusion["tokens_typesafe"]} tokens de entrada sobre {fusion["capturas"]} capturas.']
    if 'control' in resultado:
        ctl = resultado['control']
        lineas += ['', f'Control en las {ctl["paginas"]} páginas donde A y B difieren:', '',
                   '| Rama | [ilegible] | Palabras sin respaldo |', '| --- | --- | --- |',
                   f'| A · una imagen | {ctl["A"]["ilegibles"]} | {ctl["A"]["palabras_sin_respaldo"]} |',
                   f'| C · una imagen + instrucción de B | {ctl["C_instruccion_sola"]["ilegibles"]} | {ctl["C_instruccion_sola"]["palabras_sin_respaldo"]} |',
                   f'| B · multifotograma | {ctl["B"]["ilegibles"]} | {ctl["B"]["palabras_sin_respaldo"]} |']
    (carpeta / 'comparacion.md').write_text('\n'.join(lineas) + '\n', encoding='utf-8')
    print('\n' + '\n'.join(lineas), flush=True)


principal()
