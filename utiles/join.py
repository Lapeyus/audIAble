import os
import re

def orden_alfanumerico(texto):
    return [int(text) if text.isdigit() else text.lower() for text in re.split('(\d+)', texto)]

def unir_archivos_txt(directorio, archivo_salida, extension):
    try:
        with open(archivo_salida, 'w') as outfile:
            for filename in sorted(os.listdir(directorio), key=orden_alfanumerico):
                if filename.endswith(extension):
                    with open(os.path.join(directorio, filename), 'r') as infile:
                        # Aquí agregamos el nombre del archivo como un separador de página
                        outfile.write(f'-- {filename} --\n')
                        outfile.write(infile.read() + '\n')
        print(f'Archivos unidos exitosamente en {archivo_salida}')
    except Exception as e:
        print(f'Ocurrió un error: {e}')

# Uso
extension = '.res'
directorio = './res'
archivo_salida = './all/all'+extension

unir_archivos_txt(directorio, archivo_salida, extension)
