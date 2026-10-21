"""Variantes fotométricas y consenso de líneas con trazabilidad."""
from difflib import SequenceMatcher
import re
import cv2
import numpy as np


def variantes(imagen):
    gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY)
    # Estima iluminación a escala mucho mayor que el trazo; no binariza letras.
    sigma = max(9, min(gris.shape) / 35)
    fondo = cv2.GaussianBlur(gris.astype(np.float32), (0, 0), sigma)
    uniforme = np.clip(gris.astype(np.float32) * 235 / np.maximum(fondo, 20), 0, 255).astype(np.uint8)
    contraste = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8)).apply(gris)
    # Límite de píxeles para no multiplicar la memoria de páginas 4K.
    escala = max(1, min(2, 2400 / max(gris.shape)))
    return [cv2.resize(v, None, fx=escala, fy=escala, interpolation=cv2.INTER_CUBIC)
            for v in (uniforme, contraste)]


def normalizar(texto):
    # Conserva mayúsculas, acentos, cifras y puntuación: son parte del texto.
    return re.sub(r'\s+', ' ', texto).strip()


def solapamiento(a, b):
    x, y, w, h = a
    xx, yy, ww, hh = b
    inter = max(0, min(x + w, xx + ww) - max(x, xx)) * max(0, min(y + h, yy + hh) - max(y, yy))
    return inter / max(w * h + ww * hh - inter, 1e-9)


def _sospechosa_ocr(texto):
    # Dígitos incrustados en palabras (arbo1, 1os), símbolos extraños o letras sueltas partidas.
    if re.search(r'[A-Za-záéíóúüñÁÉÍÓÚÜÑ]\d|\d[A-Za-záéíóúüñÁÉÍÓÚÜÑ]', texto):
        return True
    if re.search(r'[|~^`@#$%&_=+<>\\]', texto):
        return True
    return False


def _mismos_numeros(a, b):
    return re.findall(r'\b\d+(?:[.,]\d+)*\b', a) == re.findall(r'\b\d+(?:[.,]\d+)*\b', b)


def consenso(original, alternativas):
    """Modifica solo líneas ambiguas con dos lecturas coincidentes y ubicadas.

    No interpreta confianza como probabilidad ni inventa líneas ausentes. Las
    discrepancias quedan en el informe para su revisión contra la imagen.
    """
    elegidas, informe = [], []
    for linea in original:
        candidatos = []
        for variante in alternativas:
            cercanas = [v for v in variante if solapamiento(linea['caja'], v['caja']) >= 0.55]
            candidatos.append(max(cercanas, key=lambda v: solapamiento(linea['caja'], v['caja'])) if cercanas else None)
        texto = linea['texto']
        cambio = False
        if len(candidatos) == 2 and all(c is not None for c in candidatos):
            a, b = candidatos
            acuerdo = normalizar(a['texto']) == normalizar(b['texto'])
            parecido = SequenceMatcher(None, normalizar(texto), normalizar(a['texto']), autojunk=False).ratio()
            conf_var = min(a['confianza'], b['confianza'])
            debil = linea['confianza'] < 0.85 and conf_var >= max(0.85, linea['confianza'] + 0.1) and parecido >= 0.7
            artefacto = (_sospechosa_ocr(texto) and not _sospechosa_ocr(a['texto'])
                         and _mismos_numeros(texto, a['texto']) and conf_var >= 0.85 and parecido >= 0.75)
            if acuerdo and (debil or artefacto):
                texto = a['texto']
                cambio = texto != linea['texto']
        elegidas.append(texto)
        discrepancia = any(c is not None and normalizar(c['texto']) != normalizar(texto) for c in candidatos)
        informe.append({'original': linea, 'alternativas': candidatos, 'texto': texto,
                        'corregida_por_consenso': cambio, 'revisar': discrepancia or linea['confianza'] < 0.85})
    return '\n'.join(elegidas), informe
