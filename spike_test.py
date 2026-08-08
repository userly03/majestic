"""
Spike de validación: prueba que la conexión con DataHub funciona.
Este es el primer script que corremos para verificar el setup.
"""

import logging

from src.graph.client import DataHubClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)


def main():
    print("🚀 Iniciando prueba de conexión Majestic...")

    client = DataHubClient()

    if client.is_connected:
        print("🎉 ¡Éxito! DataHub responde.")
        print("Ahora podemos empezar a construir el agente.")
    else:
        print("⚠️  No se pudo conectar. Asegúrate de tener DataHub corriendo.")
        print("   Ejecuta: datahub docker quickstart")


if __name__ == "__main__":
    main()