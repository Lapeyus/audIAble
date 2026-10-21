"""Fusión de lecturas del OCR multifotograma, con lecturas inventadas."""
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def cargar_modulo():
    fuente = (RAIZ / 'pasos' / 'pro-multiframe-ocr.py').read_text(encoding='utf-8')
    fuente = fuente[:fuente.rindex('\nprincipal()')]
    espacio = {'__file__': str(RAIZ / 'pasos' / 'pro-multiframe-ocr.py'), '__name__': 'multiframe'}
    argv = sys.argv
    sys.argv = ['pro-multiframe-ocr.py', '--f', '.', '--o', '.']
    try:
        exec(compile(fuente, 'pro-multiframe-ocr.py', 'exec'), espacio)
    finally:
        sys.argv = argv
    return espacio


M = cargar_modulo()

LINEAS = ['El cura Manuel le expuso su caso punto por', 'punto. El Obispo no dejaba de manifestar su asom',
          'bro, pero seguía escuchando atentamente. Al con', 'cluir su confesión, el Obispo con voz parsimoniosa,',
          'actitud comprensiva, le dio la venia para que se', 'despojara de los hábitos, que hiciera los trámites']


def lectura(textos, desplazamiento=0.0, confianza=1.0, quitar=()):
    alto, salida = 0.03, []
    for i, texto in enumerate(textos):
        if i in quitar:
            continue
        salida.append({'texto': texto, 'confianza': confianza, 'caja': [0.1, 0.9 - i * 0.05 - desplazamiento, 0.8, alto]})
    return salida


class FusionTest(unittest.TestCase):
    def test_captura_desplazada_no_duplica_y_recupera_lo_tapado(self):
        # la imagen final no lee el renglón 3 (una mano encima) y lee mal el 1
        final = lectura([LINEAS[0], 'punto. El Obisp0 no dejaba de manifestar su asorn'] + LINEAS[2:], quitar={3})
        final[1]['confianza'] = 0.6  # Vision da menos confianza a un renglón mal leído
        # una captura desplazada dos renglones, que sí lee todo
        captura = lectura(LINEAS, desplazamiento=0.1)
        texto, informe = M['fusionar'](final, [('cap_1.png', captura)])
        renglones = texto.split('\n')
        self.assertEqual(len(renglones), len(LINEAS), texto)
        self.assertEqual(len(set(renglones)), len(renglones), 'renglones duplicados')
        self.assertIn(LINEAS[3], renglones)
        self.assertEqual(renglones, LINEAS)
        self.assertEqual(len(informe['recuperados']), 1)

    def test_captura_sin_anclas_no_aporta(self):
        final = lectura(LINEAS)
        otra_pagina = lectura(['Texto de otra página que no tiene nada que ver', 'con lo que se lee en la imagen final, nada',
                               'de nada, y que por tanto no puede anclarse'])
        texto, informe = M['fusionar'](final, [('cap_1.png', otra_pagina)])
        self.assertEqual(texto.split('\n'), LINEAS)
        self.assertEqual(informe['capturas_sin_anclar'], ['cap_1.png'])

    def test_dos_capturas_no_recuperan_dos_veces_lo_mismo(self):
        final = lectura(LINEAS, quitar={4})
        texto, informe = M['fusionar'](final, [('cap_1.png', lectura(LINEAS, 0.02)), ('cap_2.png', lectura(LINEAS, -0.01))])
        self.assertEqual(texto.split('\n').count(LINEAS[4]), 1)


if __name__ == '__main__':
    unittest.main()
