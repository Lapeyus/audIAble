# Importing required libraries
import json
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
with open(RAIZ / 'config.json') as f:
    CONFIG = json.load(f)

RITMOS = CONFIG['Estimacion']
EXTENSIONES_VIDEO = ('.mp4', '.mov', '.m4v', '.avi', '.mkv', '.webm')

# Function to read how long a video lasts, in seconds
def duracion_video(ruta):
    import cv2
    captura = cv2.VideoCapture(str(ruta))
    try:
        fotogramas = captura.get(cv2.CAP_PROP_FRAME_COUNT)
        fps = captura.get(cv2.CAP_PROP_FPS) or 30
    finally:
        captura.release()
    return fotogramas / fps if fotogramas > 0 else 0

# Function to turn the pages argument of pre-pdf.py into a list of indexes
def parsear_paginas(texto_paginas, total):
    texto_paginas = (texto_paginas or '').strip()
    if not texto_paginas:
        return list(range(total))
    indices = []
    for pieza in texto_paginas.split(','):
        pieza = pieza.strip()
        if '-' in pieza:
            inicio, fin = (int(p) for p in pieza.split('-', 1))
            indices += list(range(inicio - 1, fin))
        elif pieza:
            indices.append(int(pieza) - 1)
    return [i for i in indices if 0 <= i < total]

# Function to measure the real volume of the job before running it, so the
# estimate is built on the actual characters instead of on an average page.
# A video cannot be measured until its pages are detected, so it is guessed
# from its length: one page every few seconds, with an average page of text
def medir_volumen(entradas, texto_paginas=''):
    paginas = caracteres = 0
    for entrada in entradas:
        entrada = Path(entrada)
        if entrada.suffix.lower() == '.txt':
            paginas += 1
            caracteres += len(entrada.read_text(encoding='utf-8', errors='ignore'))
        elif entrada.suffix.lower() in EXTENSIONES_VIDEO:
            estimadas = max(1, round(duracion_video(entrada) / RITMOS['video_s_por_pagina']))
            paginas += estimadas
            caracteres += estimadas * RITMOS['video_caracteres_por_pagina']
        elif entrada.suffix.lower() == '.pdf':
            import fitz
            with fitz.open(entrada) as documento:
                indices = parsear_paginas(texto_paginas, len(documento))
                paginas += len(indices)
                caracteres += sum(len(documento[i].get_text()) for i in indices)
    return paginas, caracteres

# Function to estimate what each chosen stage will take and cost. Every rate
# comes from config.json so it can be recalibrated on another machine
def estimar(paginas, caracteres, usar_ocr=False, motor_ocr=None, nivel_limpieza='Ninguna',
            motor_tts=None, por_divisiones=False, voz_gcp=None, vision_gratis=None,
            describir_figuras=False, llm_modelo=None, figuras_modelo=None, video_segundos=0):
    etapas = []

    def agregar(nombre, segundos, coste=0.0, detalle=''):
        etapas.append({'etapa': nombre, 'segundos': segundos, 'coste': coste, 'detalle': detalle})

    if video_segundos:
        agregar('Detección de páginas en el vídeo', video_segundos * RITMOS['video_proceso_por_segundo'], 0.0,
                f'{video_segundos:.0f} s de vídeo, ~{paginas} pág')
    if usar_ocr and not video_segundos:
        agregar('Render de páginas', paginas * RITMOS['render_s_por_pagina'], 0.0, f'{paginas} pág')
    if usar_ocr:
        if motor_ocr == 'macOS (Vision)':
            agregar('OCR de macOS (Vision)', paginas * RITMOS['ocr_mac_s_por_pagina'], 0.0,
                    f'{paginas} pág, gratis y local')
        elif motor_ocr == 'Ollama local':
            agregar('OCR local', paginas * RITMOS['ocr_local_s_por_pagina'], 0.0,
                    f'{paginas} pág, muy lento en esta máquina')
        else:
            # la franquicia puede venir consultada en vivo; si no, la del config
            gratis = RITMOS['vision_imagenes_gratis'] if vision_gratis is None else vision_gratis
            imagenes_cobradas = max(0, paginas - gratis)
            coste = imagenes_cobradas / 1000 * RITMOS['vision_usd_por_1000']
            agregar('OCR de Google Vision', paginas * RITMOS['ocr_gcp_s_por_pagina'], coste,
                    f'{imagenes_cobradas} de {paginas} pág facturables'
                    + ('' if vision_gratis is None else f', {vision_gratis} gratis restantes este mes'))
    if not usar_ocr:
        agregar('Extracción de texto', paginas * RITMOS['extraccion_s_por_pagina'], 0.0, f'{paginas} pág')

    if describir_figuras:
        if figuras_modelo and figuras_modelo.startswith('gemini'):
            agregar('Descripción de figuras', paginas * RITMOS['figuras_gemini_s_por_pagina'],
                    paginas * CONFIG['GoogleLLM']['usd_por_imagen'],
                    f'{paginas} pág con {figuras_modelo}, aproximado')
        else:
            agregar('Descripción de figuras', paginas * RITMOS['figuras_s_por_pagina'], 0.0,
                    f'{paginas} pág, aproximado: depende de cuántas figuras haya')

    if nivel_limpieza in ('Solo reglas deterministas', 'Reglas + corrección con LLM'):
        agregar('Limpieza determinista', caracteres / RITMOS['limpieza_caracteres_s'], 0.0, f'{caracteres} car')

    if nivel_limpieza in ('Solo corrección con LLM', 'Reglas + corrección con LLM'):
        if llm_modelo and llm_modelo.startswith('gemini'):
            precio = CONFIG['GoogleLLM']['usd_por_1000_car'].get(llm_modelo, 0.0007)
            agregar('Corrección con LLM', caracteres / RITMOS['llm_gemini_caracteres_s'],
                    caracteres / 1000 * precio,
                    f'{caracteres} car con {llm_modelo} en Vertex')
        else:
            agregar('Corrección con LLM', caracteres / RITMOS['llm_caracteres_s'], 0.0,
                    f'{caracteres} car a {RITMOS["llm_caracteres_s"]} car/s, la etapa más variable')

    if por_divisiones:
        con_llm = nivel_limpieza in ('Solo corrección con LLM', 'Reglas + corrección con LLM')
        ritmo = RITMOS['capitulos_s_por_pagina'] if con_llm else 0.01
        agregar('Detección de capítulos', paginas * ritmo, 0.0,
                f'{paginas} pág' + ('' if con_llm else ', solo reglas'))

    if motor_tts:
        claves = {'Microsoft Edge': 'tts_edge_caracteres_s', 'macOS local': 'tts_mac_caracteres_s',
                  'Google Cloud': 'tts_gcp_caracteres_s'}
        segundos = caracteres / RITMOS[claves[motor_tts]]
        coste = 0.0
        detalle = f'{caracteres} car, gratis'
        if motor_tts == 'Google Cloud':
            voz = voz_gcp or CONFIG['TextToSpeechAPI']['voice']['text']
            tipo = voz.split('-')[2] if len(voz.split('-')) > 2 else ''
            precio = next((v for k, v in CONFIG['TextToSpeechAPI']['Pricing'].items() if k.lower() == tipo.lower()), 0)
            coste = caracteres * precio
            detalle = f'{caracteres} car, voz {tipo or "?"} a {precio}/car'
        agregar('Síntesis de voz', segundos, coste, detalle)

    total_segundos = sum(e['segundos'] for e in etapas)
    total_coste = sum(e['coste'] for e in etapas)
    duracion_audio = caracteres / RITMOS['audio_caracteres_s'] if motor_tts else 0
    return {'etapas': etapas, 'segundos': total_segundos, 'coste': total_coste, 'audio_segundos': duracion_audio}

# Function to write a duration the way a person reads it
def formatear_duracion(segundos):
    segundos = int(round(segundos))
    if segundos < 60:
        return f'{segundos} s'
    if segundos < 3600:
        return f'{segundos // 60} min {segundos % 60:02d} s'
    return f'{segundos // 3600} h {(segundos % 3600) // 60:02d} min'
