"""
Validation spike: confirms the full episodic-memory cycle (writing
structuredProperties + reading them back) against a real DataHub
instance, before relying on it to run the agent.

Unlike DiagnosisWriter.write_report() (which swallows the exception and
returns True/False for a clean API), this spike builds the patch by hand
so it can:
  1. print the exact JSON that's about to be sent BEFORE sending it, and
  2. if emit_mcps fails, show the full traceback — not just a boolean.
This is exactly the kind of thing a spike should do: bypass the
production abstraction to debug the raw mechanism.

Requires config/agent_memory_property.yaml to already be applied:
    datahub properties upsert -f config/agent_memory_property.yaml

Usage:
    python3 scripts/spike_writeback_test.py [urn]

If no URN is passed, uses the sample dataset `datahub docker quickstart`
ships by default.
"""

import json
import logging
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datahub.specific.dataset import DatasetPatchBuilder

from src.graph.client import DataHubClient
from src.memory.writer import (
    _PROP_BUSINESS_CONTEXT,
    _PROP_CONFIDENCE,
    _PROP_DIAGNOSED_AT,
    _PROP_DIAGNOSIS,
    _PROP_PATTERN_SIGNATURE,
    DiagnosisWriter,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)

DEFAULT_TEST_URN = "urn:li:dataset:(urn:li:dataPlatform:hive,SampleHiveDataset,PROD)"

_FAKE_REPORT = {
    "pattern_signature": "spike_test:1:0:0",
    "reason": "Write-back validation spike — not a real diagnosis.",
    "confidence": 0.01,
}


def _build_patch(urn: str):
    return (
        DatasetPatchBuilder(urn)
        .add_structured_property(_PROP_PATTERN_SIGNATURE, _FAKE_REPORT["pattern_signature"])
        .add_structured_property(_PROP_DIAGNOSIS, _FAKE_REPORT["reason"])
        .add_structured_property(_PROP_CONFIDENCE, float(_FAKE_REPORT["confidence"]))
        .add_structured_property(_PROP_DIAGNOSED_AT, datetime.now(timezone.utc).isoformat())
        .add_structured_property(_PROP_BUSINESS_CONTEXT, "Written by spike_writeback_test.py")
    )


def _print_mcps(mcps) -> None:
    print("Payload about to be sent to DataHub:")
    for mcp in mcps:
        print(f"  entityUrn:  {mcp.entityUrn}")
        print(f"  entityType: {mcp.entityType}")
        print(f"  aspectName: {mcp.aspectName}")
        print(f"  changeType: {mcp.changeType}")
        if mcp.aspect is not None:
            patch_body = json.loads(mcp.aspect.value)
            print("  patch:")
            print("    " + json.dumps(patch_body, indent=2, ensure_ascii=False).replace("\n", "\n    "))


def main() -> None:
    urn = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TEST_URN
    print(f"Write-back spike on: {urn}")

    client = DataHubClient()
    if not client.is_connected:
        print("Could not connect. Run: datahub docker quickstart")
        sys.exit(1)

    writer = DiagnosisWriter(client)

    print("1/2 - Writing test diagnosis...")
    mcps = _build_patch(urn).build()
    _print_mcps(mcps)

    try:
        client.graph.emit_mcps(mcps)
    except Exception:
        print("\nemit_mcps failed. Full traceback:\n")
        traceback.print_exc()
        print(
            "\nCheck: is config/agent_memory_property.yaml applied? "
            "does the URN exist? does the token have write permission?"
        )
        sys.exit(1)

    print("emit_mcps didn't raise an exception.")

    print("2/2 - Reading the diagnosis back...")
    read_back = writer.read_diagnosis(urn)

    if read_back and read_back["pattern_signature"] == _FAKE_REPORT["pattern_signature"]:
        print("Success! The episodic memory cycle works:")
        print(read_back)
    else:
        print("What was read doesn't match what was written (or came back empty):")
        print(read_back)
        sys.exit(1)


if __name__ == "__main__":
    main()
