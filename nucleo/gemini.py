# Importing required libraries
import json
import functools
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

with open(RAIZ / 'config.json') as f:
    _config = json.load(f)

settings = _config['GoogleLLM']


# Function to tell a Google model name from a local Ollama one
def es_modelo_google(nombre):
    return (nombre or '').startswith('gemini')


# Function to build the Vertex client once, authenticated with the same
# credential chain as the rest of the Google integrations (ADC included)
@functools.lru_cache(maxsize=1)
def _cliente():
    from google import genai
    import google.auth
    from . import gcp
    gcp.preparar_credenciales()
    _, proyecto = google.auth.default()
    if not proyecto:
        raise RuntimeError('Las credenciales de Google no llevan proyecto asociado')
    return genai.Client(vertexai=True, project=proyecto, location=settings['location'])


# Function to generate text with a Gemini model. The internal reasoning is
# switched off on the flash models: these are mechanical text tasks and the
# thinking tokens would only add cost and latency
def generar(modelo, prompt, temperatura=0, json_output=False, imagen_png=None):
    from google.genai import types
    ajustes = {'temperature': temperatura, 'max_output_tokens': settings['max_output_tokens']}
    if 'pro' not in modelo:
        ajustes['thinking_config'] = types.ThinkingConfig(thinking_budget=0)
    if json_output:
        ajustes['response_mime_type'] = 'application/json'
    contenido = prompt if imagen_png is None else [
        types.Part.from_bytes(data=imagen_png, mime_type='image/png'), prompt]
    respuesta = _cliente().models.generate_content(
        model=modelo, contents=contenido, config=types.GenerateContentConfig(**ajustes))
    return respuesta.text or ''
