"""Lectura de una credencial de la bóveda passManager (Google Secret Manager).

La bóveda guarda cada «bundle» de credenciales como un secreto (vault-01, vault-02, …) en un
proyecto de GCP dedicado. Cada bundle es un JSON con `credentials`, y cada credencial tiene
`name`, `type` y `fields` (con `key` y `value`). Esta función busca la credencial por nombre y
devuelve el valor de su primer campo secreto con forma de clave, sin escribirlo en ningún sitio.
"""
import json
import shutil
import subprocess

PROYECTO = 'passmanager-jvl-9c2e'
BOVEDAS = [f'vault-0{i}' for i in range(1, 10)]
CAMPOS_CLAVE = ('api_key', 'token', 'apiKey', 'key', 'secret', 'password')


def _leer_bundle(secreto, proyecto):
    gcloud = shutil.which('gcloud')
    if not gcloud:
        raise RuntimeError('No encuentro gcloud en el PATH')
    proceso = subprocess.run([gcloud, 'secrets', 'versions', 'access', 'latest', '--secret', secreto, '--project', proyecto],
                             capture_output=True, text=True, timeout=60)
    if proceso.returncode != 0:
        # el primer renglón del error dice si el secreto no existe o falta permiso
        _leer_bundle.errores[secreto] = (proceso.stderr.strip().splitlines() or ['error desconocido'])[0][:200]
        return None
    try:
        return json.loads(proceso.stdout)
    except json.JSONDecodeError:
        _leer_bundle.errores[secreto] = 'no es un bundle JSON'
        return None


_leer_bundle.errores = {}


# Function to describe the vaults without any value: which ones open, and the
# name, type and field names of every credential
def describir(proyecto=PROYECTO, bovedas=BOVEDAS):
    descripcion = {}
    for secreto in bovedas:
        bundle = _leer_bundle(secreto, proyecto)
        if bundle is None:
            descripcion[secreto] = {'error': _leer_bundle.errores.get(secreto)}
            continue
        descripcion[secreto] = {'nombre': bundle.get('name'), 'credenciales': [
            {'nombre': c.get('name'), 'tipo': c.get('customType') or c.get('type'),
             'campos': [f.get('key') for f in c.get('fields', []) if isinstance(f, dict)]}
            for c in bundle.get('credentials', [])]}
    return descripcion


# Function to find a credential by name (case-insensitive substring of its name,
# custom type or service field) and return the value of its key-like field
def leer_credencial(nombre, proyecto=PROYECTO, bovedas=BOVEDAS):
    buscado = nombre.lower()
    for secreto in bovedas:
        bundle = _leer_bundle(secreto, proyecto)
        if not bundle:
            continue
        for credencial in bundle.get('credentials', []):
            campos = {c.get('key'): c.get('value') for c in credencial.get('fields', []) if isinstance(c, dict)}
            etiquetas = [credencial.get('name', ''), credencial.get('customType', ''), campos.get('service') or '']
            if not any(buscado in str(e).lower() for e in etiquetas):
                continue
            for campo in CAMPOS_CLAVE:
                if campos.get(campo):
                    return campos[campo]
    raise LookupError(f'No hay ninguna credencial «{nombre}» con un campo de clave en las bóvedas de {proyecto}')
