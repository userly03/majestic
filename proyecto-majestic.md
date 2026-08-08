# Majestic — El investigador de causa raíz para tu ecosistema de datos

> Construido para *Build with DataHub: The Agent Hackathon*

## El problema: el detective ciego

Suena una alarma: *"El informe de ventas de hoy está vacío."*

Con las herramientas actuales, resolver esto es un proceso manual y lento:

1. Llega una alerta genérica — el dataset no se actualizó.
2. Investigas a ciegas, herramienta por herramienta: ¿se cayó el ETL? (Airflow). ¿cambió el esquema de origen? (Snowflake). ¿el owner está de vacaciones? (Slack).
3. Después de una hora saltando entre sistemas, descubres que un cambio en una tabla de marketing, tres saltos de lineage más arriba, rompió tu informe de ventas.

El problema no es la alerta. Es que ninguna herramienta conecta los puntos por ti — te dan señales sueltas, no un diagnóstico.

## La solución: un investigador de causa raíz, no otro monitor

Este agente lee el grafo de DataHub, cruza señales de distinta naturaleza (frescura, cambios de schema, ownership) en una sola cadena causal, y escribe ese diagnóstico de vuelta al grafo como metadata auditable. La próxima vez que ve el mismo patrón estructural en otra entidad, no vuelve a investigar desde cero.

**No es "detectar y alertar más rápido". Es explicar el *por qué*, cruzando dominios que hoy nadie conecta.**

## Por qué esto no es lo que DataHub ya hace

Comparación honesta — importa que sea precisa, no favorable:

| | DataHub (Smart Assertions + Actions Framework) | Este proyecto |
|---|---|---|
| Detecta anomalías | Sí — con ML adaptativo, aprende umbrales por dataset | No reinventa esto; consume las señales que DataHub ya expone |
| Responde a un evento | Sí — reglas configurables (ej. "si tag=PII, notifica a Slack") | No compite aquí tampoco |
| Cruza tipos de problema distintos en una sola causa raíz (frescura + ownership + schema change) | No | **Sí — este es el hueco real** |
| Generaliza un diagnóstico de una entidad a otra por estructura de grafo, no por regla predefinida | No | **Sí** |
| Persiste el razonamiento como metadata consultable y auditable | Parcial (incidents, sin cadena causal) | **Sí, con evidencia trazable** |

No decimos "somos los primeros en gobernanza con IA" — eso ya lo hace DataHub Cloud en producción. Decimos que el razonamiento causal transversal con memoria generalizable es el hueco que no cubren.

## Cómo funciona

**Fase 1 — Reconocimiento.** Lee lineage, schemas, ownership, freshness vía el SDK Python de DataHub (`DataHubGraph`, no un MCP Server — se evaluó y se optó por el SDK directo). Calcula métricas estructurales (profundidad, upstream/downstream count).

**Fase 2 — Diagnóstico.** Ante una anomalía, recorre el lineage hacia atrás buscando evidencia real en el grafo (no especulación del LLM). Máximo 3 eslabones causales, cada uno respaldado por un dato concreto: tag de incidente, ausencia de owner, dataset obsoleto (freshness) o schema modificado recientemente — cuatro tipos de evidencia implementados hoy en `src/core/diagnoser.py` (no incluye assertions de DataHub todavía). Si no hay evidencia, la cadena se detiene ahí.

**Fase 3 — Memoria.** Guarda el diagnóstico como `structuredProperties` sobre la entidad: una firma de patrón determinista (`tipo_anomalía:profundidad:upstream:downstream`), el diagnóstico en texto, un campo de **contexto de negocio / lección aprendida** (texto libre que un humano puede enriquecer al cerrar el incidente), y un score de confianza. Si el agente ve la misma firma en otra entidad, recupera el diagnóstico anterior en vez de razonar desde cero.

**Simulador de impacto (bonus, mismo mecanismo invertido).** El traversal de la Fase 1 funciona hacia arriba (upstream) para diagnóstico. El mismo código, recorriendo hacia abajo (downstream), responde antes de que un cambio se ejecute: *"si modificas este dataset, afectás N datasets downstream, M de ellos dashboards — estos son los owners a notificar."* Costo marginal mínimo porque reutiliza el traversal ya construido; no es un módulo nuevo, es el mismo con la dirección invertida. (Nota: hoy `ImpactSimulator` distingue datasets de dashboards, pero no subtipos como "modelos de ML" — la frase original de este pitch era una ilustración conceptual, no el formato de salida real; ver `src/impact/simulator.py`.)

## Qué NO construimos, y por qué

Decisión deliberada, no falta de tiempo:

- **Bot de Slack** — se evalúa solo si el núcleo funciona con margen de sobra. Agrega superficie de integración externa (OAuth, webhooks) antes de validar lo esencial.
- **Traductor lenguaje natural → glosario de negocio** — depende de que el datapack tenga Business Glossary poblado, algo no confirmado. No construimos sobre un supuesto sin verificar.
- **Predicción de fallos futuros ("80% de probabilidad en 48h")** — los datapacks de muestra son una carga estática, no una serie temporal real. Sin datos históricos reales, esa cifra sería inventada, no medida.
- **Time-travel debugging con aspectos versionados** — depende de capacidades de DataHub no confirmadas en esta sesión, y es esencialmente un segundo proyecto.
- **Chaos engineering / inyección de fallos activa** — implica modificar el entorno de datos bajo prueba; riesgo real de romper el propio demo antes de grabar el video.

### Estado de validación técnica

> Actualizado a lo largo de 4 rondas de blindaje (la última, validación en vivo contra DataHub real) — ver `docs/PROPOSAL.md` para el detalle completo de cada ronda.

- [x] `datahub properties upsert` con la definición de memoria episódica — YAML en `config/agent_memory_property.yaml`. **Se encontró y corrigió un bug real acá**: la primera versión usaba nombres de campo camelCase (`displayName`, `entityTypes`) que el modelo pydantic real del SDK rechaza (espera snake_case) — solo se detectó instalando el SDK y parseando el YAML de verdad, no leyendo la doc. `python3 main.py doctor` ahora lo registra automáticamente si falta.
- [x] Write-back de `structuredProperties` vía SDK Python — `src/memory/writer.py`, `DatasetPatchBuilder.add_structured_property` + `DataHubGraph.emit_mcps`. Cubierto por tests unitarios y por `tests/test_integration.py` (opt-in, contra una instancia real).
- [x] Lectura de vuelta de la memoria escrita — `DiagnosisWriter.read_diagnosis`, mismo mecanismo de validación.
- [x] Traversal de lineage upstream/downstream, incluida paginación multi-página — `src/graph/traversal.py`, BFS sobre `DataHubGraph.scroll_lineage`. Cubierto con tests unitarios (incluido el camino de paginación, que al principio no tenía ningún test).
- [x] Búsqueda de diagnósticos previos por firma de patrón entre entidades (`find_previous_diagnosis`) — **confirmado contra una instancia real** (2026-08-08): Plan A (filtro estructurado) encontró el diagnóstico previo correctamente en la corrida final; en una corrida anterior, mientras la indexación de Elasticsearch todavía no había alcanzado a ese documento, cayó automáticamente a Plan B (texto libre) sin romper el flujo — exactamente el comportamiento que este plan B fue diseñado para cubrir.
- [x] Conexión resiliente a que DataHub tarde en levantar o esté momentáneamente caído — reintentos con backoff (`tenacity`). **Otro hallazgo real**: el retry propio se multiplicaba con el retry interno del SDK, llevando el peor caso a ~90s antes de reportar error; medido y corregido a ~15s. Ver "Notas técnicas" en `README.md`.
- [x] **Pipeline completo corrido de punta a punta contra una instancia real de DataHub** (2026-08-08): `doctor` → `seed_demo_data.py` → `diagnose --explain --write` → `impact` → reuso de memoria en una segunda entidad. Encontró y corrigió, en el camino, un bug real de UI (ver `docs/PROPOSAL.md`, Ronda 4) — el mismo tipo de hallazgo que las rondas anteriores ya habían anticipado que solo aparece corriendo contra algo real.

**Los nombres de método y clases usados (`DataHubGraph.scroll_lineage`, `LineageDirection`, `DatasetPatchBuilder`, `StructuredPropertiesClass`, `StructuredProperties.from_yaml`) fueron confirmados instalando `acryl-datahub==1.7.0` en un entorno aislado e inspeccionando el SDK directamente**, no asumidos de la documentación — exactamente la precaución que esta sección pedía tomar, y que en varios casos concretos (el YAML, el retry, y el bug de UI de la Ronda 4) encontró bugs reales que la documentación no hubiera revelado.

## Estructura del repo

Ver [`README.md`](README.md#-arquitectura) para la versión siempre actualizada — acá solo el resumen de alto nivel:

```
Majestic/
├── main.py                # CLI: diagnose / impact / doctor
├── docker-compose.yml      # un comando para correr todo en contenedor
├── config/                 # configuración centralizada + definición de memoria episódica
├── src/
│   ├── graph/               # cliente DataHub + traversal BFS
│   ├── core/                 # orquestación, diagnóstico, síntesis narrativa opcional
│   ├── memory/                # write-back y lectura de memoria episódica
│   └── impact/                 # simulador de impacto downstream
├── scripts/                # spikes, seed de datos de demo, generador de examples/
├── tests/                   # unitarios (mocks) + integración (opt-in, DataHub real)
├── examples/                # outputs de ejemplo
└── .github/workflows/       # CI
```

## Setup

Ver [`README.md`](README.md#️-instalación-y-ejecución) para la versión completa y siempre actualizada. Resumen:

1. `datahub docker quickstart` — levanta DataHub localmente.
2. `pip install -r requirements.txt` (usar un virtualenv).
3. `cp .env.example .env`
4. `python3 main.py doctor` — un solo comando que reemplaza los pasos manuales de conexión + registro de properties + ciclo write/read.
5. `python3 scripts/seed_demo_data.py` — siembra un grafo con anomalía garantizada (no depende de que el datapack de muestra tenga lineage interesante por casualidad).
6. `python3 main.py diagnose "<urn>" --explain` — corre el pipeline completo.

## Prior art (verificado, no asumido)

- [Hermes Agent (Nous Research)](https://github.com/nousresearch/hermes-agent) — memoria persistente y auto-mejora de skills, pero memoria de conversación, no de gobernanza de datos.
- [Cognee](https://github.com/topoteretes/cognee) — grafo de conocimiento como memoria de agente, uso general, no diseñado para lineage de datos empresarial.
- [Memoria (Matrix Origin)](https://github.com/matrixorigin/Memoria) — "Git for Memory" con snapshots/rollback, enfocado en memoria conversacional de agentes de código.
- [DataHub Smart Assertions / Actions Framework](https://datahub.com/products/data-observability/) — detección adaptativa y automatización basada en eventos, sin razonamiento causal transversal ni memoria generalizable entre entidades.

Ninguno combina: agente autónomo sobre un grafo de *gobernanza de datos* + razonamiento causal cruzado entre dominios + memoria persistida como metadata nativa del propio grafo.

## Licencia

Apache 2.0 — ver `LICENSE`. (Requisito del hackathon: debe ser visible en la sección "About" del repo en GitHub.)

## Checklist de submission (Devpost)

- [ ] URL del proyecto (repo con instrucciones claras — no requiere deploy)
- [ ] Repo público en GitHub, con licencia Apache 2.0 visible en "About"
- [x] Descripción del proyecto — este mismo documento + `README.md`
- [ ] Video demo <3 min, YouTube/Vimeo público — guion listo y ensayado en `docs/DEMO_SCRIPT.md`, falta grabar
- [x] `examples/` con outputs reales — regenerado el 2026-08-08 corriendo el pipeline completo contra una instancia real de DataHub (no el `FakeDataHub`). Ver `examples/README.md` para el detalle y los comandos exactos usados.
- [ ] `examples/structured_property_screenshot.png` — captura manual de la UI de DataHub (única pieza que ningún script puede generar)
- [ ] Opcional: opt-in a la encuesta para el Bonus Prize ($50 x 10)
