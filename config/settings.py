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

# Peso relativo de cada tipo de evidencia (ver el razonamiento completo en
# src/core/diagnoser.py, junto a _EVIDENCE_WEIGHTS). El ORDEN por defecto
# (incident_tag > schema_change > stale_data > unowned) está pensado para
# ser el correcto en la mayoría de los casos; los valores absolutos no
# están calibrados contra un dataset de incidentes reales — por eso son
# configurables acá, no una constante enterrada en el código. Un equipo
# que sí tenga ese historial puede recalibrarlos sin tocar diagnoser.py.
EVIDENCE_WEIGHT_INCIDENT_TAG = float(os.getenv("MAJESTIC_EVIDENCE_WEIGHT_INCIDENT_TAG", "0.9"))
EVIDENCE_WEIGHT_SCHEMA_CHANGE = float(os.getenv("MAJESTIC_EVIDENCE_WEIGHT_SCHEMA_CHANGE", "0.7"))
EVIDENCE_WEIGHT_STALE_DATA = float(os.getenv("MAJESTIC_EVIDENCE_WEIGHT_STALE_DATA", "0.5"))
EVIDENCE_WEIGHT_UNOWNED = float(os.getenv("MAJESTIC_EVIDENCE_WEIGHT_UNOWNED", "0.3"))

# Subcadenas (case-insensitive) que, si aparecen en un tag del dataset,
# se tratan como evidencia directa de incidente conocido.
INCIDENT_TAG_KEYWORDS = ["error", "broken", "incident", "deprecated", "anomaly"]

# --- Mecanismo "lag-aware" (ver docs/LAG_AWARE_DIAGNOSIS.md) ---
# Vida media, en horas, del decaimiento exponencial que se aplica al peso
# de evidencia con timestamp real (schema_change, stale_data): evidencia
# más vieja pesa menos al elegir causa raíz, nunca llega a cero. No aplica
# a incident_tag/unowned (sin timestamp confiable disponible).
LAG_DECAY_HALFLIFE_HOURS = float(os.getenv("MAJESTIC_LAG_DECAY_HALFLIFE_HOURS", "48"))

# Si dos hops consecutivos de la cadena causal tienen el mismo evidence_type,
# el hop más cercano al target se multiplica por este factor — es más
# probable que esté heredando el problema del hop más lejano que aportando
# una señal independiente.
UPSTREAM_INHERITANCE_DISCOUNT = float(os.getenv("MAJESTIC_UPSTREAM_INHERITANCE_DISCOUNT", "0.5"))

# Cuántos candidatos a causa raíz devolver rankeados (ranked_candidates),
# no solo el primero.
RANKED_CANDIDATES_TOP_K = int(os.getenv("MAJESTIC_RANKED_CANDIDATES_TOP_K", "3"))

# --- check-change (RiskAssessor) ---
# risk_score >= este umbral => "check-change" bloquea (exit 1) en vez de
# aprobar. Heurística, igual que _EVIDENCE_WEIGHTS en diagnoser.py: el
# valor por defecto no está calibrado contra incidentes reales, pero SÍ es
# configurable (a diferencia de _EVIDENCE_WEIGHTS, que son constantes de
# código) porque acá el costo de ajustarlo por organización es legítimo:
# qué tan tolerante al riesgo sea un equipo es una decisión de negocio, no
# una propiedad del algoritmo.
CHECK_CHANGE_RISK_THRESHOLD = float(os.getenv("MAJESTIC_CHECK_CHANGE_RISK_THRESHOLD", "0.5"))

# --- Listener de incidentes (src/events/listener.py) ---
# Segundos entre cada polling a DataHub buscando datasets con tag de
# incidente nuevos. 5s por defecto: suficientemente rápido para una demo
# en vivo, sin martillar el GMS en un uso real prolongado.
LISTENER_POLL_INTERVAL_SECONDS = float(os.getenv("MAJESTIC_LISTENER_POLL_INTERVAL_SECONDS", "5"))
