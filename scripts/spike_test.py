"""
Validation spike: tests that the DataHub connection works.
This is the first script run to verify the setup.
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.graph.client import DataHubClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)


def main():
    print("Starting Majestic connection test...")

    client = DataHubClient()

    if client.is_connected:
        print("Success! DataHub is responding.")
        print("We can now start building the agent.")
    else:
        print("Could not connect. Make sure DataHub is running.")
        print("   Run: datahub docker quickstart")


if __name__ == "__main__":
    main()
