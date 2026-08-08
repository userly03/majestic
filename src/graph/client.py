"""
Cliente hacia DataHub GMS (Graph Management Service).
Encapsula toda la comunicación con DataHub: conexión, lineage y
lectura/escritura de aspectos (incluidas structured properties).

Usa DataHubGraph (no solo el emitter REST) porque el traversal de
lineage y el write-back de structured properties requieren su API de
consulta, no solo de emisión.
"""

import logging
from typing import Optional

from datahub.ingestion.graph.client import DataHubGraph
from datahub.ingestion.graph.config import DatahubClientConfig

from config.settings import DATAHUB_GMS_TOKEN, DATAHUB_GMS_URL

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
            self.graph = DataHubGraph(
                DatahubClientConfig(server=self.server, token=self.token)
            )
            self.graph.test_connection()
            logger.info("✅ Conexión exitosa con DataHub GMS")
        except Exception as exc:
            logger.error("❌ No se pudo conectar a DataHub: %s", exc)
            self.graph = None

    @property
    def is_connected(self) -> bool:
        return self.graph is not None
