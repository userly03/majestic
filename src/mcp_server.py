"""
Servidor MCP de Majestic — expone `diagnose`/`impact` como herramientas
invocables por otros agentes, no solo por la CLI.

`main.py` ya es una capa fina sobre `MajesticAgent`/`ImpactSimulator`
(ver src/core/agent.py, src/impact/simulator.py) — este módulo es un
segundo "frontend" sobre el mismo core, sin tocar esa lógica. No hay
razonamiento nuevo acá: cada tool arma un DataHubClient (reutilizado
entre llamadas, ver `_get_client`) y delega en las mismas clases que ya
usa `main.py`.

Uso:
    python3 -m src.mcp_server              # sirve por stdio (el transporte
                                              # que usan Claude Desktop y la
                                              # mayoría de los clientes MCP)

Requiere el extra `mcp` (ver requirements-dev.txt o `pip install mcp`) —
no es una dependencia de producción de la CLI, así que no está en
requirements.txt.
"""

import logging
from typing import Any, Dict, Optional

from mcp.server.mcpserver import MCPServer

from src.core.agent import MajesticAgent
from src.graph.client import DataHubClient
from src.impact.simulator import ImpactSimulator
from src.memory.writer import DiagnosisWriter

logger = logging.getLogger(__name__)

mcp_app = MCPServer(
    "majestic",
    instructions=(
        "Diagnostica causa raíz y simula impacto downstream sobre entidades "
        "de DataHub (datasets, dashboards) a partir de su URN. Usa evidencia "
        "real del grafo de linaje (tags de incidente, ownership, freshness, "
        "cambios de schema) — nunca especula."
    ),
)

# Un solo DataHubClient reutilizado entre llamadas: reconectar en cada tool
# call pagaría el costo de conexión (retry + test_connection) por request,
# innecesario dentro de una misma sesión del servidor MCP.
_client: Optional[DataHubClient] = None


def _get_client() -> DataHubClient:
    global _client
    if _client is None or not _client.is_connected:
        _client = DataHubClient()
        if not _client.is_connected:
            raise RuntimeError(
                "No se pudo conectar a DataHub. Ejecuta: datahub docker quickstart"
            )
    return _client


@mcp_app.tool()
def majestic_diagnose(urn: str, write: bool = False) -> Dict[str, Any]:
    """
    Diagnostica la causa raíz de un dataset/dashboard de DataHub.

    Recorre el linaje upstream buscando evidencia real (tags de incidente,
    ownership, freshness, cambios de schema) y devuelve la cadena causal
    encontrada, la causa raíz elegida y una lista de candidatos rankeados
    (mecanismo lag-aware: decaimiento por antigüedad + descuento por
    herencia — ver docs/LAG_AWARE_DIAGNOSIS.md).

    Args:
        urn: URN completo del dataset/dashboard a diagnosticar.
        write: si es True, persiste el diagnóstico en DataHub como
            structuredProperties (memoria episódica reutilizable).
    """
    client = _get_client()
    report = MajesticAgent(client).diagnose(urn)

    if write:
        ok = DiagnosisWriter(client).write_report(urn, report)
        report = {**report, "written_to_datahub": ok}

    return report


@mcp_app.tool()
def majestic_impact(urn: str) -> Dict[str, Any]:
    """
    Simula el impacto downstream de un cambio propuesto sobre un dataset.

    Recorre el linaje downstream (mismo traversal que `majestic_diagnose`,
    invertido) y devuelve cuántos datasets y dashboards se verían
    afectados, quiénes son sus owners, y un `risk_level` categórico
    (none/low/medium/high).

    Args:
        urn: URN completo del dataset sobre el que se planea el cambio.
    """
    client = _get_client()
    return ImpactSimulator(client).simulate(urn)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
    mcp_app.run()
