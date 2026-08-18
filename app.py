# Importing required libraries
import re
import io
import json
import time
import shutil
import asyncio
import subprocess
import sys
import wave
from pathlib import Path

import streamlit as st

from nucleo import estimacion, ollama_local

RAIZ = Path(__file__).resolve().parent
PASOS = RAIZ / 'pasos'
with open(RAIZ / 'config.json') as f:
    CONFIG = json.load(f)

IDIOMAS = {
    'Español': 'es', 'Inglés': 'en', 'Francés': 'fr', 'Italiano': 'it',
    'Portugués': 'pt', 'Alemán': 'de', 'Todos': ''
}

MUESTRAS = {
    'es': 'Esta es una muestra de mi voz leyendo un libro en voz alta.',
    'en': 'This is a sample of my voice reading a book out loud.',
    'fr': 'Voici un exemple de ma voix lisant un livre à voix haute.',
    'it': 'Questo è un esempio della mia voce mentre leggo un libro.',
    'pt': 'Esta é uma amostra da minha voz lendo um livro em voz alta.',
    'de': 'Dies ist eine Probe meiner Stimme beim Vorlesen eines Buches.'
}

st.set_page_config(page_title='audIAble', page_icon='🎧', layout='wide')


# ---------------------------------------------------------------- utilidades

# Function to run one of the pipeline scripts, streaming its output to the page
def ejecutar(comando, registro, titulo, barra=None, total=0, patron=None):
    registro.write(f'$ {" ".join(str(c) for c in comando)}')
    proceso = subprocess.Popen(
        [sys.executable, '-u'] + [str(c) for c in comando],
        cwd=RAIZ, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    lineas, hechos, inicio = [], 0, time.time()
    for linea in proceso.stdout:
        lineas.append(linea.rstrip())
        registro.code('\n'.join(lineas[-14:]), language='text')
        # cada línea que casa con el patrón es un elemento terminado: con eso se
        # mide el ritmo real y se proyecta cuánto falta de esta etapa
        if barra is not None and patron and re.search(patron, linea):
            hechos += 1
            if total:
                transcurrido = time.time() - inicio
                restante = transcurrido / hechos * max(total - hechos, 0)
                # el total es aproximado (p. ej. las partes de audio dependen del
                # troceado), así que la barra no se llena hasta acabar de verdad
                barra.progress(min(hechos / total, 0.95),
                               text=f'{titulo}: {hechos} de ~{total} · quedan ~{estimacion.formatear_duracion(restante)} de esta etapa')
            else:
                barra.progress(0.0, text=f'{titulo}: {hechos} elemento(s) procesados')
    proceso.wait()
    if proceso.returncode != 0:
        raise RuntimeError(f'{titulo} falló (código {proceso.returncode}):\n' + '\n'.join(lineas[-6:]))
    if barra is not None and total and hechos:
        barra.progress(1.0, text=f'{titulo}: {hechos} elemento(s) · etapa completada')
    return lineas


VOZ_SISTEMA = '(voz por defecto del sistema)'


# Function to find out how this machine can talk to Google: ADC, environment or
# the project credentials. Cached because the ADC probe can take a couple seconds
@st.cache_data(show_spinner=False, ttl=300)
def fuente_google():
    try:
        from nucleo import gcp
        return gcp.preparar_credenciales()
    except Exception:
        return None


# Function to ask Cloud Monitoring how much of the Vision free tier is left this
# month. Read only and free of charge; None when the query is not possible
@st.cache_data(show_spinner=False, ttl=300)
def vision_gratis_restantes():
    try:
        from nucleo import gcp
        usadas = gcp.paginas_vision_usadas()
        return max(0, CONFIG['Estimacion']['vision_imagenes_gratis'] - usadas), usadas
    except Exception:
        return None, None


# Function to render the Google credential state: a caption when ADC already
# gives access, and an input asking for the path to a JSON key when it does not
def bloque_credenciales_google(contenedor, clave):
    fuente = fuente_google()
    if fuente:
        contenedor.caption(f'✅ Credenciales de Google: {fuente}.')
        return None, True
    ruta = contenedor.text_input(
        'Ruta a tu llave JSON de Google', key=clave,
        help='No se encontró ADC. Pega la ruta de la llave de tu cuenta de servicio, '
             'o inicia sesión una vez con: gcloud auth application-default login'
    )
    if not ruta.strip():
        contenedor.error('Sin ADC ni llave JSON, este motor de Google no puede ejecutarse.')
        return None, False
    ruta_real = Path(ruta.strip()).expanduser()
    if not ruta_real.is_file():
        contenedor.error(f'No existe: {ruta_real}')
        return None, False
    contenedor.caption(f'✅ Se usará la llave: {ruta_real}')
    return str(ruta_real), True


# Function to list the installed Ollama models that fit a task, detected on the
# fly so the page never offers a model that is not there
@st.cache_data(show_spinner=False, ttl=60)
def modelos_ollama(tarea):
    try:
        return ollama_local.modelos_para(CONFIG['OllamaCleanup']['host'], tarea)
    except Exception:
        return []


# Function to draw a selector with the detected models, preselecting the one in
# config.json when it happens to be installed
def selector_modelo(contenedor, etiqueta, tarea, preferido, clave):
    disponibles = modelos_ollama(tarea)
    # con credenciales de Google resueltas, los Gemini de Vertex entran como
    # opción: mucho más rápidos que un modelo local, con coste por carácter
    if tarea in ('texto', 'figuras') and fuente_google():
        disponibles = disponibles + list(CONFIG['GoogleLLM']['models'])
    if not disponibles:
        contenedor.error('Ni Ollama responde ni hay credenciales de Google: no hay modelos disponibles.')
        return None
    indice = disponibles.index(preferido) if preferido in disponibles else 0
    return contenedor.selectbox(etiqueta, disponibles, index=indice, key=clave,
                                help='Los locales vienen de tu servidor de Ollama (gratis). Los gemini-* '
                                     'van a Google Vertex con tus credenciales: mucho más rápidos, '
                                     'con un coste pequeño por carácter que la estimación muestra.')


# Function to read which voice macOS is set to speak with, to show it next to
# the system voice option
@st.cache_data(show_spinner=False)
def voz_del_sistema():
    if sys.platform != 'darwin':
        return ''
    try:
        salida = subprocess.run(['defaults', 'read', 'com.apple.Accessibility',
                                 'SpokenContentDefaultVoiceSelectionsByLanguage'],
                                capture_output=True, text=True, timeout=5).stdout
        coincidencia = re.search(r'voiceId\s*=\s*"?([^";\n]+)"?', salida)
        return coincidencia.group(1).strip() if coincidencia else ''
    except Exception:
        return ''


# Function to list the macOS voices as (id, name, locale)
@st.cache_data(show_spinner=False)
def voces_mac():
    if sys.platform != 'darwin':
        return []
    salida = subprocess.run(['say', '-v', '?'], capture_output=True, text=True).stdout
    voces = []
    for linea in salida.splitlines():
        coincidencia = re.match(r'^(.+?)\s+([a-z]{2,3}[_-][A-Za-z0-9]{2,3})\s+#', linea)
        if coincidencia:
            voces.append((coincidencia.group(1).strip(), coincidencia.group(2)))
    return sorted(voces, key=lambda v: (v[1], v[0]))


# Function to list the Edge TTS voices as (id, locale)
@st.cache_data(show_spinner=False)
def voces_edge():
    try:
        import edge_tts
    except ImportError:
        return []
    voces = asyncio.run(edge_tts.list_voices())
    return sorted(((v['ShortName'], v['Locale']) for v in voces), key=lambda v: v[1])


# Function to keep only the voices of the chosen language
def filtrar_por_idioma(voces, idioma):
    if not idioma:
        return voces
    return [v for v in voces if v[1].replace('_', '-').lower().startswith(idioma)] or voces


# Function to generate a short sample so the voice can be judged by ear
def generar_demo(motor, voz, idioma, destino):
    texto = MUESTRAS.get(idioma or 'es', MUESTRAS['es'])
    if motor == 'Microsoft Edge':
        import edge_tts
        ajustes = CONFIG['EdgeTTS']
        asyncio.run(edge_tts.Communicate(texto, voz, rate=ajustes['rate'], volume=ajustes['volume'],
                                         pitch=ajustes['pitch']).save(str(destino)))
    else:
        ajustes = CONFIG['MacTTS']
        origen = destino.with_suffix('.txt')
        origen.write_text(texto, encoding='utf-8')
        comando = ['say', '-f', str(origen), '-o', str(destino)]
        if voz:
            comando[1:1] = ['-v', voz]
        if ajustes['data_format']:
            comando.append(f"--data-format={ajustes['data_format']}")
        subprocess.run(comando, check=True)
        origen.unlink(missing_ok=True)
    return destino


# Function to measure the real size of the job, cached so the estimate does not
# reopen the PDF on every interaction with the page
@st.cache_data(show_spinner=False)
def medir_volumen_cacheado(rutas, texto_paginas, marcas):
    return estimacion.medir_volumen([Path(r) for r in rutas], texto_paginas)


# Function to sort page files by their number
def orden_natural(ruta):
    numeros = re.findall(r'\d+', ruta.stem)
    return (int(numeros[-1]) if numeros else 0, ruta.stem)


# Function to write the cleaned text as a PDF, using the PDF library already in
# the project so no extra dependency is needed
def exportar_pdf(texto, destino):
    import fitz
    documento = fitz.open()
    ancho, alto, margen = 595, 842, 56
    caja = fitz.Rect(margen, margen, ancho - margen, alto - margen)
    pendiente = texto.strip() or ' '
    while pendiente:
        corte = min(len(pendiente), 2400)
        if corte < len(pendiente):
            espacio = pendiente.rfind(' ', 0, corte)
            corte = espacio if espacio > 0 else corte
        bloque, resto = pendiente[:corte], pendiente[corte:].lstrip()
        pagina = documento.new_page(width=ancho, height=alto)
        # un valor negativo significa que no cupo nada: se recorta y el sobrante
        # vuelve a la cola, para que la exportación nunca pierda texto en silencio
        while pagina.insert_textbox(caja, bloque, fontsize=11, fontname='helv', align=0) < 0 and len(bloque) > 200:
            recorte = bloque.rfind(' ', 0, int(len(bloque) * 0.9)) or len(bloque) // 2
            bloque, resto = bloque[:recorte], (bloque[recorte:] + ' ' + resto).strip()
        pendiente = resto
    documento.save(destino)
    documento.close()
    return destino


# Function to join audio parts into a single file per division
def unir_audios(rutas, destino):
    if destino.suffix == '.wav':
        with wave.open(str(rutas[0]), 'rb') as primera:
            parametros = primera.getparams()
        silencio = b'\x00' * (parametros.nchannels * parametros.sampwidth * int(parametros.framerate * 0.5))
        with wave.open(str(destino), 'wb') as salida:
            salida.setparams(parametros)
            for ruta in rutas:
                with wave.open(str(ruta), 'rb') as origen:
                    if origen.getparams()[:3] != parametros[:3]:
                        continue
                    salida.writeframes(origen.readframes(origen.getnframes()))
                salida.writeframes(silencio)
    else:
        with open(destino, 'wb') as salida:
            for ruta in rutas:
                salida.write(ruta.read_bytes())
    return destino


# ---------------------------------------------------------------- entrada

st.title('🎧 audIAble')
st.caption('De PDF escaneado a audiolibro: extracción, limpieza, corrección con LLM local y voz.')

st.header('1. Qué quieres procesar')
columna_a, columna_b = st.columns([1, 2])
with columna_a:
    tipo_entrada = st.radio('Origen', ['Archivo único', 'Carpeta completa'], key='tipo_entrada')
with columna_b:
    ruta_entrada = st.text_input(
        'Ruta del archivo' if tipo_entrada == 'Archivo único' else 'Ruta de la carpeta',
        value=str(RAIZ / 'vientosAlisios.txt.pdf') if tipo_entrada == 'Archivo único' else str(RAIZ),
        help='PDF o TXT. Un TXT se entiende como texto ya extraído, con OCR hecho o sin él.'
    )
    subido = st.file_uploader('…o sube un archivo', type=['pdf', 'txt'], key='subida')

entradas = []
origen = Path(ruta_entrada.strip()) if ruta_entrada.strip() else None
if subido is not None:
    destino_subida = RAIZ / 'trabajo' / 'entrada' / subido.name
    destino_subida.parent.mkdir(parents=True, exist_ok=True)
    destino_subida.write_bytes(subido.getbuffer())
    entradas = [destino_subida]
elif origen and origen.exists():
    if origen.is_dir():
        entradas = sorted(a for a in origen.iterdir() if a.suffix.lower() in ('.pdf', '.txt'))
    else:
        entradas = [origen]

if entradas:
    st.success(f'{len(entradas)} archivo(s): ' + ', '.join(e.name for e in entradas[:6]) + ('…' if len(entradas) > 6 else ''))
else:
    st.warning('Indica una ruta existente o sube un archivo.')

nombre_idioma = st.selectbox(
    'Idioma del libro', [n for n in IDIOMAS if n != 'Todos'], index=0,
    help='Guía todo lo que se genera: las descripciones de figuras y tablas, las instrucciones '
         'del corrector LLM y el filtrado de voces del paso 5.'
)
idioma = IDIOMAS[nombre_idioma]

hay_pdf = any(e.suffix.lower() == '.pdf' for e in entradas)
paginas = st.text_input('Páginas del PDF (1, 1-5, 2,7,9). Vacío = todas', value='1') if hay_pdf else ''

# ---------------------------------------------------------------- OCR

st.header('2. OCR')
st.caption('Un PDF con capa de texto no necesita OCR. Actívalo si el PDF es una imagen escaneada o si la capa de texto viene rota.')
usar_ocr = st.checkbox('Ejecutar OCR sobre las páginas', value=False)
motor_ocr, modelo_ocr, dpi = None, None, 300
llave_ocr, google_ocr_ok = None, True
gratis_vision = None
if usar_ocr:
    columna_a, columna_b, columna_c = st.columns(3)
    motores_ocr = (['macOS (Vision)'] if sys.platform == 'darwin' else []) + ['Ollama local', 'Google Cloud Vision']
    motor_ocr = columna_a.selectbox('Motor de OCR', motores_ocr)
    dpi = columna_b.number_input('Resolución de render (dpi)', 72, 600, 300, 50)
    if motor_ocr == 'macOS (Vision)':
        st.caption('El motor del sistema (el mismo de Vista Previa): gratis, local y sin depender de la red.')
    elif motor_ocr == 'Ollama local':
        modelo_ocr = selector_modelo(columna_c, 'Modelo de visión', 'ocr', CONFIG['OllamaOCR']['model'], 'modelo_ocr')
        st.info('En esta máquina los modelos de visión respondieron muy lentos y vacíos en mis pruebas. '
                'Si el OCR local se queda colgado, prueba con Google Cloud Vision.')
    else:
        llave_ocr, google_ocr_ok = bloque_credenciales_google(st, 'llave_ocr')
        if google_ocr_ok:
            gratis_vision, usadas_vision = vision_gratis_restantes()
            if gratis_vision is not None:
                st.caption(f'📊 Uso de Vision este mes: {usadas_vision} página(s); '
                           f'te quedan {gratis_vision} gratuitas de {CONFIG["Estimacion"]["vision_imagenes_gratis"]}.')
            else:
                st.caption('No se pudo consultar el uso de Vision (¿API de Monitoring sin habilitar?); '
                           'la estimación asume la franquicia completa.')

# ---------------------------------------------------------------- limpieza

describir_figuras = st.checkbox(
    'Avanzado: describir imágenes y tablas con el LLM', value=False,
    help='El narrador leerá una descripción generada por el LLM local donde aparezca cada figura o '
         'tabla, para que el audiolibro se entienda sin verlas. Con capa de texto, la descripción se '
         'inserta en su punto exacto de lectura; combinado con OCR, se inspecciona cada página '
         'escaneada y las descripciones se añaden al final de su página.'
)
modelo_figuras = None
if describir_figuras:
    columna_f, _ = st.columns([1, 2])
    modelo_figuras = selector_modelo(columna_f, 'Modelo para las figuras', 'figuras',
                                     CONFIG['Figuras']['model_vision'], 'modelo_figuras')

st.header('3. Limpieza del texto')
nivel = st.radio(
    'Nivel',
    ['Ninguna', 'Solo reglas deterministas', 'Solo corrección con LLM', 'Reglas + corrección con LLM'],
    index=3,
    help='Las reglas arreglan envoltura de líneas, guiones, abreviaturas y espacios. '
         'El LLM repara palabras rotas por el escaneo y frases entrelazadas. '
         '«Solo corrección con LLM» le pasa el texto extraído tal cual, sin reglas previas.'
)
usa_reglas = nivel in ('Solo reglas deterministas', 'Reglas + corrección con LLM')
usa_llm = nivel in ('Solo corrección con LLM', 'Reglas + corrección con LLM')
modelo_llm = CONFIG['OllamaCleanup']['model']
if usa_llm:
    columna_a, columna_b = st.columns(2)
    modelo_llm = selector_modelo(columna_a, 'Modelo de corrección', 'texto', modelo_llm, 'modelo_llm') or modelo_llm
    st.caption('Cada trozo corregido se valida contra el original: si el modelo inventa texto, se descarta y se conserva el trozo original.')

st.header('4. Guardar el texto limpio')
columna_a, columna_b = st.columns(2)
guardar_txt = columna_a.checkbox('TXT', value=True)
guardar_pdf = columna_b.checkbox('PDF', value=False)

# ---------------------------------------------------------------- voz

st.header('5. Voz')
generar_audio = st.checkbox(
    'Generar audio', value=True,
    help='Desmárcalo para quedarte solo con el escaneo y la limpieza: la salida será únicamente el texto en TXT o PDF.'
)

motor_tts = voz = None
llave_tts, google_tts_ok = None, True
if not generar_audio:
    st.caption('Sin audio: el pipeline se detiene después de la limpieza y entrega solo el texto.')

if generar_audio:
    columna_b, columna_c = st.columns([1, 2])
    columna_b.caption(f'Voces filtradas por el idioma del libro: {nombre_idioma}.')
    motor_tts = columna_b.selectbox('Motor de voz', ['Microsoft Edge', 'macOS local', 'Google Cloud'])

    if motor_tts == 'Microsoft Edge':
        disponibles = filtrar_por_idioma(voces_edge(), idioma)
    elif motor_tts == 'macOS local':
        disponibles = filtrar_por_idioma(voces_mac(), idioma)
    else:
        disponibles = [(CONFIG['TextToSpeechAPI']['voice']['text'], CONFIG['TextToSpeechAPI']['voice']['language_code'])]
        llave_tts, google_tts_ok = bloque_credenciales_google(st, 'llave_tts')

    opciones_voz = [v[0] for v in disponibles]
    if motor_tts == 'macOS local':
        opciones_voz = [VOZ_SISTEMA] + opciones_voz

    if opciones_voz:
        localidades = dict(disponibles)
        voz = columna_c.selectbox('Voz', opciones_voz,
                                  format_func=lambda v: v if v == VOZ_SISTEMA else f'{v}  ({localidades.get(v, "")})')
        if voz == VOZ_SISTEMA:
            actual = voz_del_sistema()
            columna_c.caption(f'Se llamará a say sin voz: hablará la de Ajustes del Sistema'
                              + (f' ({actual})' if actual else '') + '.')
    else:
        columna_c.warning('No hay voces disponibles para ese motor. Instala edge-tts o usa macOS.')

if generar_audio and voz and motor_tts != 'Google Cloud':
    if st.button('🔊 Escuchar demo de esta voz'):
        carpeta_demo = RAIZ / 'trabajo' / 'demos'
        carpeta_demo.mkdir(parents=True, exist_ok=True)
        extension = 'mp3' if motor_tts == 'Microsoft Edge' else 'wav'
        ruta_demo = carpeta_demo / f'{re.sub(r"[^A-Za-z0-9]+", "_", voz)}.{extension}'
        with st.spinner('Generando la muestra…'):
            try:
                generar_demo(motor_tts, None if voz == VOZ_SISTEMA else voz, idioma, ruta_demo)
                st.audio(str(ruta_demo))
            except Exception as error:
                st.error(f'No se pudo generar la muestra: {error}')

por_divisiones = False
if generar_audio:
    st.header('6. Formato del audio')
    formato_salida = st.radio(
        'Entrega',
        ['Un único archivo largo', 'Un archivo por división lógica (capítulos y secciones)'],
        help='Las divisiones las propone el LLM leyendo el comienzo de cada página; sin LLM se usan solo las reglas de títulos.'
    )
    por_divisiones = formato_salida.startswith('Un archivo por')

if not generar_audio and not (guardar_txt or guardar_pdf):
    st.warning('Sin audio y sin TXT ni PDF no se produciría ningún archivo: marca al menos un formato en el paso 4.')

# ---------------------------------------------------------------- ejecución

total_paginas = total_caracteres = 0
st.header('7. Estimación')
if entradas:
    try:
        marcas = tuple(Path(e).stat().st_mtime for e in entradas)
        total_paginas, total_caracteres = medir_volumen_cacheado(tuple(str(e) for e in entradas), paginas, marcas)
        calculo = estimacion.estimar(
            total_paginas, total_caracteres,
            usar_ocr=usar_ocr, motor_ocr=motor_ocr, nivel_limpieza=nivel,
            motor_tts=motor_tts if (generar_audio and voz) else None,
            por_divisiones=por_divisiones, voz_gcp=voz, vision_gratis=gratis_vision,
            describir_figuras=describir_figuras, llm_modelo=modelo_llm, figuras_modelo=modelo_figuras
        )
        columna_a, columna_b, columna_c, columna_d = st.columns(4)
        columna_a.metric('Volumen', f'{total_paginas} pág', f'{total_caracteres:,} caracteres'.replace(',', '.'))
        columna_b.metric('Tiempo de proceso', estimacion.formatear_duracion(calculo['segundos']))
        texto_coste = 'Gratis' if not calculo['coste'] else (
            f"${calculo['coste']:.2f}" if calculo['coste'] >= 0.01 else f"${calculo['coste']:.3f}")
        columna_c.metric('Coste', texto_coste)
        columna_d.metric('Audio resultante', estimacion.formatear_duracion(calculo['audio_segundos']))

        st.dataframe(
            [{'Etapa': e['etapa'], 'Tiempo': estimacion.formatear_duracion(e['segundos']),
              'Coste': f"${e['coste']:.4f}" if e['coste'] else '-', 'Detalle': e['detalle']}
             for e in calculo['etapas']],
            hide_index=True, use_container_width=True
        )
        if hay_pdf and not usar_ocr and total_paginas and total_caracteres < total_paginas * 20:
            st.error('Este PDF apenas tiene capa de texto: parece un escaneo puro. '
                     'Sin OCR, la extracción saldrá vacía y no habrá nada que limpiar ni leer. '
                     'Activa «Ejecutar OCR» en el paso 2.')
        if calculo['coste']:
            st.warning(f"Esta configuración factura unos {texto_coste} en tu cuenta de Google Cloud. "
                       'Los motores Edge y macOS hacen el mismo trabajo gratis.')
        if calculo['segundos'] > 3600:
            st.info('Más de una hora de proceso. Puedes empezar por unas pocas páginas para validar el resultado antes de lanzar el libro entero.')
        st.caption('Estimación a partir de los ritmos medidos en esta máquina, guardados en config.json '
                   '(sección Estimacion) por si quieres recalibrarlos.')
    except Exception as error:
        st.info(f'No se pudo calcular la estimación: {error}')
else:
    st.caption('Elige una entrada para ver la estimación.')

st.header('8. Ejecutar')
carpeta_trabajo = Path(st.text_input('Carpeta de salida', value=str(RAIZ / 'trabajo' / 'salida')))
empezar_de_cero = st.checkbox(
    'Empezar de cero (vacía la carpeta de salida antes de ejecutar)', value=True,
    help='Evita mezclar este libro con los restos de una corrida anterior: las etapas saltan '
         'los archivos que ya existen, así que los artefactos viejos contaminan al libro nuevo. '
         'Desmárcalo solo para reanudar una corrida interrumpida del MISMO libro.'
)


# Function to empty the working folder so a new book never inherits the pages,
# audio or reports of the previous one
def vaciar_salida(carpeta):
    if carpeta.exists():
        shutil.rmtree(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)

faltan_condiciones = (not entradas
                      or (generar_audio and not voz)
                      or (not generar_audio and not (guardar_txt or guardar_pdf))
                      or (usar_ocr and motor_ocr == 'Google Cloud Vision' and not google_ocr_ok)
                      or (generar_audio and motor_tts == 'Google Cloud' and not google_tts_ok))
if st.button('▶️ Ejecutar el pipeline', type='primary', disabled=faltan_condiciones):
    registro = st.empty()
    barra = st.progress(0.0, text='Preparando…')
    try:
        if empezar_de_cero:
            vaciar_salida(carpeta_trabajo)
        carpeta_trabajo.mkdir(parents=True, exist_ok=True)
        carpeta_txt = carpeta_trabajo / 'texto'
        carpeta_txt.mkdir(parents=True, exist_ok=True)

        with st.status('Ejecutando…', expanded=True) as estado:
            # --- extracción
            estado.update(label='Extrayendo el texto')
            for entrada in entradas:
                if entrada.suffix.lower() == '.txt':
                    shutil.copy(entrada, carpeta_txt / entrada.name)
                elif usar_ocr:
                    carpeta_img = carpeta_trabajo / 'imagenes'
                    comando = [str(PASOS / 'pre-pdf.py'), '--f', entrada, '--o', carpeta_img, '--m', 'photo', '--dpi', dpi]
                    if paginas.strip():
                        comando += ['--p', paginas.strip()]
                    ejecutar(comando, registro, 'Render de páginas')
                    if motor_ocr == 'macOS (Vision)':
                        ejecutar([str(PASOS / 'pro-mac-ocr.py'), '--f', carpeta_img, '--o', carpeta_txt, '--idioma', idioma or 'es'],
                                 registro, 'OCR de macOS', barra, total_paginas, r'caracteres,')
                    elif motor_ocr == 'Ollama local':
                        ejecutar([str(PASOS / 'pro-ollama-ocr.py'), '--f', carpeta_img, '--o', carpeta_txt, '--m', modelo_ocr],
                                 registro, 'OCR local', barra, total_paginas, r'caracteres,')
                    else:
                        comando_ocr = [str(PASOS / 'pro-gcp-ocr.py'), '--f', carpeta_img, '--o', carpeta_txt]
                        if llave_ocr:
                            comando_ocr += ['--cred', llave_ocr]
                        ejecutar(comando_ocr, registro, 'OCR de Google', barra, total_paginas, r'\.txt')
                    if describir_figuras:
                        estado.update(label='Buscando y describiendo figuras en las páginas escaneadas')
                        comando_fig = [str(PASOS / 'pre-figuras.py'), '--img', carpeta_img, '--o', carpeta_txt, '--idioma', idioma or 'es']
                        if modelo_figuras:
                            comando_fig += ['--mv', modelo_figuras, '--mt', modelo_figuras]
                        ejecutar(comando_fig, registro, 'Descripción de figuras', barra, total_paginas, r'\(\d+s\)')
                elif describir_figuras:
                    comando = [str(PASOS / 'pre-figuras.py'), '--f', entrada, '--o', carpeta_txt, '--idioma', idioma or 'es']
                    if modelo_figuras:
                        comando += ['--mv', modelo_figuras, '--mt', modelo_figuras]
                    if paginas.strip():
                        comando += ['--p', paginas.strip()]
                    ejecutar(comando, registro, 'Extracción con descripciones', barra, total_paginas, r'tabla\(s\)')
                else:
                    comando = [str(PASOS / 'pre-pdf.py'), '--f', entrada, '--o', carpeta_txt, '--m', 'split']
                    if paginas.strip():
                        comando += ['--p', paginas.strip()]
                    ejecutar(comando, registro, 'Extracción de texto', barra, total_paginas, r'extracted and saved')

            # --- guardarraíl: si la extracción salió vacía, parar aquí con causa
            paginas_extraidas = [a for a in carpeta_txt.iterdir() if a.suffix == '.txt' and 'cambios' not in a.name]
            extraido = sum(len(a.read_text(encoding='utf-8', errors='ignore').strip()) for a in paginas_extraidas)
            if not paginas_extraidas or extraido < max(len(paginas_extraidas), 1) * 20:
                raise RuntimeError(
                    f'La extracción produjo {len(paginas_extraidas)} página(s) con solo {extraido} caracteres en total. '
                    'Este PDF no tiene capa de texto utilizable: es un escaneo. '
                    'Vuelve al paso 2 y activa «Ejecutar OCR» para leer las páginas como imágenes.')

            # --- limpieza
            if usa_reglas:
                estado.update(label='Limpiando con reglas deterministas')
                ejecutar([str(PASOS / 'pre-cleanup.py'), '--f', carpeta_txt, '--idioma', idioma or 'es'],
                         registro, 'Limpieza', barra, total_paginas, r'caracteres\)')
            if usa_llm:
                estado.update(label='Corrigiendo el escaneado con el LLM local (puede tardar)')
                ejecutar([str(PASOS / 'pre-ollama.py'), '--f', carpeta_txt, '--m', modelo_llm, '--idioma', idioma or 'es'],
                         registro, 'Corrección con LLM', barra, total_paginas, r'(informe|se salta)')

            # --- divisiones
            divisiones = None
            if generar_audio and por_divisiones:
                estado.update(label='Buscando capítulos y secciones')
                comando = [str(PASOS / 'pre-capitulos.py'), '--f', carpeta_txt, '--o', carpeta_trabajo / 'divisiones.json', '--m', modelo_llm]
                if not usa_llm:
                    comando.append('--sinllm')
                ejecutar(comando, registro, 'Detección de capítulos')
                divisiones = json.loads((carpeta_trabajo / 'divisiones.json').read_text(encoding='utf-8'))

            # --- exportación del texto
            estado.update(label='Guardando el texto limpio')
            paginas_txt = sorted((a for a in carpeta_txt.iterdir() if a.suffix == '.txt' and 'cambios' not in a.name), key=orden_natural)
            texto_completo = '\n\n'.join(a.read_text(encoding='utf-8') for a in paginas_txt)
            if guardar_txt:
                (carpeta_trabajo / 'texto_limpio.txt').write_text(texto_completo, encoding='utf-8')
            if guardar_pdf:
                exportar_pdf(texto_completo, carpeta_trabajo / 'texto_limpio.pdf')

            # --- audio
            entregas = []
            if generar_audio:
                estado.update(label='Generando el audio')
                carpeta_audio = carpeta_trabajo / 'audio'
                guiones = {'Microsoft Edge': 'pro-edge-tts.py', 'macOS local': 'pro-mac-tts.py', 'Google Cloud': 'pro-gcp-tts.py'}
                comando = [str(PASOS / guiones[motor_tts]), '--f', carpeta_txt, '--o', carpeta_audio]
                if motor_tts != 'Google Cloud' and voz != VOZ_SISTEMA:
                    comando += ['--v', voz]
                if motor_tts == 'Google Cloud' and llave_tts:
                    comando += ['--cred', llave_tts]
                ejecutar(comando, registro, 'Síntesis de voz', barra,
                         max(1, round(total_caracteres / 4500)), r'characters\)')

                extension = 'mp3' if motor_tts == 'Microsoft Edge' else 'wav'
                # se descarta el audio que una corrida anterior pudiera haber generado
                # a partir de un informe de cambios, que no es texto del libro
                partes = sorted((p for p in carpeta_audio.glob(f'*.{extension}') if '.cambios' not in p.name),
                                key=orden_natural)
                if por_divisiones and divisiones:
                    for division in divisiones:
                        nombres = {Path(a).stem for a in division['archivos']}
                        trozos = [p for p in partes if re.sub(r'_\d+$', '', p.stem) in nombres]
                        if trozos:
                            seguro = re.sub(r'[^\w\-]+', '_', division['titulo']).strip('_') or 'parte'
                            entregas.append(unir_audios(trozos, carpeta_trabajo / f'{seguro}.{extension}'))
                if not entregas:
                    entregas = [unir_audios(partes, carpeta_trabajo / f'audiolibro.{extension}')] if partes else []

            estado.update(label='Listo', state='complete')

        st.subheader('Resultados')
        for entrega in entregas:
            st.write(f'**{entrega.name}**')
            st.audio(str(entrega))
            st.download_button(f'Descargar {entrega.name}', entrega.read_bytes(), entrega.name, key=str(entrega))
        for extra in ['texto_limpio.txt', 'texto_limpio.pdf']:
            ruta = carpeta_trabajo / extra
            if ruta.exists():
                st.download_button(f'Descargar {extra}', ruta.read_bytes(), extra, key=extra)
        st.info(f'Todos los archivos intermedios están en {carpeta_trabajo}')

    except Exception as error:
        st.error(str(error))
