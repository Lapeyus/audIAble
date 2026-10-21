import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
import cv2
import numpy as np
from nucleo.calidad_video import (calidad, alinear, cuadro_seguro, cuadro_envolvente, ordenar_cuadro,
                                  enderezar, movimiento_compensado, planitud, detectar_lomo, limpiar_iluminacion)
from nucleo.ocr_calidad import consenso, variantes
from nucleo.limpieza import limpiar_texto, quitar_encabezados_repetidos

spec = importlib.util.spec_from_file_location('pre_video', Path(__file__).resolve().parents[1] / 'pasos/pre-video.py')
video = importlib.util.module_from_spec(spec)
spec.loader.exec_module(video)


def pagina(semilla=7):
    rng = np.random.default_rng(semilla)
    imagen = np.full((720, 540, 3), 245, np.uint8)
    for y in range(40, 700, 30):
        texto = ' '.join(str(n) for n in rng.integers(1000, 9999, 7))
        cv2.putText(imagen, texto, (15, y), cv2.FONT_HERSHEY_SIMPLEX, 0.47, (25, 25, 25), 1, cv2.LINE_AA)
    return imagen


class CalidadTest(unittest.TestCase):
    def test_nitidez_prefiere_texto_enfocado(self):
        a = pagina()
        self.assertGreater(calidad(a), 2 * calidad(cv2.GaussianBlur(a, (9, 9), 2)))

    def test_registro_perspectiva_con_sombra(self):
        a = pagina()
        origen = np.float32([[0, 0], [539, 0], [539, 719], [0, 719]])
        destino = np.float32([[30, 15], [510, 35], [535, 695], [10, 715]])
        h = cv2.getPerspectiveTransform(origen, destino)
        b = cv2.warpPerspective(a, h, (540, 720), borderValue=(245, 245, 245))
        b = np.clip(b.astype(float) * 0.85, 0, 255).astype(np.uint8)
        registrada, soporte = alinear(a, b)
        self.assertIsNotNone(registrada)
        self.assertGreater(soporte.mean(), 0.8)
        self.assertGreater(np.corrcoef(a[soporte].ravel(), registrada[soporte].ravel())[0, 1], 0.9)

    def test_no_registra_paginas_diferentes(self):
        self.assertIsNone(alinear(pagina(1), pagina(22))[0])

    def test_blanco_no_se_registra_ni_rota(self):
        a = np.full((150, 110, 3), 255, np.uint8)
        self.assertIsNone(alinear(a, a)[0])
        np.testing.assert_array_equal(enderezar(a), a)
        self.assertEqual(video.similitud(a, a), 0)

    def test_cuadrilatero_oblicuo_y_degenerado(self):
        self.assertTrue(cuadro_seguro(np.float32([[100, 10], [400, 80], [500, 650], [0, 700]])))
        self.assertFalse(cuadro_seguro(np.float32([[0, 0], [500, 0], [250, 2], [0, 700]])))
        rombo = np.float32([[200, 0], [400, 200], [200, 400], [0, 200]])
        self.assertEqual(len(np.unique(ordenar_cuadro(rombo), axis=0)), 4)

    def test_cuadro_envolvente_restituye_esquina_hundida_por_pulgar(self):
        # La esquina inferior izquierda fue empujada hacia dentro (x=280 en vez de 150) por el pulgar
        recortada = np.float32([[150, 100], [950, 100], [950, 1300], [280, 1220]])
        limpia = np.float32([[150, 100], [950, 100], [950, 1300], [150, 1300]])
        env = cuadro_envolvente([recortada, recortada, limpia], forma=(1440, 1080))
        self.assertLess(env[3, 0], 175)
        self.assertGreater(env[3, 1], 1280)

    def test_planitud_tolera_inclinacion_leve_y_detecta_lomo(self):
        a = pagina()
        m = cv2.getRotationMatrix2D((270, 360), 3.5, 1.0)
        inclinada = cv2.warpAffine(a, m, (540, 720), borderValue=(245, 245, 245))
        self.assertGreater(planitud(inclinada), 0.85)
        doble = np.hstack([a, pagina(9)])
        # Sombra de lomo desplazada ligeramente del centro
        doble[:, 515:525] = np.clip(doble[:, 515:525].astype(int) - 70, 0, 255).astype(np.uint8)
        fin_izq, inicio_der = detectar_lomo(doble)
        self.assertLessEqual(fin_izq, 522)
        self.assertGreaterEqual(inicio_der, 518)

    def test_limpiar_iluminacion_aplana_sombra_sin_perder_contraste(self):
        a = pagina()
        gradiente = np.linspace(0.55, 1.0, a.shape[1], dtype=np.float32)[None, :, None]
        sombreada = np.clip(a.astype(np.float32) * gradiente, 0, 255).astype(np.uint8)
        limpia = limpiar_iluminacion(sombreada)
        # El fondo oscuro del lado izquierdo se aclara notablemente
        self.assertGreater(float(limpia[:, :120].mean()), float(sombreada[:, :120].mean()) + 40)

    def test_movimiento_rotacion_y_exposicion(self):
        a = cv2.cvtColor(pagina(), cv2.COLOR_BGR2GRAY).astype(np.float32)
        m = cv2.getRotationMatrix2D((270, 360), 2, 1.01)
        b = cv2.warpAffine(a, m, (540, 720), borderValue=245) - 10
        self.assertLess(movimiento_compensado(a, b), 5)
        c = cv2.cvtColor(pagina(100), cv2.COLOR_BGR2GRAY).astype(np.float32)
        self.assertGreater(movimiento_compensado(a, c), 8)

    def test_capturas_del_reposo_y_de_su_entorno(self):
        video.args = SimpleNamespace(umbral=2.5, factor=1.4, quietud=0.5, capturas=3)
        medidas = [(i, i * 0.25, 20 if i in (0, 7) else 0, 100 + (i == 3)) for i in range(8)]
        tomas = video.elegir_fotogramas(medidas)
        self.assertEqual(len(tomas), 1)
        # la referencia (primera) es la más nítida del reposo; el resto puede venir
        # de hasta dos fotogramas analizados fuera de él, donde la mano se aparta
        self.assertEqual(tomas[0]['indices'][0], 3)
        self.assertTrue(set(tomas[0]['indices']).issubset(set(range(0, 8))))

    def test_un_autoenfoque_no_parte_el_reposo(self):
        video.args = SimpleNamespace(umbral=2.5, factor=1.4, quietud=0.5, capturas=3)
        # un pico de dos fotogramas en los que la nitidez se desploma es un desenfoque
        medidas = [(i, i * 0.25, 4 if i in (5, 6) else 0, 5 if i in (5, 6) else 100) for i in range(12)]
        self.assertEqual(len(video.elegir_fotogramas(medidas)), 1)
        # uno igual de breve pero con la imagen nítida entre dos reposos completos es un cambio de página
        medidas = [(i, i * 0.25, 4 if i in (5, 6) else 0, 100) for i in range(12)]
        self.assertEqual(len(video.elegir_fotogramas(medidas)), 2)

    def test_reajuste_de_mano_no_descarta_reposo_partido(self):
        video.args = SimpleNamespace(umbral=2.5, factor=1.4, quietud=0.8, capturas=3)
        # Dos mitades de 0.5 s (< 0.8 s) separadas por 1 fotograma de reajuste suave (mov=3.2) forman un reposo válido
        medidas = [(i, i * 0.25, 3.2 if i == 3 else (15.0 if i in (0, 7) else 0.4), 100.0) for i in range(8)]
        tomas = video.elegir_fotogramas(medidas)
        self.assertEqual(len(tomas), 1)

    def test_detecta_cambio_de_pagina_con_texto_pequeno(self):
        # A 160 px y con desenfoque fuerte estas páginas antes se fundían.
        video.args = SimpleNamespace(fps=4, umbral=2.5, factor=1.4, quietud=0.5, capturas=3)
        with tempfile.TemporaryDirectory() as temporal:
            ruta = Path(temporal) / 'libro.avi'
            writer = cv2.VideoWriter(str(ruta), cv2.VideoWriter_fourcc(*'MJPG'), 12, (540, 720))
            self.assertTrue(writer.isOpened())
            for semilla in (1, 22, 100):
                for _ in range(24):
                    writer.write(pagina(semilla))
            writer.release()
            self.assertEqual(len(video.elegir_fotogramas(video.medir_video(ruta))), 3)

    def test_sin_deteccion_se_conserva_el_fotograma(self):
        video.args = SimpleNamespace(recorte='auto')
        with tempfile.TemporaryDirectory() as temporal:
            video.CARPETA_CANDIDATAS = Path(temporal)
            ruta = Path(temporal) / 'vacia.png'
            imagen = np.full((300, 400, 3), 255, np.uint8)
            cv2.imwrite(str(ruta), imagen)
            anterior = video.detectar_paginas_vision
            video.detectar_paginas_vision = lambda rutas: {}
            try:
                tomas = [{'rutas': [ruta]}]
                video.recortar_tomas(tomas)
                self.assertFalse(tomas[0]['recorte_fiable'])
                np.testing.assert_array_equal(video.cargar(tomas[0]), imagen)
            finally:
                video.detectar_paginas_vision = anterior


class ConsensoTest(unittest.TestCase):
    def linea(self, texto, confianza=0.9, caja=None):
        return {'texto': texto, 'confianza': confianza, 'caja': caja or [0.1, 0.4, 0.8, 0.05]}

    def test_dos_variantes_corrigen_lectura_debil(self):
        original = [self.linea('El arbo1 verde.', 0.4)]
        alternativa = [self.linea('El arbol verde.')]
        texto, informe = consenso(original, [alternativa, alternativa])
        self.assertEqual(texto, 'El arbol verde.')
        self.assertTrue(informe[0]['corregida_por_consenso'])

    def test_corrige_artefacto_intrapalabra_aun_con_confianza_alta(self):
        original = [self.linea('El arbo1 verde.', 1.0)]
        alternativa = [self.linea('El arbol verde.', 0.95)]
        texto, informe = consenso(original, [alternativa, alternativa])
        self.assertEqual(texto, 'El arbol verde.')
        self.assertTrue(informe[0]['corregida_por_consenso'])

    def test_desacuerdo_y_otras_lineas_no_sustituyen(self):
        original = [self.linea('Total 123 euros.', 0.4)]
        a = [self.linea('Total 128 euros.')]
        b = [self.linea('Total 129 euros.')]
        self.assertEqual(consenso(original, [a, b])[0], original[0]['texto'])
        fuera = [self.linea('Total 128 euros.', caja=[0.1, 0.7, 0.8, 0.05])]
        self.assertEqual(consenso(original, [fuera, fuera])[0], original[0]['texto'])

    def test_preserva_original_confiable(self):
        original = [self.linea('Precio 123,45.', 1.0)]
        variante = [self.linea('Precio 128,45.', 1.0)]
        self.assertEqual(consenso(original, [variante, variante])[0], original[0]['texto'])

    def test_variantes_finitas_sin_modificar_original(self):
        a = pagina()
        copia = a.copy()
        for v in variantes(a):
            self.assertEqual(v.dtype, np.uint8)
            self.assertLessEqual(max(v.shape), 2400)
        np.testing.assert_array_equal(a, copia)


class LimpiezaTest(unittest.TestCase):
    def test_conserva_puntos_suspensivos_y_une_guiones_de_renglon(self):
        bruto = '16 LA MADRIGUERA\nCARLOS Y CARLOS\nNo sabía... si estaba es-\ncondido en el jardín.\n- 16 -'
        limpio = limpiar_texto(bruto, 'es')
        self.assertIn('CARLOS Y CARLOS.', limpio)
        self.assertIn('No sabía... si estaba escondido en el jardín.', limpio)
        self.assertNotIn('LA MADRIGUERA', limpio)
        self.assertNotIn('es- condido', limpio)

    def test_colapsa_repeticiones_de_frases_y_cornisas_de_libro(self):
        paginas = [
            f'Te llevaré en mis ojos\nTexto único de la página número {i} con palabras suficientes.\n{i + 10}'
            for i in range(6)
        ]
        sin_cornisas = quitar_encabezados_repetidos(paginas)
        for p in sin_cornisas:
            self.assertNotIn('Te llevaré en mis ojos', p)
        repetido = limpiar_texto('Estaba en la casa en la casa en la casa esperando.', 'es')
        self.assertEqual(repetido.strip(), 'Estaba en la casa esperando.')


if __name__ == '__main__':
    unittest.main()
