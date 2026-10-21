"""Los agentes de línea de comandos instalados en la máquina (Claude Code, Codex, Antigravity,
Gemini) como motores de corrección: se les manda el texto, y si pueden mirar la imagen de la
página, también la imagen. Cada uno se invoca en su modo no interactivo y devuelve solo texto."""
import os
import shutil
import tempfile
import subprocess
from pathlib import Path

# nombre del motor -> ejecutable y si admite imágenes
AGENTES = {
    'claude': {'bin': 'claude', 'imagen': True},
    'codex': {'bin': 'codex', 'imagen': True},
    'agy': {'bin': 'agy', 'imagen': True},
    'gemini-cli': {'bin': 'gemini', 'imagen': True},
}


# Function to tell whether a model name is one of the CLI agents
def es_agente(modelo):
    return modelo in AGENTES


# Function to list the agents whose executable is installed
def disponibles():
    return [nombre for nombre, datos in AGENTES.items() if shutil.which(datos['bin'])]


# Function to run one agent on a prompt, optionally with page images, and return
# its answer. Every agent runs in a scratch folder with no project files, so the
# only thing it can read is what it is given; the timeout bounds a hung run
def generar(agente, prompt, imagenes=(), modelo=None, timeout=300):
    datos = AGENTES[agente]
    ejecutable = shutil.which(datos['bin'])
    if not ejecutable:
        raise RuntimeError(f'No encuentro la CLI «{datos["bin"]}» en el PATH')
    entorno = dict(os.environ, NO_COLOR='1')
    with tempfile.TemporaryDirectory(prefix='audIAble-agente-') as carpeta:
        # las imágenes se copian a la carpeta del agente: su sandbox no sale de
        # ella, y un disco externo montado en /Volumes queda fuera
        copias = []
        for imagen in imagenes:
            destino = Path(carpeta) / Path(imagen).name
            shutil.copy(imagen, destino)
            copias.append(str(destino))
        imagenes = copias
        if agente == 'claude':
            texto = prompt + (('\n\nImagen de la página: ' + ' '.join(imagenes)) if imagenes else '')
            comando = [ejecutable, '-p', texto, '--allowedTools', 'Read'] + (['--model', modelo] if modelo else [])
        elif agente == 'codex':
            salida = Path(carpeta) / 'respuesta.txt'
            comando = [ejecutable, 'exec', '--ephemeral', '--skip-git-repo-check', '-s', 'read-only', '-o', str(salida)]
            for imagen in imagenes:
                comando += ['-i', imagen]
            comando += (['-m', modelo] if modelo else []) + ['-']
        elif agente == 'agy':
            texto = prompt + (('\n\nImagen de la página: ' + ' '.join(imagenes)) if imagenes else '')
            comando = [ejecutable, '-p', texto, '--mode', 'plan'] + (['--model', modelo] if modelo else [])
        else:
            texto = prompt + (('\n' + ' '.join(f'@{i}' for i in imagenes)) if imagenes else '')
            comando = [ejecutable, '-p', texto, '-o', 'text', '--skip-trust', '-y'] + (['-m', modelo] if modelo else [])
        # sin terminal, codex lee el prompt por stdin («-»); a los demás se les cierra
        proceso = subprocess.run(comando, capture_output=True, text=True, timeout=timeout, cwd=carpeta, env=entorno,
                                 input=prompt if agente == 'codex' else None,
                                 stdin=None if agente == 'codex' else subprocess.DEVNULL)
        if proceso.returncode != 0:
            raise RuntimeError(f'{agente} terminó con error {proceso.returncode}: {(proceso.stderr or proceso.stdout).strip()[-400:]}')
        respuesta = salida.read_text(encoding='utf-8') if agente == 'codex' and salida.exists() else proceso.stdout
    respuesta = respuesta.strip()
    if not respuesta:
        raise RuntimeError(f'{agente} no devolvió texto')
    return respuesta
