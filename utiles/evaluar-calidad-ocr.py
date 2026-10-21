# Evaluación local reproducible; no extrapolar a vídeos reales sin anotaciones.
import sys, json, subprocess, os, re, argparse
from pathlib import Path
import cv2, numpy as np, fitz
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from nucleo.ocr_calidad import variantes, consenso
parser = argparse.ArgumentParser(description='Compara CER de un helper Vision anterior con el consenso actual usando texto sintético conocido.')
parser.add_argument('--referencia', required=True, type=Path, help='Ruta a una versión anterior de vision_ocr.swift.')
parser.add_argument('--salida', required=True, type=Path, help='Carpeta nueva para imágenes, transcripciones y métricas.')
args = parser.parse_args()
if sys.platform != 'darwin':
    parser.error('Esta comparación requiere Vision de macOS')
if not args.referencia.is_file():
    parser.error('No existe el helper de referencia')
root = RAIZ
out = args.salida
out.mkdir(parents=True, exist_ok=False)
lineas = [
'La lluvia caía lentamente sobre los árboles del jardín.',
'El viajero abrió su cuaderno y escribió la fecha: 23 de abril.',
'En la biblioteca había 128 libros, ordenados por su autor.',
'La precisión del texto depende de conservar cada carácter.',
'¿Cuántas páginas quedan? Todavía faltan treinta y dos.',
'El café costaba 1.250 colones y el pan, 875 colones.',
'Una cámara en movimiento puede difuminar las letras.',
'Los números 0123456789 deben permanecer sin cambios.',
'Mañana volveremos al río para escuchar a los pájaros.',
'El último párrafo termina aquí, junto a la ventana abierta.'
]
doc = fitz.open(); page = doc.new_page(width=500, height=480)
for i, t in enumerate(lineas): page.insert_text((25, 45 + i*39), t, fontsize=12, fontname='tiro')
pix=page.get_pixmap(matrix=fitz.Matrix(2,2)); a=np.frombuffer(pix.samples,np.uint8).reshape(pix.height,pix.width,3).copy()
a=cv2.cvtColor(a,cv2.COLOR_RGB2BGR)
x=np.linspace(0.23,1,a.shape[1])[None,:,None]
small=cv2.resize(a,None,fx=.45,fy=.45,interpolation=cv2.INTER_AREA)
k=np.zeros((7,7),np.float32); k[3]=1/7
casos={'limpio':a,'sombra':np.clip(a*x,0,255).astype(np.uint8),'baja_resolucion':small,'movimiento':cv2.filter2D(a,-1,k)}
env = os.environ.copy()
def norm(t): return re.sub(r'\s+',' ',t).strip()
def cer(a,b):
 a,b=norm(a),norm(b); d=list(range(len(b)+1))
 for i,aa in enumerate(a,1):
  n=[i]
  for j,bb in enumerate(b,1): n.append(min(n[-1]+1,d[j]+1,d[j-1]+(aa!=bb)))
  d=n
 return d[-1]/max(1,len(a))
resultados={}
(out/'referencia.txt').write_text('\n'.join(lineas), encoding='utf-8')
for nombre, imagen in casos.items():
 ruta=out/(nombre+'.png'); cv2.imwrite(str(ruta),imagen)
 base=subprocess.run(['swift',str(args.referencia),'es-ES,en-US',str(ruta)],capture_output=True,text=True,env=env,check=True)
 if '###ERROR:' in base.stdout: raise RuntimeError(base.stdout)
 texto='\n'.join(l for l in base.stdout.splitlines() if not l.startswith('###'))
 rutas=[ruta]
 for i,v in enumerate(variantes(imagen)):
  r=out/f'{nombre}_{i}.png';cv2.imwrite(str(r),v);rutas.append(r)
 nuevo=subprocess.run(['swift',str(root/'pasos/vision_ocr.swift'),'es-ES,en-US','--json']+list(map(str,rutas)),capture_output=True,text=True,env=env,check=True)
 if '###ERROR:' in nuevo.stdout: raise RuntimeError(nuevo.stdout)
 lecturas=[json.loads(l) for l in nuevo.stdout.splitlines() if l.startswith('[')]
 elegido,informe=consenso(lecturas[0],lecturas[1:])
 resultados[nombre]={'cer_anterior':cer(' '.join(lineas),texto),'cer_nuevo':cer(' '.join(lineas),elegido),'lineas':len(lecturas[0]),'cambios':sum(l['corregida_por_consenso'] for l in informe)}
 (out/f'{nombre}_anterior.txt').write_text(texto, encoding='utf-8')
 (out/f'{nombre}_nuevo.txt').write_text(elegido, encoding='utf-8')
 print(nombre,resultados[nombre],flush=True)
(out/'resultado.json').write_text(json.dumps(resultados,indent=2))
