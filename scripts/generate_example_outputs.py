"""
Genera los outputs de ejemplo en examples/ corriendo el código REAL del
agente (MajesticAgent, ImpactSimulator, DiagnosisWriter, narrator — las
mismas clases de producción, sin reimplementar ni simplificar la lógica)
contra un grafo falso en memoria, no contra una instancia real de DataHub.

Por qué existe esto: no hay una instancia de DataHub disponible en este
entorno para generar los outputs "reales" que pide el checklist de
submission (ver examples/README.md). Esto es honestamente un paso
intermedio — mejor que un JSON escrito a mano (que podía quedar
desincronizado del código real la próxima vez que algo cambie), pero NO
reemplaza correr esto contra DataHub de verdad antes de grabar el video.
Cuando haya una instancia real:

    python3 scripts/seed_demo_data.py
    python3 main.py diagnose "<urn_de_C>" --write --explain
    python3 main.py diagnose "<urn_de_F>"   # para el ejemplo de reuso
    python3 main.py impact "<urn_de_C>"

y reemplazar los archivos de examples/ con esos outputs reales (más la
captura de pantalla de la UI, que este script obviamente no puede generar).

Uso:
    python3 scripts/generate_example_outputs.py
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datahub.ingestion.graph.openapi import LineageDirection
from datahub.metadata.schema_classes import (
    DatasetLineageTypeClass,
    DatasetPropertiesClass,
    GlobalTagsClass,
    OwnershipClass,
    StatusClass,
    StructuredPropertiesClass,
    StructuredPropertyValueAssignmentClass,
    TagAssociationClass,
    UpstreamClass,
    UpstreamLineageClass,
)
from datahub.emitter.mcp import MetadataChangeProposalWrapper

import scripts.seed_demo_data as seed_mod
from src.core.agent import MajesticAgent
from src.core.narrator import explain
from src.impact.simulator import ImpactSimulator
from src.memory.writer import DiagnosisWriter

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"

# Segunda entidad, en otra parte del grafo, con la MISMA estructura que
# A→B→C (mismo tipo de evidencia, mismo hop, mismo fan-in/out) — para
# demostrar que la Fase 3 (memoria) reutiliza el diagnóstico de C en vez
# de razonar desde cero.
URN_H = "urn:li:dataset:(urn:li:dataPlatform:hive,majestic_demo.finance_raw,PROD)"
URN_G = "urn:li:dataset:(urn:li:dataPlatform:hive,majestic_demo.finance_etl,PROD)"
URN_F = "urn:li:dataset:(urn:li:dataPlatform:hive,majestic_demo.finance_report,PROD)"
DASHBOARD2_URN = "urn:li:dashboard:(looker,majestic_demo.finance_dashboard)"
TAG2_URN = "urn:li:tag:majestic_demo_incident_2"


class FakeDataHub:
    """
    Grafo falso en memoria con la misma forma de respuesta que
    DataHubGraph (scroll_lineage, get_aspect, emit_mcp, emit_mcps,
    get_urns_by_filter), para poder correr el código real del agente sin
    una instancia de DataHub corriendo. NO es un mock que finge éxito: de
    verdad guarda y responde con lo que se emitió, direction-aware.
    """

    def __init__(self):
        self.aspects: dict = {}
        self.edges: list = []  # (source_urn, dest_urn, source_type, dest_type)

    def emit_mcp(self, mcp):
        self.aspects.setdefault(mcp.entityUrn, {})[type(mcp.aspect)] = mcp.aspect
        if isinstance(mcp.aspect, UpstreamLineageClass):
            for up in mcp.aspect.upstreams:
                self.edges.append((up.dataset, mcp.entityUrn, "dataset", "dataset"))
        if type(mcp.aspect).__name__ == "DashboardInfoClass" and mcp.aspect.datasets:
            for ds_urn in mcp.aspect.datasets:
                self.edges.append((ds_urn, mcp.entityUrn, "dataset", "dashboard"))

    def get_aspect(self, urn, aspect_type, version=0):
        return self.aspects.get(urn, {}).get(aspect_type)

    def scroll_lineage(self, *, urns, direction, count, scroll_id):
        anchor = urns[0]
        rels = []
        for src, dst, src_t, dst_t in self.edges:
            if direction == LineageDirection.UPSTREAM and dst == anchor:
                rels.append(self._rel(src, dst, src_t, dst_t))
            elif direction == LineageDirection.DOWNSTREAM and src == anchor:
                rels.append(self._rel(src, dst, src_t, dst_t))
        return SimpleNamespace(relationships=rels, scroll_id=None)

    @staticmethod
    def _rel(src, dst, src_t, dst_t):
        return SimpleNamespace(
            source_urn=src, destination_urn=dst,
            source_entity_type=src_t, destination_entity_type=dst_t,
            relationship_type="DownstreamOf",
        )

    def emit_mcps(self, mcps):
        for mcp in mcps:
            if mcp.aspectName != "structuredProperties":
                continue
            patch = json.loads(mcp.aspect.value)
            existing = self.aspects.get(mcp.entityUrn, {}).get(StructuredPropertiesClass)
            props_by_urn = {p.propertyUrn: p for p in (existing.properties if existing else [])}
            for op in patch["patch"]:
                value = op["value"]
                prop_urn = value["propertyUrn"]
                raw_values = [list(v.values())[0] for v in value["values"]]
                props_by_urn[prop_urn] = StructuredPropertyValueAssignmentClass(
                    propertyUrn=prop_urn, values=raw_values
                )
            self.aspects.setdefault(mcp.entityUrn, {})[StructuredPropertiesClass] = (
                StructuredPropertiesClass(properties=list(props_by_urn.values()))
            )
        return []

    def get_urns_by_filter(self, *, entity_types=None, extraFilters=None, query=None, **kwargs):
        matches = []
        needle = extraFilters[0]["values"][0] if extraFilters else query
        for urn, aspects in self.aspects.items():
            props = aspects.get(StructuredPropertiesClass)
            if not props:
                continue
            all_values = [v for a in props.properties for v in a.values]
            if any(needle == v or needle in str(v) for v in all_values):
                matches.append(urn)
        return iter(matches)


def _seed_second_matching_entity(client) -> None:
    """H -> G -> F, mismo patrón que A -> B -> C: anomalía (tag de
    incidente) en G, dashboard downstream de F."""
    for urn, name in [(URN_H, "finance_raw"), (URN_G, "finance_etl"), (URN_F, "finance_report")]:
        client.graph.emit_mcp(MetadataChangeProposalWrapper(
            entityUrn=urn, aspect=DatasetPropertiesClass(name=name, description="[Majestic demo] Ejemplo de reuso de memoria."),
        ))
        client.graph.emit_mcp(MetadataChangeProposalWrapper(entityUrn=urn, aspect=StatusClass(removed=False)))

    client.graph.emit_mcp(MetadataChangeProposalWrapper(entityUrn=URN_G, aspect=OwnershipClass(owners=[])))
    client.graph.emit_mcp(MetadataChangeProposalWrapper(
        entityUrn=URN_G, aspect=UpstreamLineageClass(upstreams=[
            UpstreamClass(dataset=URN_H, type=DatasetLineageTypeClass.TRANSFORMED)
        ]),
    ))
    client.graph.emit_mcp(MetadataChangeProposalWrapper(
        entityUrn=URN_F, aspect=UpstreamLineageClass(upstreams=[
            UpstreamClass(dataset=URN_G, type=DatasetLineageTypeClass.TRANSFORMED)
        ]),
    ))
    client.graph.emit_mcp(MetadataChangeProposalWrapper(
        entityUrn=TAG2_URN, aspect=GlobalTagsClass(tags=[]),
    ))  # placeholder, se pisa abajo con el TagAssociation real
    client.graph.emit_mcp(MetadataChangeProposalWrapper(
        entityUrn=URN_G, aspect=GlobalTagsClass(tags=[TagAssociationClass(tag=TAG2_URN)]),
    ))

    from datahub.metadata.schema_classes import DashboardInfoClass, ChangeAuditStampsClass, AuditStampClass
    import time
    stamp = AuditStampClass(time=int(time.time() * 1000), actor="urn:li:corpuser:majestic_seed")
    client.graph.emit_mcp(MetadataChangeProposalWrapper(
        entityUrn=DASHBOARD2_URN,
        aspect=DashboardInfoClass(
            title="[Majestic demo] Dashboard de Finanzas",
            description="Ejemplo de reuso de memoria.",
            lastModified=ChangeAuditStampsClass(created=stamp, lastModified=stamp),
            datasets=[URN_F],
        ),
    ))


def _write_json(filename: str, data) -> None:
    path = EXAMPLES_DIR / filename
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"  ✓ {path.relative_to(EXAMPLES_DIR.parent)}")


def main() -> None:
    graph = FakeDataHub()
    client = SimpleNamespace(graph=graph, is_connected=True)

    print("1/4 — Sembrando A→B→C + dashboard (mismo grafo que seed_demo_data.py)...")
    seed_mod.seed(client)
    print("2/4 — Sembrando H→G→F + dashboard2 (misma estructura, para el ejemplo de reuso)...")
    _seed_second_matching_entity(client)

    agent = MajesticAgent(client)
    simulator = ImpactSimulator(client)
    writer = DiagnosisWriter(client)

    print("3/4 — Corriendo diagnose/impact/write reales sobre C...")
    report_c = agent.diagnose(seed_mod.URN_C)
    writer.write_report(seed_mod.URN_C, report_c, business_context="Generado por scripts/generate_example_outputs.py")
    impact_c = simulator.simulate(seed_mod.URN_C)
    explanation_c = explain(report_c)

    print("4/4 — Corriendo diagnose sobre F para mostrar el reuso de memoria...")
    report_f = agent.diagnose(URN_F)
    previous = writer.find_previous_diagnosis(report_f["pattern_signature"], exclude_urn=URN_F)

    EXAMPLES_DIR.mkdir(exist_ok=True)
    print("\nEscribiendo archivos:")
    _write_json("diagnosis_output.json", report_c)
    _write_json("impact_output.json", impact_c)
    (EXAMPLES_DIR / "explain_output.txt").write_text(explanation_c + "\n")
    print(f"  ✓ examples/explain_output.txt")
    _write_json(
        "memory_reuse_output.json",
        {
            "target_urn": URN_F,
            "target_pattern_signature": report_f["pattern_signature"],
            "reused_diagnosis_from": previous,
        },
    )

    assert report_c["pattern_signature"] == report_f["pattern_signature"], (
        "Las firmas de C y F deberían coincidir — revisar _seed_second_matching_entity."
    )
    assert previous is not None, "find_previous_diagnosis debería haber encontrado el diagnóstico de C."

    print("\n✅ Listo. Recordatorio: estos outputs vienen de código real contra un grafo")
    print("   falso en memoria, NO de una instancia de DataHub. Reemplazar antes de la")
    print("   submission — ver examples/README.md.")


if __name__ == "__main__":
    main()
