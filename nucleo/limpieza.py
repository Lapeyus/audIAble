# Importing required libraries
import re
import unicodedata

# Characters that a PDF text layer drags along and a TTS engine reads badly
SUSTITUCIONES = {
    ' ': ' ', ' ': ' ', ' ': ' ',       # non breaking spaces
    'ﬀ': 'ff', 'ﬁ': 'fi', 'ﬂ': 'fl',    # ligatures
    'ﬃ': 'ffi', 'ﬄ': 'ffl',
    '‘': "'", '’': "'", '‚': "'",       # curly quotes
    '“': '"', '”': '"', '„': '"',
    '…': '...', '­': '',                     # ellipsis, soft hyphen
    '​': '', '﻿': ''                         # zero width, BOM
}

# Abbreviations a TTS engine spells out or mispronounces, one table per
# language. The symbols also differ: "&" is "y" in Spanish and "and" in English
ABREVIATURAS = {
    'es': [
        (r'\bEE\.?\s?UU\b', 'Estados Unidos'),
        (r'\bEE\.\s?VV\b', 'Estados Unidos'),
        (r'\betc\.(?=\s+[A-ZÁÉÍÓÚ¿¡])', 'etcétera.'),
        (r'\betc\.', 'etcétera'),
        (r'\bSr\.', 'señor'), (r'\bSra\.', 'señora'), (r'\bSrta\.', 'señorita'),
        (r'\bDr\.', 'doctor'), (r'\bDra\.', 'doctora'),
        (r'\bpágs\.', 'páginas'), (r'\bpág\.', 'página'), (r'\bnúm\.', 'número'),
        (r'\bp\.\s?ej\.', 'por ejemplo'), (r'\bej\.', 'ejemplo'),
        (r'\bAvda\.', 'avenida'), (r'\bcap\.', 'capítulo'),
        (r'\be\.\s?g\.,?', 'por ejemplo'), (r'\bi\.\s?e\.,?', 'es decir')
    ],
    'en': [
        (r'\bMr\.', 'Mister'), (r'\bMrs\.', 'Missus'), (r'\bMs\.', 'Miss'),
        (r'\bDr\.', 'Doctor'), (r'\bProf\.', 'Professor'),
        (r'\bCapt\.', 'Captain'), (r'\bCol\.', 'Colonel'), (r'\bGen\.', 'General'),
        (r'\bLt\.', 'Lieutenant'), (r'\bSgt\.', 'Sergeant'), (r'\bRev\.', 'Reverend'),
        (r'\bJr\.', 'Junior'), (r'\bSr\.', 'Senior'),
        # St. is Saint before a capitalized name and Street after an address
        (r'\bSt\.(?=\s?[A-Z])', 'Saint'), (r'\bSt\.', 'Street'),
        (r'\bMt\.', 'Mount'), (r'\bAve\.', 'Avenue'), (r'\bBlvd\.', 'Boulevard'),
        (r'\bU\.\s?S\.\s?A\.', 'United States'), (r'\bU\.\s?S\.', 'United States'),
        (r'\bU\.\s?K\.', 'United Kingdom'),
        (r'\betc\.(?=\s+[A-Z])', 'et cetera.'), (r'\betc\.', 'et cetera'),
        (r'\bvs\.', 'versus'), (r'\bapprox\.', 'approximately'), (r'\bDept\.', 'Department'),
        (r'\bpp\.(?=\s?\d)', 'pages'), (r'\bp\.(?=\s?\d)', 'page'), (r'\bNo\.(?=\s?\d)', 'Number'),
        (r'\be\.\s?g\.,?', 'for example'), (r'\bi\.\s?e\.,?', 'that is')
    ]
}

SIMBOLOS = {
    'es': {'&': ' y ', '%': ' por ciento'},
    'en': {'&': ' and ', '%': ' percent'}
}

# Words that never end a complete sentence: a line break right after one of
# them is the wrap of the PDF, not a pause the author wanted
_CONECTORES = {
    'de', 'del', 'la', 'el', 'los', 'las', 'un', 'una', 'unos', 'unas', 'y', 'e', 'o', 'u',
    'a', 'al', 'en', 'con', 'sin', 'por', 'para', 'que', 'se', 'su', 'sus', 'mi', 'tu', 'lo',
    'ni', 'como', 'más', 'muy', 'les', 'nos', 'me', 'te', 'es', 'era', 'fue', 'ha', 'han',
    'the', 'of', 'and', 'to', 'in', 'on', 'at', 'with', 'for', 'from', 'by', 'or', 'an',
    'is', 'are', 'was', 'were', 'has', 'have', 'had', 'be', 'been', 'their', 'its', 'this',
    'that', 'these', 'those', 'as', 'but', 'not', 'his', 'her', 'my', 'your', 'our', 'so'
}

_TERMINALES = ('.', '!', '?', '…', ':', ';', '»', '"')

# Lines that open with these words are headings no matter their length
_TITULO = re.compile(
    r'^(\d+(\.\d+)*\s+\S|(cap[íi]tulo|chapter|parte|part|libro|book|secci[óo]n|section|'
    r'd[íi]a|day|figura|figure|tabla|table|pr[óo]logo|ep[íi]logo|prologue|epilogue|'
    r'[íi]ndice|index|contents|ap[ée]ndice|appendix|unidad|unit|lecci[óo]n|lesson|'
    r'acto|act|escena|scene)\b)', re.IGNORECASE)


# Function to decide whether a piece of text has the shape of a heading, a
# caption or an attribution: something the listener needs separated by a pause
def _es_estructural(actual, ancho):
    palabras = actual.split()
    if not palabras:
        return False
    ultima = re.sub(r'\W+$', '', palabras[-1])
    if ultima.lower() in _CONECTORES:
        return False
    # un encabezado con palabra clave o numeración de sección lo es siempre
    if _TITULO.match(actual):
        return True
    # una línea entera en mayúsculas, si no es una fórmula de letras sueltas
    if actual.isupper():
        return (len(palabras) <= 8
                and not any(len(re.sub(r'\W+', '', p)) == 1 for p in palabras)
                and any(len(p) >= 3 for p in palabras))
    # una línea corta con forma de atribución: empieza y termina en mayúscula,
    # cifra o paréntesis ("William Wallace (Braveheart)"), nunca prosa como
    # "Y sin embargo el viejo", cuya última palabra va en minúscula
    return ((actual[:1].isupper() or actual[:1].isdigit() or actual[:1] in '«"(')
            and len(actual) < max(24, ancho * 0.6) and len(palabras) <= 6
            and (ultima[:1].isupper() or ultima[:1].isdigit() or actual.endswith(')')))


# Function to keep the line breaks that carry meaning and make sure each kept
# line ends in a full stop, so the TTS pauses instead of reading everything in
# one breath. A hard-wrapped line of prose still joins with the next one: only
# a line with the shape of a heading, a quote or an attribution is preserved
def puntuar_lineas(texto):
    resultado = []
    for parrafo in re.split(r'\n\s*\n', texto):
        lineas = [linea.strip() for linea in parrafo.split('\n') if linea.strip()]
        if not lineas:
            continue
        if len(lineas) == 1:
            resultado.append(lineas[0])
            continue

        ancho = max(len(linea) for linea in lineas)
        piezas, actual = [], ''
        for indice, linea in enumerate(lineas):
            actual = f'{actual} {linea}'.strip() if actual else linea
            if indice == len(lineas) - 1:
                piezas.append(actual)
                break
            siguiente = lineas[indice + 1]

            # la puerta de la regla: solo si el renglón siguiente arranca en
            # mayúscula (o cifra, apertura o raya de diálogo) puede haber corte.
            # Si arranca en minúscula la frase continúa abajo, aunque la línea
            # termine en un punto: ese punto suele ser el guion de corte de una
            # palabra partida que el OCR leyó mal, y se retira al unir
            if not (siguiente[:1].isupper() or siguiente[:1].isdigit() or siguiente[:1] in '«"¿¡(—'):
                if re.search(r'\w\.$', actual) and not actual.endswith(('...', '….')):
                    actual = actual[:-1]
                continue

            if actual.endswith(_TERMINALES):
                # la oración ya está rematada: el cambio de línea se conserva
                piezas.append(actual)
                actual = ''
                continue
            if actual.endswith((',', '-', '‐', '‑', '–')):
                continue
            if _es_estructural(actual, ancho):
                piezas.append(actual + '.')
                actual = ''
        resultado.append('\n\n'.join(piezas))
    return '\n\n'.join(resultado)


# Function to strip HTML and normalize the characters of the text layer
def normalizar_caracteres(texto):
    # bs4 se importa aquí para que los scripts que no limpian HTML no lo requieran
    from bs4 import BeautifulSoup
    texto = BeautifulSoup(texto, 'html.parser').get_text()
    texto = unicodedata.normalize('NFC', texto)
    for origen, destino in SUSTITUCIONES.items():
        texto = texto.replace(origen, destino)
    return texto

# Function to drop the page numbers the extractor leaves on their own line
def quitar_numeros_pagina(texto):
    lineas = [l for l in texto.split('\n') if not re.fullmatch(r'\s*[\dIVXLCivxlc]{1,6}\s*', l)]
    return '\n'.join(lineas)

# Function to undo the hard wrapping of the PDF, keeping real paragraphs.
# Words cut by a hyphen at the end of a line are joined back together
def desenvolver_lineas(texto):
    texto = re.sub(r'(\w)[-‐‑]\s*\n\s*(\w)', r'\1\2', texto)
    texto = re.sub(r'\n\s*\n+', '\x00', texto)
    texto = re.sub(r'\s*\n\s*', ' ', texto)
    return texto.replace('\x00', '\n\n')

# Function to sort out the hyphens and dashes. A hyphen stuck to the previous
# word is a word the scanner broke in two; a dash surrounded by spaces is a
# Spanish inciso or a dialogue mark, which reads better as a comma or as nothing
def arreglar_guiones(texto):
    # A matched pair of dashes is an inciso, and both ends become commas. This
    # has to run before the broken word rule, because "dijo -sin mirarme- que"
    # and "fa- llones" look the same to it
    texto = re.sub(r'(?<=\s)[-‐‑–—]\s*([^-‐‑–—\n]{1,120}?)\s*[-‐‑–—](?=[\s.,;:!?])', r', \1,', texto)
    texto = re.sub(r'(\w)[-‐‑]\s+(\w)', r'\1\2', texto)
    texto = re.sub(r'(?m)^[ \t]*[-‐‑–—][ \t]*', '', texto)
    texto = re.sub(r'(\w)\s*[-‐‑–—](?=\s*[.,;:!?])', r'\1', texto)
    texto = re.sub(r'(?<=\s)[-‐‑–—]\s*(?=\w)', ', ', texto)
    texto = re.sub(r'(\w)[–—](?=\s)', r'\1,', texto)
    return texto

# Function to drop markdown emphasis, which a TTS engine pronounces
def quitar_markdown(texto):
    texto = re.sub(r'\*\*([^*\n]+)\*\*', r'\1', texto)
    texto = re.sub(r'(?<!\w)\*([^*\n]+)\*(?!\w)', r'\1', texto)
    texto = re.sub(r'(?<!\w)_([^_\n]+)_(?!\w)', r'\1', texto)
    texto = re.sub(r'(?m)^#{1,6}\s+', '', texto)
    return texto


# Function to expand the abbreviations a TTS engine cannot read out loud. For a
# language without its own table only the text survives untouched, which is safe
def expandir_abreviaturas(texto, idioma='es'):
    for patron, reemplazo in ABREVIATURAS.get(idioma, []):
        texto = re.sub(patron, reemplazo, texto)
    for simbolo, palabra in SIMBOLOS.get(idioma, {}).items():
        texto = texto.replace(simbolo, palabra)
    return texto

# Function to tidy up the spacing and the punctuation left by the rules above
def normalizar_espacios(texto):
    texto = re.sub(r'[ \t]+', ' ', texto)
    texto = re.sub(r'\s+([,;:.!?])', r'\1', texto)
    texto = re.sub(r'([,;:])(?=\w)', r'\1 ', texto)
    texto = re.sub(r',\s*,+', ',', texto)
    texto = re.sub(r',\s*([.;:!?])', r'\1', texto)
    texto = re.sub(r'\(\s*\)', '', texto)
    texto = re.sub(r'\n{3,}', '\n\n', texto)
    return '\n\n'.join(p.strip() for p in texto.split('\n\n') if p.strip()) + '\n'

# Function to collapse the degenerate repetition a model falls into when it
# loops: the same word or the same sentence over and over. It arrives from OCR
# or from a correction, and read out loud it becomes minutes of one word
def colapsar_repeticiones(texto, maximo=3):
    texto = re.sub(r'(?i)(\b\S{2,}\b)(\s+\1\b){' + str(maximo) + r',}', r'\1', texto)
    # la deduplicación de frases va párrafo a párrafo, para no aplastar los
    # saltos de línea que puntuar_lineas decidió conservar
    parrafos = []
    for parrafo in texto.split('\n\n'):
        frases, previa, salida = re.split(r'(?<=[.!?…])\s+', parrafo), None, []
        for frase in frases:
            clave = re.sub(r'\W+', '', frase.lower())
            if clave and clave == previa:
                continue
            previa = clave
            salida.append(frase)
        parrafos.append(' '.join(salida))
    return '\n\n'.join(parrafos)


# Function to remove the whitespace a TTS engine turns into pauses. Inside a
# paragraph every line break is just how the PDF or the model wrapped the text,
# so it becomes a space; only an empty line survives, as the paragraph break
def normalizar_pausas(texto):
    texto = texto.replace('\r\n', '\n').replace('\r', '\n')
    texto = re.sub(r'[ \t\u00a0]+', ' ', texto)
    texto = '\n'.join(linea.strip() for linea in texto.split('\n'))
    texto = re.sub(r'\n{2,}', '\x00', texto)
    texto = texto.replace('\n', ' ')
    texto = re.sub(r' *\x00 *', '\n\n', texto)
    texto = re.sub(r'([.!?…,;:]) *\1+', r'\1', texto)
    texto = re.sub(r'[ \t]+', ' ', texto)
    return '\n\n'.join(p.strip() for p in texto.split('\n\n') if p.strip())


# Function to run every deterministic rule over one text
def limpiar_texto(texto, idioma='es'):
    texto = normalizar_caracteres(texto)
    texto = quitar_numeros_pagina(texto)
    texto = expandir_abreviaturas(texto, idioma)
    texto = puntuar_lineas(texto)
    texto = desenvolver_lineas(texto)
    texto = arreglar_guiones(texto)
    texto = quitar_markdown(texto)
    texto = normalizar_espacios(texto)
    texto = colapsar_repeticiones(texto)
    return normalizar_pausas(texto) + '\n'
