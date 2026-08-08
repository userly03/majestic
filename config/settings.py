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

# --- Traversal de lineage ---
DEFAULT_MAX_HOPS = int(os.getenv("MAJESTIC_MAX_HOPS", "3"))

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

# --- Memoria episódica (structuredProperties) ---
# Debe coincidir con el urn definido en agent_memory_property.yaml
MEMORY_PROPERTY_URN = "urn:li:structuredProperty:majestic.diagnosis"
