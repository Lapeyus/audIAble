"""Dónde viven los archivos pesados: en la biblioteca del disco externo si está montado, si no en trabajo/."""
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
with open(RAIZ / 'config.json') as f:
    BIBLIOTECA = Path(json.load(f).get('Rutas', {}).get('biblioteca', RAIZ / 'trabajo'))


# Function to tell whether the external library is reachable right now
def biblioteca_montada():
    return BIBLIOTECA.exists()


# Function to give the folder where the phone videos are copied
def carpeta_telefono():
    return (BIBLIOTECA if biblioteca_montada() else RAIZ / 'trabajo') / 'entrada' / 'telefono'


# Function to give the default output folder
def carpeta_salida():
    return (BIBLIOTECA if biblioteca_montada() else RAIZ / 'trabajo') / 'salida'
