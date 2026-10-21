# Importing required libraries
import re
import sys
import json
import argparse
import subprocess
import statistics as st
from pathlib import Path
from collections import Counter

# La raíz del repositorio queda un nivel por encima de esta carpeta
RAIZ = Path(__file__).resolve().parent.parent
IDIOMAS_VISION = {'es': 'es-ES', 'en': 'en-US', 'fr': 'fr-FR', 'it': 'it-IT', 'pt': 'pt-BR', 'de': 'de-DE'}

# Command line arguments setup
parser = argparse.ArgumentParser(
    description='Quality indicators of a book made from video: what the page detector reports (calidad.json), '
                'what Vision reads per page (confidence per line, with --json) and how the text looks '
                '(characters, words, suspicious tokens). Writes indicadores.json and prints a summary.')
parser.add_argument('--f', dest='carpeta', required=True, help='Work folder: imagenes/ (with calidad.json) and texto/ inside.')
parser.add_argument('--idioma', dest='idioma', default='es', choices=sorted(IDIOMAS_VISION))
parser.add_argument('--sin-vision', dest='sin_vision', action='store_true', help='Skip the per-line confidence pass.')
args = parser.parse_args()


# Function to read every page again with Vision in JSON mode, to get the
# confidence of each line. Batches keep one swift start-up for many pages
def confianzas_vision(rutas):
    resultado = {}
    for inicio in range(0, len(rutas), 40):
        comando = ['swift', str(RAIZ / 'pasos' / 'vision_ocr.swift'), f'{IDIOMAS_VISION[args.idioma]},en-US', '--json'] \
                  + [str(r) for r in rutas[inicio:inicio + 40]]
        salida = subprocess.run(comando, capture_output=True, text=True, timeout=3600)
        actual = None
        for linea in salida.stdout.splitlines():
            if linea.startswith('###FILE:'):
                actual = linea[len('###FILE:'):]
            elif actual and linea.startswith('['):
                resultado[actual] = json.loads(linea)
    return resultado


# Function to flag tokens that no Spanish word looks like: digits glued to
# letters, four consonants in a row, letters repeated three times, or a lone
# capital inside a lowercase word
def sospechoso(token):
    t = token.strip('.,;:¡!¿?()"«»“”\'-')
    if len(t) < 3:
        return False
    if re.search(r'[A-Za-zÁÉÍÓÚÑáéíóúñ]\d|\d[A-Za-zÁÉÍÓÚÑáéíóúñ]', t):
        return True
    # cinco consonantes seguidas: cuatro las tiene el español (construir, instrumento)
    if re.search(r'[bcdfghjklmnpqrstvwxz]{5}', t.lower()):
        return True
    if re.search(r'(.)\1\1', t.lower()) and not t.isdigit():
        return True
    if re.search(r'[a-záéíóúñ][A-ZÁÉÍÓÚÑ]', t):
        return True
    return False


def principal():
    carpeta = Path(args.carpeta)
    carpeta_img, carpeta_txt = carpeta / 'imagenes', carpeta / 'texto'
    calidad = json.loads((carpeta_img / 'calidad.json').read_text(encoding='utf-8')) if (carpeta_img / 'calidad.json').exists() else []
    paginas = sorted((p for p in carpeta_txt.glob('pag_*.txt') if not p.name.startswith('.') and 'cambios' not in p.name),
                     key=lambda p: int(re.findall(r'\d+', p.stem)[-1]))
    informe = {'paginas': len(paginas), 'detector': {}, 'ocr': {}, 'texto': {}, 'por_pagina': []}

    # --- detector
    if calidad:
        mano = [p.get('fraccion_mano_reemplazada', 0) for p in calidad]
        nitidez = [p.get('nitidez', 0) for p in calidad]
        tamanos = Counter(tuple(p.get('dimensiones', [])) for p in calidad)
        informe['detector'] = {
            'paginas_detectadas': len(calidad),
            'recorte_fiable': sum(1 for p in calidad if p.get('recorte_fiable')),
            'mano_borrada_mediana': round(st.median(mano), 2),
            'paginas_sin_borrar_mano': sum(1 for m in mano if m == 0),
            'nitidez_mediana': round(st.median(nitidez), 1),
            'nitidez_minima': round(min(nitidez), 1),
            'tamano_mas_comun': list(tamanos.most_common(1)[0][0]) if tamanos else None,
            'tamanos_distintos': len(tamanos),
            'capturas_por_pagina_mediana': st.median(p.get('capturas', 1) for p in calidad),
        }

    # --- lectura con confianza por línea
    por_ruta = {}
    if not args.sin_vision:
        imagenes = [carpeta_img / f'{p.stem}.png' for p in paginas if (carpeta_img / f'{p.stem}.png').exists()]
        por_ruta = confianzas_vision(imagenes)

    # --- texto
    totales = {'caracteres': 0, 'palabras': 0, 'sospechosas': 0, 'lineas': 0, 'lineas_dudosas': 0}
    confianzas_todas = []
    for pagina in paginas:
        texto = pagina.read_text(encoding='utf-8', errors='ignore')
        palabras = re.findall(r'\S+', texto)
        sospechosas = [w for w in palabras if sospechoso(w)]
        lineas = por_ruta.get(str(carpeta_img / f'{pagina.stem}.png'), [])
        confianzas = [l['confianza'] for l in lineas]
        confianzas_todas += confianzas
        dudosas = sum(1 for c in confianzas if c < 0.5)
        # un parche de la mano mal alineado pega el mismo texto dos veces seguidas («su asomsu asom»)
        duplicados = [m.group(1) for m in re.finditer(r'(\S[^\n]{5,}?)\1', texto) if not m.group(1).strip().isdigit()]
        fila = {'pagina': pagina.stem, 'caracteres': len(texto.strip()), 'palabras': len(palabras),
                'fragmentos_duplicados': len(duplicados), 'ejemplos_duplicados': duplicados[:4],
                'sospechosas': len(sospechosas), 'tasa_sospechosas': round(len(sospechosas) / max(len(palabras), 1), 3),
                'lineas': len(lineas), 'confianza_media': round(st.mean(confianzas), 3) if confianzas else None,
                'lineas_dudosas': dudosas, 'ejemplos_sospechosos': sospechosas[:6]}
        informe['por_pagina'].append(fila)
        totales['caracteres'] += fila['caracteres']; totales['palabras'] += fila['palabras']
        totales['sospechosas'] += fila['sospechosas']; totales['lineas'] += fila['lineas']; totales['lineas_dudosas'] += dudosas

    informe['texto'] = {
        'caracteres': totales['caracteres'], 'palabras': totales['palabras'],
        'caracteres_por_pagina_mediana': st.median(f['caracteres'] for f in informe['por_pagina']) if paginas else 0,
        'paginas_casi_vacias': sum(1 for f in informe['por_pagina'] if f['caracteres'] < 100),
        'tasa_palabras_sospechosas': round(totales['sospechosas'] / max(totales['palabras'], 1), 4),
        'fragmentos_duplicados': sum(f['fragmentos_duplicados'] for f in informe['por_pagina']),
        'paginas_con_duplicados': [f['pagina'] for f in informe['por_pagina'] if f['fragmentos_duplicados']],
        'paginas_peores': sorted(informe['por_pagina'], key=lambda f: -f['tasa_sospechosas'])[:5],
    }
    if confianzas_todas:
        informe['ocr'] = {
            'lineas': totales['lineas'],
            'confianza_media': round(st.mean(confianzas_todas), 3),
            'confianza_mediana': round(st.median(confianzas_todas), 3),
            'lineas_dudosas': totales['lineas_dudosas'],
            'tasa_lineas_dudosas': round(totales['lineas_dudosas'] / max(totales['lineas'], 1), 4),
            'paginas_con_confianza_baja': [f['pagina'] for f in informe['por_pagina']
                                           if f['confianza_media'] is not None and f['confianza_media'] < 0.6],
        }
    (carpeta / 'indicadores.json').write_text(json.dumps(informe, indent=2, ensure_ascii=False), encoding='utf-8')

    print(f'Páginas: {informe["paginas"]}')
    for bloque in ('detector', 'ocr', 'texto'):
        if informe[bloque]:
            print(f'\n[{bloque}]')
            for clave, valor in informe[bloque].items():
                if clave == 'paginas_peores':
                    print('  páginas con más palabras sospechosas: ' + ', '.join(
                        f'{f["pagina"]} ({100 * f["tasa_sospechosas"]:.0f}%: {", ".join(f["ejemplos_sospechosos"][:3])})' for f in valor))
                else:
                    print(f'  {clave}: {valor}')
    print(f'\nDetalle por página en {carpeta / "indicadores.json"}')


principal()
