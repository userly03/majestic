"""
Configuración centralizada de Majestic.
Todos los módulos deben leer configuración de aquí en vez de llamar
os.getenv() directamente, para tener un solo lugar donde ver/cambiar defaults.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# --- Conexión a DataHub ---
DATAHUB_GMS_URL = os.getenv("DATAHUB_GMS_URL", "http://localhost:8080")
DATAHUB_GMS_TOKEN = os.getenv("DATAHUB_GMS_TOKEN")

# Reintentos al establecer conexión, en nuestra propia capa (tenacity, en
# client.py). Si DataHub "parpadea" al arrancar el agente, esto evita morir
# en el primer intento.
CONNECT_RETRY_ATTEMPTS = int(os.getenv("MAJESTIC_CONNECT_RETRY_ATTEMPTS", "3"))
CONNECT_RETRY_WAIT_MIN_SECONDS = float(os.getenv("MAJESTIC_CONNECT_RETRY_WAIT_MIN", "1"))
CONNECT_RETRY_WAIT_MAX_SECONDS = float(os.getenv("MAJESTIC_CONNECT_RETRY_WAIT_MAX", "10"))

# Timeout por request HTTP hacia el GMS. Sin esto, DatahubClientConfig no
# aplica ningún límite propio — un GMS colgado puede dejar al agente
# esperando indefinidamente, justo el tipo de cosa que no puede pasar en vivo.
HTTP_TIMEOUT_SECONDS = float(os.getenv("MAJESTIC_HTTP_TIMEOUT_SECONDS", "10"))

# Reintentos internos del SDK por request HTTP (urllib3, con backoff
# exponencial propio). IMPORTANTE: por defecto son 4 y SÍ se activan también
# ante "connection refused", no solo ante 5xx — medido contra un GMS caído,
# un solo test_connection() con el default tardaba 28s en fallar. Como ya
# reintentamos la conexión en nuestra propia capa (CONNECT_RETRY_ATTEMPTS),
# tener las dos capas en su valor por defecto multiplica la espera (3 × 28s
# ≈ 90s antes de reportar "no se pudo conectar" — inaceptable en vivo). Lo
# bajamos a un valor chico: sigue absorbiendo un blip transitorio aislado en
# medio de una operación normal, sin convertir "DataHub está caído" en un
# cuelgue de minuto y medio.
HTTP_RETRY_MAX_TIMES = int(os.getenv("MAJESTIC_HTTP_RETRY_MAX_TIMES", "2"))

# --- Traversal de lineage ---
DEFAULT_MAX_HOPS = int(os.getenv("MAJESTIC_MAX_HOPS", "3"))

# Máximo de llamadas get_aspect en paralelo por hop (diagnóstico) o por lote
# (impact). Grafos angostos no lo notan; en grafos anchos evita que la
# latencia percibida crezca linealmente con el fan-in de un nodo.
MAX_PARALLEL_REQUESTS = int(os.getenv("MAJESTIC_MAX_PARALLEL_REQUESTS", "8"))

# --- Diagnóstico (Fase 2) ---
# Máximo de eslabones causales evidenciados que se persiguen upstream.
MAX_CAUSAL_LINKS = int(os.getenv("MAJESTIC_MAX_CAUSAL_LINKS", "3"))

# Si un dataset no se actualizó en más de este umbral, se considera evidencia
# de "datos obsoletos" (posible ETL caído). Heurística inicial, ajustar con
# datos reales de incidentes una vez el agente esté en uso.
FRESHNESS_THRESHOLD_HOURS = int(os.getenv("MAJESTIC_FRESHNESS_THRESHOLD_HOURS", "24"))

# Subcadenas (case-insensitive) que, si aparecen en un tag del dataset,
# se tratan como evidencia directa de incidente conocido.
INCIDENT_TAG_KEYWORDS = ["error", "broken", "incident", "deprecated", "anomaly"]
