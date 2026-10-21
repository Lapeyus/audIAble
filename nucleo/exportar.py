"""Exportación del texto limpio: PDF solo texto y PDF enriquecido (imagen + capa de texto)."""
# Importing required libraries
import re


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


# Function to build the enriched PDF: each page shows the original page image
# with the cleaned text laid invisibly on top, so the book looks like the
# scanned original but can be searched, selected and copied
def exportar_pdf_enriquecido(paginas_txt, destino, origen_pdf=None, carpeta_img=None, dpi_img=300):
    import fitz

    # Function to turn a page pixmap into a JPEG at about 150 dpi. The render
    # comes at OCR resolution as raw PNG, which inflates the PDF to gigabytes;
    # a compressed page is enough to read on screen and keeps the file small
    def comprimir_pagina(pix, dpi_origen):
        if pix.alpha:
            pix = fitz.Pixmap(pix, 0)
        if pix.n != 3:
            pix = fitz.Pixmap(fitz.csRGB, pix)
        while dpi_origen > 200:
            pix.shrink(1)
            dpi_origen /= 2
        return pix.tobytes('jpeg', jpg_quality=70)

    documento = fitz.open()
    original = fitz.open(str(origen_pdf)) if origen_pdf else None
    generadas = 0
    for ruta in paginas_txt:
        numeros = re.findall(r'\d+', ruta.stem)
        numero = int(numeros[-1]) if numeros else 0
        texto = ruta.read_text(encoding='utf-8')

        imagen = carpeta_img / f'{ruta.stem}.png' if carpeta_img else None
        if imagen and imagen.exists():
            pix = fitz.Pixmap(str(imagen))
            # el tamaño de página se calcula antes de encoger la imagen. Un fotograma
            # de vídeo no tiene dpi (dpi_img=None): se le da la altura de un A4
            dpi = dpi_img or pix.height * 72 / 842
            ancho, alto = pix.width * 72 / dpi, pix.height * 72 / dpi
            pagina = documento.new_page(width=ancho, height=alto)
            pagina.insert_image(pagina.rect, stream=comprimir_pagina(pix, dpi))
        elif original and 0 < numero <= len(original):
            pix = original[numero - 1].get_pixmap(dpi=150)
            ancho, alto = original[numero - 1].rect.width, original[numero - 1].rect.height
            pagina = documento.new_page(width=ancho, height=alto)
            pagina.insert_image(pagina.rect, stream=comprimir_pagina(pix, 150))
        else:
            continue

        # texto invisible (render_mode 3) encogido hasta que quepa en la página
        caja = fitz.Rect(2, 2, pagina.rect.width - 2, pagina.rect.height - 2)
        cuerpo = 9.0
        while cuerpo > 3 and pagina.insert_textbox(caja, texto, fontsize=cuerpo, fontname='helv',
                                                   render_mode=3, align=0) < 0:
            cuerpo -= 1
        generadas += 1
    if original:
        original.close()
    if not generadas:
        return None
    documento.save(destino, garbage=4, deflate=True)
    documento.close()
    return destino
