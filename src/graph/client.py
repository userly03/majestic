"""
Cliente hacia DataHub GMS (Graph Management Service).
Encapsula toda la comunicación con DataHub: conexión, lineage y
lectura/escritura de aspectos (incluidas structured properties).

Usa DataHubGraph (no solo el emitter REST, del que hereda) porque el
traversal de lineage y el write-back de structured properties requieren
su API de consulta, no solo de emisión.
"""

import logging
from typing import Optional

from datahub.ingestion.graph.client import DataHubGraph
from datahub.ingestion.graph.config import DatahubClientConfig
from tenacity import (
    before_sleep_log,
    retry,
    stop_after_attempt,
    wait_exponential,
)

from config.settings import (
    CONNECT_RETRY_ATTEMPTS,
    CONNECT_RETRY_WAIT_MAX_SECONDS,
    CONNECT_RETRY_WAIT_MIN_SECONDS,
    DATAHUB_GMS_TOKEN,
    DATAHUB_GMS_URL,
)

logger = logging.getLogger(__name__)


class DataHubClient:
    """Cliente reutilizable para interactuar con DataHub."""

    def __init__(
        self,
        server_url: Optional[str] = None,
        token: Optional[str] = None,
    ):
        self.server = server_url or DATAHUB_GMS_URL
        self.token = token or DATAHUB_GMS_TOKEN

        logger.info("🔗 Inicializando DataHubClient → %s", self.server)

        try:
            self.graph = self._connect_with_retry()
            logger.info("✅ Conexión exitosa con DataHub GMS")
        except Exception as exc:
            logger.error(
                "❌ No se pudo conectar a DataHub tras %d intentos: %s",
                CONNECT_RETRY_ATTEMPTS,
                exc,
            )
            self.graph = None

    @retry(
        stop=stop_after_attempt(CONNECT_RETRY_ATTEMPTS),
        wait=wait_exponential(
            multiplier=1,
            min=CONNECT_RETRY_WAIT_MIN_SECONDS,
            max=CONNECT_RETRY_WAIT_MAX_SECONDS,
        ),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _connect_with_retry(self) -> DataHubGraph:
        """
        Intenta conectar hasta CONNECT_RETRY_ATTEMPTS veces con backoff
        exponencial. Si DataHub está reiniciando o momentáneamente no
        responde, esto evita que el agente muera en el primer intento.
        Si los reintentos se agotan, relanza la excepción original
        (reraise=True) para que el try/except del constructor la capture.
        """
        graph = DataHubGraph(
            DatahubClientConfig(server=self.server, token=self.token)
        )
        graph.test_connection()
        return graph

    @property
    def is_connected(self) -> bool:
        return self.graph is not None
