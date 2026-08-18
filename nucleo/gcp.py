# Importing required libraries
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


# Function to get the Google credentials ready before creating any client. The
# resolution order is: an explicit JSON key, the environment variable when it
# points to a real file, the credentials.json of the project, and finally the
# Application Default Credentials of the machine (gcloud). It returns a human
# readable description of the source, or raises with the way to fix it
def preparar_credenciales(ruta_llave=None):
    if ruta_llave:
        ruta = Path(ruta_llave).expanduser()
        if not ruta.is_file():
            raise FileNotFoundError(f'La llave JSON no existe: {ruta}')
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = str(ruta)
        return f'llave JSON: {ruta}'

    actual = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')
    if actual:
        if Path(actual).is_file():
            return f'variable GOOGLE_APPLICATION_CREDENTIALS: {actual}'
        # una variable que apunta a un archivo inexistente rompería también el
        # ADC, así que se descarta en lugar de dejar que lo pise
        del os.environ['GOOGLE_APPLICATION_CREDENTIALS']

    proyecto = RAIZ / 'credentials.json'
    if proyecto.is_file():
        os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = str(proyecto)
        return 'credentials.json del proyecto'

    try:
        import google.auth
        credenciales, id_proyecto = google.auth.default()
        return 'ADC del sistema' + (f' (proyecto {id_proyecto})' if id_proyecto else '')
    except Exception as error:
        raise RuntimeError(
            'No hay credenciales de Google. Opciones: pasa la ruta de tu llave JSON '
            '(--cred en los scripts, o el campo de la interfaz), coloca credentials.json '
            'en la raíz del proyecto, o inicia sesión con: gcloud auth application-default login'
        ) from error


# Function to count how many requests this project has sent to the Vision API
# during the current calendar month, read from Cloud Monitoring. The reads are
# free and only successful (billed) requests are counted. Google does not expose
# the remaining free tier directly, so the app subtracts this from the monthly
# allowance in config.json
def paginas_vision_usadas(ruta_llave=None):
    import datetime
    import google.auth
    from google.cloud import monitoring_v3

    preparar_credenciales(ruta_llave)
    credenciales, proyecto = google.auth.default()
    if not proyecto:
        raise RuntimeError('Las credenciales no llevan un proyecto asociado')

    ahora = datetime.datetime.now(datetime.timezone.utc)
    inicio = ahora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    segundos = int((ahora - inicio).total_seconds()) or 60

    cliente = monitoring_v3.MetricServiceClient(credentials=credenciales)
    respuesta = cliente.list_time_series(request={
        'name': f'projects/{proyecto}',
        'filter': ('metric.type="serviceruntime.googleapis.com/api/request_count" '
                   'AND resource.label.service="vision.googleapis.com" '
                   'AND metric.label.response_code_class="2xx"'),
        'interval': {'start_time': {'seconds': int(inicio.timestamp())},
                     'end_time': {'seconds': int(ahora.timestamp())}},
        'aggregation': {'alignment_period': {'seconds': segundos},
                        'per_series_aligner': monitoring_v3.Aggregation.Aligner.ALIGN_SUM,
                        'cross_series_reducer': monitoring_v3.Aggregation.Reducer.REDUCE_SUM},
        'view': monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL
    })
    return sum(int(punto.value.int64_value) for serie in respuesta for punto in serie.points)
