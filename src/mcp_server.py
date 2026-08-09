"""
Majestic's MCP server — exposes `diagnose`/`impact` as tools other agents
can invoke, not just the CLI.

`main.py` is already a thin layer over `MajesticAgent`/`ImpactSimulator`
(see src/core/agent.py, src/impact/simulator.py) — this module is a
second "frontend" over the same core, without touching that logic. There
is no new reasoning here: each tool builds a DataHubClient (reused across
calls, see `_get_client`) and delegates to the same classes `main.py`
already uses.

Usage:
    python3 -m src.mcp_server              # serves over stdio (the
                                              # transport used by Claude
                                              # Desktop and most MCP clients)

Requires the `mcp` extra (see requirements-dev.txt or `pip install mcp`)
— not a production dependency of the CLI, so it isn't in requirements.txt.
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
        "Diagnoses the root cause and simulates downstream impact on "
        "DataHub entities (datasets, dashboards) given their URN. Uses "
        "real evidence from the lineage graph (incident tags, ownership, "
        "freshness, schema changes) — never speculates."
    ),
)

# A single DataHubClient reused across calls: reconnecting on every tool
# call would pay the connection cost (retry + test_connection) per
# request, unnecessary within a single MCP server session.
_client: Optional[DataHubClient] = None


def _get_client() -> DataHubClient:
    global _client
    if _client is None or not _client.is_connected:
        _client = DataHubClient()
        if not _client.is_connected:
            raise RuntimeError(
                "Could not connect to DataHub. Run: datahub docker quickstart"
            )
    return _client


@mcp_app.tool()
def majestic_diagnose(urn: str, write: bool = False) -> Dict[str, Any]:
    """
    Diagnoses the root cause of a DataHub dataset/dashboard.

    Walks the upstream lineage looking for real evidence (incident tags,
    ownership, freshness, schema changes) and returns the causal chain
    found, the chosen root cause, and a list of ranked candidates
    (lag-aware mechanism: recency decay + inheritance discount — see
    docs/LAG_AWARE_DIAGNOSIS.md).

    Args:
        urn: full URN of the dataset/dashboard to diagnose.
        write: if True, persists the diagnosis in DataHub as
            structuredProperties (reusable episodic memory).
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
    Simulates the downstream impact of a proposed change on a dataset.

    Walks the lineage downstream (same traversal as `majestic_diagnose`,
    inverted) and returns how many datasets and dashboards would be
    affected, who owns them, and a categorical `risk_level`
    (none/low/medium/high).

    Args:
        urn: full URN of the dataset the change is planned for.
    """
    client = _get_client()
    return ImpactSimulator(client).simulate(urn)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
    mcp_app.run()
