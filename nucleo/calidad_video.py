"""Geometría y calidad conservadoras: nunca sintetiza caracteres ausentes."""
import cv2
import numpy as np

VERSION = 3


def calidad(imagen):
    """Tenengrad por bloques, exigiendo nitidez uniforme en el cuerpo de la página."""
    gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY) if imagen.ndim == 3 else imagen
    escala = min(1.0, 1280 / max(gris.shape))
    if escala < 1:
        gris = cv2.resize(gris, None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA)
    gris = cv2.GaussianBlur(gris, (3, 3), 0.6)
    gx = cv2.Sobel(gris, cv2.CV_32F, 1, 0)
    gy = cv2.Sobel(gris, cv2.CV_32F, 0, 1)
    energia = gx * gx + gy * gy
    bloques = []
    for fila in np.array_split(energia, 6):
        for bloque in np.array_split(fila, 6, axis=1):
            if bloque.size:
                bloques.append(float(np.mean(bloque)))
    ordenados = sorted(bloques)
    # Combina el percentil 45 (que cae si media página sigue en movimiento) con
    # la mediana de los dos tercios superiores (que descarta los márgenes blancos)
    p45 = float(np.percentile(ordenados, 45))
    p_alta = float(np.median(ordenados[len(ordenados) // 3:]))
    return 0.5 * p45 + 0.5 * p_alta


def ordenar_cuadro(puntos):
    puntos = np.asarray(puntos, np.float32).reshape(4, 2)
    centro = puntos.mean(axis=0)
    angulos = np.arctan2(puntos[:, 1] - centro[1], puntos[:, 0] - centro[0])
    ordenados = puntos[np.argsort(angulos)]
    return np.roll(ordenados, -int(np.argmin(ordenados.sum(axis=1))), axis=0).copy()


def cuadro_seguro(puntos):
    """Acepta perspectiva oblicua; rechaza cruces, triángulos y degeneración."""
    p = np.asarray(puntos, np.float32).reshape(4, 2)
    if not np.isfinite(p).all() or not cv2.isContourConvex(p):
        return False
    lados = np.linalg.norm(np.roll(p, -1, axis=0) - p, axis=1)
    if min(lados) < 16 or max(lados) / min(lados) > 12:
        return False
    for i in range(4):
        u, v = p[i - 1] - p[i], p[(i + 1) % 4] - p[i]
        if abs(float(np.dot(u, v) / (np.linalg.norm(u) * np.linalg.norm(v)))) > 0.94:
            return False
    return abs(cv2.contourArea(p)) > 0.15 * max(lados) ** 2


def cuadro_envolvente(lista_esquinas, forma=None, margen=0.012):
    """Calcula el cuadrilátero envolvente robusto de varias detecciones.

    Cuando un pulgar pisa una esquina de la página, el detector de documentos
    encoge esa esquina hacia dentro y corta renglones. Al tomar el percentil
    exterior de cada vértice y corregir esquinas pellizcadas respecto al
    paralelogramo opuesto, se conserva toda la caja de texto.
    """
    cuadros = np.asarray([ordenar_cuadro(e) for e in lista_esquinas], dtype=np.float32)
    if len(cuadros) == 1:
        p = cuadros[0].copy()
    else:
        p = np.zeros((4, 2), dtype=np.float32)
        p[0, 0], p[0, 1] = np.percentile(cuadros[:, 0, 0], 20), np.percentile(cuadros[:, 0, 1], 20)
        p[1, 0], p[1, 1] = np.percentile(cuadros[:, 1, 0], 80), np.percentile(cuadros[:, 1, 1], 20)
        p[2, 0], p[2, 1] = np.percentile(cuadros[:, 2, 0], 80), np.percentile(cuadros[:, 2, 1], 80)
        p[3, 0], p[3, 1] = np.percentile(cuadros[:, 3, 0], 20), np.percentile(cuadros[:, 3, 1], 80)
    # Si una sola esquina quedó hundida hacia dentro respecto al paralelogramo de
    # las otras tres (por una mano fija en todo el tramo), se abre hacia fuera
    centro = p.mean(axis=0)
    paralelogramo = [
        p[3] + (p[1] - p[2]),
        p[0] + (p[2] - p[3]),
        p[3] + (p[1] - p[0]),
        p[0] + (p[2] - p[1]),
    ]
    desviaciones = []
    for i in range(4):
        v_act = p[i] - centro
        v_esp = paralelogramo[i] - centro
        d_act = float(np.linalg.norm(v_act))
        proy = float(np.dot(v_esp, v_act / max(d_act, 1e-3)))
        desviaciones.append((proy - d_act) / max(d_act, 1.0))
    peor = int(np.argmax(desviaciones))
    if desviaciones[peor] > 0.05 and sorted(desviaciones)[-2] < 0.03:
        candidato = p.copy()
        candidato[peor] = p[peor] + 0.8 * (paralelogramo[peor] - p[peor])
        if cuadro_seguro(candidato):
            p = candidato
    if margen > 0:
        expandido = centro + (1.0 + margen) * (p - centro)
        if forma is not None:
            alto, ancho = forma[:2]
            expandido[:, 0] = np.clip(expandido[:, 0], 0, ancho - 1)
            expandido[:, 1] = np.clip(expandido[:, 1], 0, alto - 1)
        if cuadro_seguro(expandido):
            p = expandido.astype(np.float32)
    return p if cuadro_seguro(p) else ordenar_cuadro(cuadros[0])


def homografia(referencia, captura, mascara=None):
    """RootSIFT + correspondencias mutuas + USAC/MAGSAC, ref → captura.

    Exige soporte espacial y error simétrico bajo, además del número de inliers.
    Devuelve None si no hay evidencia suficiente de un mismo plano.
    """
    def preparar(imagen):
        gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY) if imagen.ndim == 3 else imagen
        escala = min(1.0, 1400 / max(gris.shape))
        return cv2.resize(gris, None, fx=escala, fy=escala), escala

    a, sa = preparar(referencia)
    b, sb = preparar(captura)
    ma = None if mascara is None else cv2.resize(mascara.astype(np.uint8), (a.shape[1], a.shape[0]), interpolation=cv2.INTER_NEAREST)
    sift = cv2.SIFT_create(nfeatures=4000, contrastThreshold=0.025)
    ka, da = sift.detectAndCompute(a, ma)
    kb, db = sift.detectAndCompute(b, None)
    if da is None or db is None or min(len(da), len(db)) < 12:
        return None
    da = np.sqrt(da / (da.sum(axis=1, keepdims=True) + 1e-7))
    db = np.sqrt(db / (db.sum(axis=1, keepdims=True) + 1e-7))
    matcher = cv2.BFMatcher(cv2.NORM_L2)
    def pares(x, y):
        return {p[0].queryIdx: p[0].trainIdx for p in matcher.knnMatch(x, y, k=2)
                if len(p) == 2 and p[0].distance < 0.72 * p[1].distance}
    ab, ba = pares(da, db), pares(db, da)
    comunes = [(i, j) for i, j in ab.items() if ba.get(j) == i]
    if len(comunes) < 12:
        return None
    origen = np.float32([ka[i].pt for i, _ in comunes])
    destino = np.float32([kb[j].pt for _, j in comunes])
    h, aceptados = cv2.findHomography(origen, destino, cv2.USAC_MAGSAC, 2.0, maxIters=5000, confidence=0.999)
    if h is None or aceptados is None or not np.isfinite(h).all():
        return None
    buenos = aceptados.ravel().astype(bool)
    if buenos.sum() < 12 or buenos.mean() < 0.55:
        return None
    for puntos, forma in ((origen[buenos], a.shape), (destino[buenos], b.shape)):
        if cv2.contourArea(cv2.convexHull(puntos)) < 0.08 * forma[0] * forma[1]:
            return None
    try:
        inversa = np.linalg.inv(h)
    except np.linalg.LinAlgError:
        return None
    ida = cv2.perspectiveTransform(origen[buenos, None], h)[:, 0]
    vuelta = cv2.perspectiveTransform(destino[buenos, None], inversa)[:, 0]
    if max(np.median(np.linalg.norm(ida - destino[buenos], axis=1)),
           np.median(np.linalg.norm(vuelta - origen[buenos], axis=1))) > 1.2:
        return None
    h = np.diag([1 / sb, 1 / sb, 1]) @ h @ np.diag([sa, sa, 1])
    alto, ancho = referencia.shape[:2]
    esquinas = np.float32([[0, 0], [ancho - 1, 0], [ancho - 1, alto - 1], [0, alto - 1]])
    proyectadas = cv2.perspectiveTransform(esquinas[None], h)[0]
    if not cuadro_seguro(proyectadas) or cv2.contourArea(proyectadas, oriented=True) <= 0:
        return None
    razon = cv2.contourArea(proyectadas) / (ancho * alto)
    if not 0.35 < razon < 2.8:
        return None
    return h


def alinear(referencia, captura, mascara=None):
    h = homografia(referencia, captura, mascara)
    if h is None:
        return None, None
    alto, ancho = referencia.shape[:2]
    flags = cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP
    alineada = cv2.warpPerspective(captura, h, (ancho, alto), flags=flags, borderValue=(255, 255, 255))
    soporte = cv2.warpPerspective(np.full(captura.shape[:2], 255, np.uint8), h, (ancho, alto), flags=flags)
    soporte = cv2.erode((soporte == 255).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    return alineada, soporte


def enderezar(imagen):
    """Deskew con evidencia sobre la tinta limpia (sin manchas ni bordes) y lienzo expandido."""
    gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY) if imagen.ndim == 3 else imagen
    if min(gris.shape) < 32 or gris.std() < 3:
        return imagen
    tinta = tinta_de(imagen, 900)
    if not 0.005 < np.mean(tinta > 0) < 0.4:
        return imagen
    angulos = np.arange(-6, 6.01, 0.25)
    valores = [perfil_lineas(tinta, a) for a in angulos]
    indice = int(np.argmax(valores))
    angulo = float(angulos[indice])
    if indice in (0, len(angulos) - 1) or abs(angulo) < 0.2 or valores[indice] < 1.08 * perfil_lineas(tinta, 0):
        return imagen
    alto, ancho = imagen.shape[:2]
    m = cv2.getRotationMatrix2D((ancho / 2, alto / 2), angulo, 1)
    w = int(np.ceil(alto * abs(m[0, 1]) + ancho * abs(m[0, 0])))
    h = int(np.ceil(alto * abs(m[0, 0]) + ancho * abs(m[0, 1])))
    m[:, 2] += ((w - ancho) / 2, (h - alto) / 2)
    return cv2.warpAffine(imagen, m, (w, h), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))


def movimiento_compensado(anterior, actual):
    """Compensa traslación, rotación, escala, exposición y manos en los bordes."""
    a, b = anterior.astype(np.float32), actual.astype(np.float32)
    au, bu = np.clip(a, 0, 255).astype(np.uint8), np.clip(b, 0, 255).astype(np.uint8)
    matriz = None
    # Se buscan puntos de seguimiento en el interior para no enganchar una mano en el borde
    mascara_interior = np.zeros_like(au)
    my, mx = max(1, au.shape[0] // 10), max(1, au.shape[1] // 10)
    mascara_interior[my:-my, mx:-mx] = 255
    puntos = cv2.goodFeaturesToTrack(au, maxCorners=180, qualityLevel=0.02, minDistance=5, mask=mascara_interior)
    if puntos is not None and len(puntos) >= 12:
        destino, estado, _ = cv2.calcOpticalFlowPyrLK(au, bu, puntos, None)
        if destino is not None:
            vuelta, valido, _ = cv2.calcOpticalFlowPyrLK(bu, au, destino, None)
            if vuelta is not None:
                buenos = (estado.ravel() > 0) & (valido.ravel() > 0) & (np.linalg.norm(vuelta - puntos, axis=2).ravel() < 0.8)
                if buenos.sum() >= 12:
                    candidatos, inliers = cv2.estimateAffinePartial2D(puntos[buenos], destino[buenos], method=cv2.RANSAC, ransacReprojThreshold=1.0)
                    if candidatos is not None and inliers is not None and inliers.mean() > 0.65:
                        area = cv2.contourArea(cv2.convexHull(puntos[buenos][inliers.ravel() > 0]))
                        escala = np.linalg.norm(candidatos[0, :2])
                        if area > a.size * 0.12 and 0.9 < escala < 1.1 and abs(candidatos[0, 1]) < 0.15:
                            matriz = candidatos.astype(np.float32)
    if matriz is None:
        (dx, dy), respuesta = cv2.phaseCorrelate(a, b)
        if not (np.isfinite([dx, dy, respuesta]).all() and respuesta > 0.2 and
                abs(dx) < a.shape[1] / 4 and abs(dy) < a.shape[0] / 4):
            dx = dy = 0
        matriz = np.float32([[1, 0, dx], [0, 1, dy]])
    tamano = (a.shape[1], a.shape[0])
    flags = cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP
    alineada = cv2.warpAffine(b, matriz, tamano, flags=flags)
    soporte = cv2.warpAffine(np.ones(b.shape, np.float32), matriz, tamano, flags=flags) > 0.999
    if soporte.mean() < 0.65:
        mapa_diff = np.abs(a - b)
        mascara = np.ones(a.shape, dtype=bool)
    else:
        mediana = float(np.median((a - alineada)[soporte]))
        mapa_diff = np.abs((a - alineada) - mediana)
        mascara = soporte
    # Si uno o dos bloques de borde se disparan en solitario (> 3x la mediana del resto),
    # es un dedo reajustándose en el margen y no un paso de hoja de toda la página
    h, w = a.shape
    bloques = []
    for by in range(4):
        y0, y1 = (by * h) // 4, ((by + 1) * h) // 4
        for bx in range(4):
            x0, x1 = (bx * w) // 4, ((bx + 1) * w) // 4
            m_b = mascara[y0:y1, x0:x1]
            if m_b.any():
                en_borde = by in (0, 3) or bx in (0, 3)
                bloques.append((float(np.mean(mapa_diff[y0:y1, x0:x1][m_b])), en_borde))
    if len(bloques) >= 8:
        valores = [v for v, _ in bloques]
        tope = max(4.0, 3.0 * float(np.median(valores)))
        filtrados = [v for v, b in bloques if not (b and v > tope)]
        if len(filtrados) >= len(bloques) - 3:
            return float(np.mean(filtrados))
    return float(np.mean(mapa_diff[mascara])) if mascara.any() else 0.0


def perfil_lineas(tinta, angulo):
    """Varianza del perfil de filas de la tinta girada: máxima cuando las líneas quedan horizontales."""
    centro = (tinta.shape[1] / 2, tinta.shape[0] / 2)
    girada = cv2.warpAffine(tinta, cv2.getRotationMatrix2D(centro, float(angulo), 1), (tinta.shape[1], tinta.shape[0]))
    return float(np.var(girada.sum(axis=1)))


def tinta_de(imagen, ancho=600):
    gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY) if imagen.ndim == 3 else imagen
    escala = min(1.0, ancho / gris.shape[1])
    if escala < 1:
        gris = cv2.resize(gris, None, fx=escala, fy=escala, interpolation=cv2.INTER_AREA)
    # Normaliza sombras suaves antes de umbralizar para no fundir el pliegue del lomo con las letras
    sigma = max(9, min(gris.shape) / 25)
    fondo = cv2.GaussianBlur(gris.astype(np.float32), (0, 0), sigma)
    nivelada = np.clip(gris.astype(np.float32) * 235.0 / np.maximum(fondo, 30.0), 0, 255).astype(np.uint8)
    binaria = 255 - cv2.threshold(nivelada, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    # solo cuenta el texto: las manchas grandes (el borde de la página, el fondo,
    # una mano) dominarían el perfil y esconderían la inclinación de las líneas
    cuantas, etiquetas, cajas, _ = cv2.connectedComponentsWithStats(binaria)
    alto_maximo = 0.05 * binaria.shape[0]
    for etiqueta in range(1, cuantas):
        x, y, w, h, area = cajas[etiqueta]
        if h > alto_maximo or w > 0.5 * binaria.shape[1]:
            binaria[etiquetas == etiqueta] = 0
    tinta = binaria.astype(np.float32)
    tinta[:3] = tinta[-3:] = 0
    tinta[:, :3] = tinta[:, -3:] = 0
    return tinta


def planitud(imagen):
    """Cuánto de rectas y horizontales están las líneas de texto (0-1).

    Admite una leve inclinación corregible por enderezar() (±6°), pero penaliza
    hojas levantadas o giradas a mitad de vuelta.
    """
    tinta = tinta_de(imagen)
    if not 0.005 < np.mean(tinta > 0) < 0.4:
        return 1.0
    recto = max(perfil_lineas(tinta, a) for a in np.arange(-6, 6.01, 1.5))
    mejor = max(perfil_lineas(tinta, a) for a in np.arange(-24, 24.01, 2))
    return recto / mejor if mejor > 0 else 1.0


def detectar_lomo(imagen):
    """Localiza el pliegue central de un libro abierto y devuelve (fin_izq, inicio_der).

    Busca en la franja central (42%-58%) la columna sin texto y con sombra de
    pliegue, evitando cortar palabras cercanas al margen interior.
    """
    alto, ancho = imagen.shape[:2]
    if ancho < 64:
        mitad = ancho // 2
        return mitad, mitad
    x0, x1 = int(0.42 * ancho), int(0.58 * ancho)
    if x1 <= x0 + 4:
        mitad = ancho // 2
        return mitad, mitad
    tinta = tinta_de(imagen, min(800, ancho))
    escala = tinta.shape[1] / ancho
    tx0, tx1 = max(0, int(x0 * escala)), min(tinta.shape[1], int(x1 * escala))
    # Densidad vertical de tinta en el cuerpo central (15%-85% de la altura)
    y0, y1 = int(0.15 * tinta.shape[0]), int(0.85 * tinta.shape[0])
    densidad_tinta = (tinta[y0:y1, tx0:tx1] > 0).mean(axis=0)
    densidad_tinta = cv2.GaussianBlur(densidad_tinta.reshape(1, -1).astype(np.float32), (11, 1), 0).ravel()

    gris = cv2.cvtColor(imagen, cv2.COLOR_BGR2GRAY) if imagen.ndim == 3 else imagen
    gris_cuerpo = cv2.resize(gris[int(0.15 * alto):int(0.85 * alto), x0:x1], (tx1 - tx0, 100), interpolation=cv2.INTER_AREA)
    brillo = gris_cuerpo.mean(axis=0).astype(np.float32)
    brillo_norm = (brillo - brillo.min()) / (brillo.max() - brillo.min() + 1e-5)
    # Penaliza cortar sobre tinta (peso alto), prefiere el valle de sombra del lomo y cercanía al centro
    pos = np.linspace(-1.0, 1.0, tx1 - tx0, dtype=np.float32)
    coste = 4.0 * densidad_tinta + 0.35 * brillo_norm + 0.15 * (pos ** 2)
    mejor_tx = tx0 + int(np.argmin(coste))
    centro_x = int(round(mejor_tx / escala))
    # Pequeño margen de seguridad para no arrastrar la línea negra del pliegue
    holgura = max(2, int(0.004 * ancho))
    return max(1, centro_x - holgura), min(ancho - 1, centro_x + holgura)


def centro_indice(franjas):
    return franjas // 2


def desdoblar(imagen):
    """Endereza la curvatura de las líneas (el libro no queda plano cerca del lomo).

    Se divide la zona con texto en franjas verticales y se mide, por correlación
    de los perfiles de filas en las bandas superior, media e inferior, cuánto
    sube o baja el texto hacia el lomo; ese desplazamiento bidimensional se
    deshace con cv2.remap solo cuando la evidencia es clara.
    """
    alto, ancho = imagen.shape[:2]
    tinta = tinta_de(imagen, 800)
    if not 0.005 < np.mean(tinta > 0) < 0.4:
        return imagen
    escala = tinta.shape[1] / ancho
    col_tinta = (tinta > 0).mean(axis=0)
    cols_activas = np.where(col_tinta > 0.01)[0]
    if len(cols_activas) < tinta.shape[1] // 3:
        return imagen
    franjas = 12
    limites = np.linspace(int(cols_activas[0]), int(cols_activas[-1]) + 1, franjas + 1).astype(int)
    c_idx = centro_indice(franjas)
    central = tinta[:, limites[max(0, c_idx - 1)]:limites[min(franjas, c_idx + 1)]].sum(axis=1)
    central = cv2.GaussianBlur(central.reshape(-1, 1), (1, 5), 0).ravel()
    central = central - central.mean()
    autocorrelacion = np.correlate(central, central, mode='full')[len(central) - 1:]
    candidatos = [lag for lag in range(8, max(9, len(autocorrelacion) // 5))
                  if autocorrelacion[lag] > autocorrelacion[lag - 1]
                  and autocorrelacion[lag] >= autocorrelacion[lag + 1]
                  and autocorrelacion[lag] > 0]
    interlineado = max(candidatos[:3], key=lambda l: autocorrelacion[l]) if candidatos else 0.03 * tinta.shape[0]
    maximo = max(2, int(0.45 * interlineado))

    def curva_banda(sub_tinta):
        perfiles = []
        for i in range(franjas):
            perfil = sub_tinta[:, limites[i]:limites[i + 1]].sum(axis=1)
            perfil = cv2.GaussianBlur(perfil.reshape(-1, 1), (1, 5), 0).ravel()
            perfiles.append(perfil - perfil.mean())

        def desplazamiento(a, b):
            na, nb = np.linalg.norm(a), np.linalg.norm(b)
            if na < 1e-3 or nb < 1e-3:
                return 0, 0.0
            mejor, mejor_valor = 0, -1.0
            norma = na * nb + 1e-6
            for d in range(-maximo, maximo + 1):
                if d >= 0:
                    valor = float(np.dot(a[d:], b[:len(b) - d])) / norma
                else:
                    valor = float(np.dot(a[:d], b[-d:])) / norma
                if valor > mejor_valor:
                    mejor, mejor_valor = d, valor
            return mejor, mejor_valor

        centro = franjas // 2
        acumulado, pesos, confianzas = {centro: 0.0}, {centro: 1.0}, []
        for i in range(centro + 1, franjas):
            d, c = desplazamiento(perfiles[i - 1], perfiles[i])
            acumulado[i] = acumulado[i - 1] - (d if c >= 0.25 else 0)
            pesos[i] = max(0.05, c if c >= 0.25 else 0.05)
            confianzas.append(c)
        for i in range(centro - 1, -1, -1):
            d, c = desplazamiento(perfiles[i + 1], perfiles[i])
            acumulado[i] = acumulado[i + 1] - (d if c >= 0.25 else 0)
            pesos[i] = max(0.05, c if c >= 0.25 else 0.05)
            confianzas.append(c)
        if not confianzas or float(np.median(confianzas)) < 0.3:
            return None
        xs = np.array([(limites[i] + limites[i + 1]) / 2 for i in range(franjas)])
        ys = np.array([acumulado[i] for i in range(franjas)])
        ws = np.array([pesos[i] for i in range(franjas)])
        polinomio = np.polyfit(xs, ys, 3, w=ws)
        columnas = np.clip(np.arange(ancho, dtype=np.float32) * escala, xs[0], xs[-1])
        correccion = np.polyval(polinomio, columnas) / escala
        return correccion - correccion[ancho // 2]

    c_global = curva_banda(tinta)
    if c_global is None:
        return imagen
    h_t = tinta.shape[0]
    c_sup = curva_banda(tinta[:h_t // 2]) if h_t >= 120 else None
    c_inf = curva_banda(tinta[h_t // 2:]) if h_t >= 120 else None
    c_sup = c_sup if c_sup is not None else c_global
    c_inf = c_inf if c_inf is not None else c_global
    if max(np.max(np.abs(c_global)), np.max(np.abs(c_sup)), np.max(np.abs(c_inf))) * escala < 2.5:
        return imagen
    t_y = np.clip((np.arange(alto, dtype=np.float32) / max(alto - 1, 1) - 0.25) / 0.5, 0.0, 1.0)[:, None]
    despl = (1.0 - t_y) * c_sup[None, :] + t_y * c_inf[None, :]
    mapa_x = np.tile(np.arange(ancho, dtype=np.float32), (alto, 1))
    mapa_y = np.arange(alto, dtype=np.float32)[:, None] + despl
    return cv2.remap(imagen, mapa_x, mapa_y.astype(np.float32), cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def limpiar_iluminacion(imagen):
    """Normaliza sombras de curvatura e iluminación desigual sin binarizar trazos."""
    if imagen is None or imagen.size == 0 or min(imagen.shape[:2]) < 32:
        return imagen
    if imagen.ndim == 2:
        l = imagen
        sigma = max(15, min(l.shape) / 18)
        fondo = cv2.GaussianBlur(l.astype(np.float32), (0, 0), sigma)
        l_norm = np.clip(l.astype(np.float32) * 240.0 / np.maximum(fondo, 40.0), 0, 255)
        suave = cv2.GaussianBlur(l_norm, (0, 0), 1.0)
        return np.clip(l_norm + 0.25 * (l_norm - suave), 0, 255).astype(np.uint8)
    lab = cv2.cvtColor(imagen, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    if l.std() < 3:
        return imagen
    sigma = max(15, min(l.shape) / 18)
    fondo = cv2.GaussianBlur(l.astype(np.float32), (0, 0), sigma)
    # Compensa el gradiente de sombra conservando el contraste natural del papel
    factor = np.clip(238.0 / np.maximum(fondo, 45.0), 0.75, 2.2)
    l_norm = np.clip(l.astype(np.float32) * (0.65 * factor + 0.35), 0, 255)
    suave = cv2.GaussianBlur(l_norm, (0, 0), 1.0)
    l_nitida = np.clip(l_norm + 0.25 * (l_norm - suave), 0, 255).astype(np.uint8)
    return cv2.cvtColor(cv2.merge([l_nitida, a, b]), cv2.COLOR_LAB2BGR)

