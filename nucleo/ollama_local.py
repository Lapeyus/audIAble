# Importing required libraries
import json
import urllib.request

# Some OCR models do not declare the vision capability even though they read
# images, so the family and the name are checked as well
def es_de_vision(modelo):
    marca = f"{modelo['nombre']} {modelo['familia']}".lower()
    return 'vision' in modelo['capacidades'] or 'ocr' in marca


# Function to ask the server which models are installed
def listar_modelos(host):
    peticion = urllib.request.Request(f'{host}/api/tags')
    with urllib.request.urlopen(peticion, timeout=10) as respuesta:
        datos = json.loads(respuesta.read())
    modelos = []
    for modelo in datos.get('models', []):
        modelos.append({
            'nombre': modelo['name'],
            'capacidades': modelo.get('capabilities') or [],
            'familia': (modelo.get('details') or {}).get('family') or '',
            'tamano': modelo.get('size') or 0
        })
    return modelos


# Function to list the installed models that fit a task, best candidate first.
# For OCR the models specialized in reading pages go first; for text the bigger
# ones do, since on the same machine they are usually the more accurate
def modelos_para(host, tarea):
    modelos = listar_modelos(host)
    if tarea == 'figuras':
        candidatos = [m for m in modelos if 'vision' in m['capacidades']]
        return [m['nombre'] for m in sorted(candidatos, key=lambda m: ('ocr' in f"{m['nombre']} {m['familia']}".lower(), -m['tamano']))]
    if tarea == 'ocr':
        candidatos = [m for m in modelos if es_de_vision(m)]
        return [m['nombre'] for m in sorted(candidatos, key=lambda m: ('ocr' not in f"{m['nombre']} {m['familia']}".lower(), -m['tamano']))]
    candidatos = [m for m in modelos if 'completion' in m['capacidades'] and 'ocr' not in f"{m['nombre']} {m['familia']}".lower()]
    return [m['nombre'] for m in sorted(candidatos, key=lambda m: -m['tamano'])]


# Function to settle on a model: the one asked for when it is installed, and
# otherwise the best autodetected candidate for the task
def elegir_modelo(host, preferido, tarea):
    disponibles = modelos_para(host, tarea)
    if not disponibles:
        raise RuntimeError(f'No hay ningún modelo instalado que sirva para {tarea}. Descarga uno con: ollama pull <modelo>')
    if preferido in disponibles:
        return preferido, False
    return disponibles[0], True
