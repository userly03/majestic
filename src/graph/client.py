"""
Client toward DataHub GMS (Graph Management Service).
Wraps all communication with DataHub: connection, lineage, and
reading/writing aspects (including structured properties).

Uses DataHubGraph (not just the REST emitter it inherits from) because
lineage traversal and structured-property write-back need its query API,
not just emission.
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
    HTTP_RETRY_MAX_TIMES,
    HTTP_TIMEOUT_SECONDS,
)

logger = logging.getLogger(__name__)


class DataHubClient:
    """Reusable client for interacting with DataHub."""

    def __init__(
        self,
        server_url: Optional[str] = None,
        token: Optional[str] = None,
    ):
        self.server = server_url or DATAHUB_GMS_URL
        self.token = token or DATAHUB_GMS_TOKEN

        logger.info("Initializing DataHubClient -> %s", self.server)

        try:
            self.graph = self._connect_with_retry()
            logger.info("Successfully connected to DataHub GMS")
        except Exception as exc:
            logger.error(
                "Could not connect to DataHub after %d attempts: %s",
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
        Tries to connect up to CONNECT_RETRY_ATTEMPTS times with
        exponential backoff. If DataHub is restarting or momentarily
        unresponsive, this keeps the agent from dying on the first
        attempt. If retries are exhausted, re-raises the original
        exception (reraise=True) so the constructor's try/except catches
        it.
        """
        graph = DataHubGraph(
            DatahubClientConfig(
                server=self.server,
                token=self.token,
                timeout_sec=HTTP_TIMEOUT_SECONDS,
                retry_max_times=HTTP_RETRY_MAX_TIMES,
            )
        )
        graph.test_connection()
        return graph

    @property
    def is_connected(self) -> bool:
        return self.graph is not None
