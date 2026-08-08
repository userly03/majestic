"""
Síntesis narrativa opcional del diagnóstico (docs/PROPOSAL.md, sección 3.4).

Toma un `report` ya generado por MajesticAgent.diagnose() — evidencia ya
extraída y verificada contra el grafo — y lo redacta en lenguaje natural
para un humano. Este módulo NUNCA decide qué es evidencia ni inventa
eslabones: solo redacta sobre hechos que RootCauseDiagnoser ya extrajo y
verificó. Esa separación es la que permite, más adelante, enchufar un LLM
real acá sin arriesgar que alucine la cadena causal — el LLM (si se agrega)
solo tendría el trabajo de fraseo, no de razonamiento sobre el grafo.

Estado actual: `explain()` es una plantilla determinística, sin llamar a
ningún proveedor externo (sin API key, sin costo, sin nuevo punto de falla
en la demo). El equipo decidió no elegir proveedor todavía — ver
docs/PROPOSAL.md 3.4. Cuando se elija uno (Anthropic, OpenAI, etc.), la forma de
enchufarlo es reemplazar el cuerpo de `explain()` por una llamada real que
reciba el mismo `report` y devuelva un string; la firma no cambia, así que
nada en agent.py/main.py necesita tocarse.
"""

from typing import Any, Dict, List


def explain(report: Dict[str, Any]) -> str:
    """
    Redacta en lenguaje natural el diagnóstico de MajesticAgent.diagnose().

    Args:
        report: el dict que devuelve MajesticAgent.diagnose() (target_urn,
            root_cause_urn, reason, causal_chain, confidence, ...).

    Returns:
        Un párrafo legible para humanos. Nunca lanza excepción por sí
        mismo — si el reporte no trae cadena causal, explica eso también.
    """
    target_urn = report.get("target_urn", "el dataset diagnosticado")
    causal_chain: List[Dict[str, Any]] = report.get("causal_chain") or []

    if not causal_chain:
        return (
            f"No se encontró evidencia concreta upstream de {target_urn}. "
            "Puede ser que el dato esté sano, que la anomalía esté más allá "
            "de la profundidad de búsqueda configurada, o que el problema no "
            "deje rastro en tags, ownership, freshness ni schema — las únicas "
            "señales que este agente sabe leer hoy."
        )

    steps = "\n".join(
        f"  {i}. Salto {link['hop']} ({link['urn']}): {link['evidence']}."
        for i, link in enumerate(causal_chain, start=1)
    )

    root_cause_urn = report.get("root_cause_urn")
    confidence = report.get("confidence", 0.0)

    return (
        f"El problema en {target_urn} parece originarse en {root_cause_urn}. "
        f"Cadena de evidencia encontrada recorriendo el linaje hacia atrás:\n"
        f"{steps}\n"
        f"Se elige {root_cause_urn} como causa raíz por ser el eslabón "
        f"evidenciado más lejano upstream: cuanto más lejos en el linaje y "
        f"con evidencia real (no solo el primer sospechoso), más probable "
        f"que sea el origen del problema y no un síntoma derivado de él. "
        f"Confianza heurística: {confidence * 100:.0f}% "
        f"(ranking razonado, no una probabilidad calibrada — ver README)."
    )
