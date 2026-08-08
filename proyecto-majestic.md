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

**Fase 1 — Reconocimiento.** Lee lineage, schemas, ownership, freshness vía DataHub SDK/MCP Server. Calcula métricas estructurales (profundidad, upstream/downstream count).

**Fase 2 — Diagnóstico.** Ante una anomalía, recorre el lineage hacia atrás buscando evidencia real en el grafo (no especulación del LLM). Máximo 3 eslabones causales, cada uno respaldado por un dato concreto (timestamp, tag, owner, assertion). Si no hay evidencia, la cadena se detiene ahí.

**Fase 3 — Memoria.** Guarda el diagnóstico como `structuredProperties` sobre la entidad: una firma de patrón determinista (`tipo_anomalía:profundidad:upstream:downstream`), el diagnóstico en texto, un campo de **contexto de negocio / lección aprendida** (texto libre que un humano puede enriquecer al cerrar el incidente), y un score de confianza. Si el agente ve la misma firma en otra entidad, recupera el diagnóstico anterior en vez de razonar desde cero.

**Simulador de impacto (bonus, mismo mecanismo invertido).** El traversal de la Fase 1 funciona hacia arriba (upstream) para diagnóstico. El mismo código, recorriendo hacia abajo (downstream), responde antes de que un cambio se ejecute: *"si modificas esta columna, rompes 3 informes, 2 modelos de ML y 1 dashboard ejecutivo — estos son los owners a notificar."* Costo marginal mínimo porque reutiliza el traversal ya construido; no es un módulo nuevo, es el mismo con la dirección invertida.

## Qué NO construimos, y por qué

Decisión deliberada, no falta de tiempo:

- **Bot de Slack** — se evalúa solo si el núcleo funciona con margen de sobra. Agrega superficie de integración externa (OAuth, webhooks) antes de validar lo esencial.
- **Traductor lenguaje natural → glosario de negocio** — depende de que el datapack tenga Business Glossary poblado, algo no confirmado. No construimos sobre un supuesto sin verificar.
- **Predicción de fallos futuros ("80% de probabilidad en 48h")** — los datapacks de muestra son una carga estática, no una serie temporal real. Sin datos históricos reales, esa cifra sería inventada, no medida.
- **Time-travel debugging con aspectos versionados** — depende de capacidades de DataHub no confirmadas en esta sesión, y es esencialmente un segundo proyecto.
- **Chaos engineering / inyección de fallos activa** — implica modificar el entorno de datos bajo prueba; riesgo real de romper el propio demo antes de grabar el video.

### Estado de validación técnica

> Actualizado tras implementar contra el SDK real (no solo documentación).

- [x] `datahub properties upsert` con la definición de memoria episódica — YAML en `config/agent_memory_property.yaml`, formato acorde a la doc oficial de `acryl-datahub==1.7.0`. Pendiente de correr contra una instancia local real.
- [x] Write-back de `structuredProperties` vía SDK Python — implementado en `src/memory/writer.py` con `DatasetPatchBuilder.add_structured_property` + `DataHubGraph.emit_mcps`, métodos confirmados por introspección directa del SDK instalado (no asumidos de memoria). Cubierto por tests con mocks; falta correr `scripts/spike_writeback_test.py` contra una instancia real antes de la demo.
- [x] Lectura de vuelta de la memoria escrita — `DiagnosisWriter.read_diagnosis`, mismo caveat que el punto anterior.
- [x] Traversal de lineage upstream/downstream con la profundidad necesaria para el diagnóstico — `src/graph/traversal.py`, BFS multi-hop sobre `DataHubGraph.scroll_lineage`. Verificado con tests unitarios; falta validar el volumen/latencia real con un datapack cargado.
- [ ] Búsqueda de diagnósticos previos por firma de patrón entre entidades (`find_previous_diagnosis`) — usa un filtro de búsqueda sobre `structuredProperties.<qualifiedName>` cuyo nombre de campo exacto en Elasticsearch no está confirmado contra una instancia real. Es el ítem de mayor riesgo antes de grabar el video demo.

**Los nombres de método y clases usados (`DataHubGraph.scroll_lineage`, `LineageDirection`, `DatasetPatchBuilder`, `StructuredPropertiesClass`) fueron confirmados instalando `acryl-datahub==1.7.0` en un entorno aislado e inspeccionando el SDK directamente**, no asumidos de la documentación — exactamente la precaución que esta sección pedía tomar.

## Estructura del repo

```
Majestic/
├── main.py                          # entrypoint CLI (diagnose / impact)
├── config/
│   ├── settings.py                   # configuración centralizada
│   └── agent_memory_property.yaml    # definición de la memoria episódica
├── src/
│   ├── graph/
│   │   ├── client.py                  # DataHubClient (wrapper sobre DataHubGraph)
│   │   └── traversal.py               # LineageTraversal — BFS upstream/downstream
│   ├── core/
│   │   ├── agent.py                   # MajesticAgent — orquesta las 3 fases
│   │   └── diagnoser.py               # RootCauseDiagnoser — evidencia + cadena causal
│   ├── memory/
│   │   └── writer.py                  # DiagnosisWriter — write-back y lectura de memoria
│   └── impact/
│       └── simulator.py               # ImpactSimulator
├── scripts/
│   └── spike_writeback_test.py
├── spike_test.py
├── tests/
└── README.md
```

(Nota: el repo real usa `src/` como paquete raíz en vez de `core/` en la raíz, y `writer.py` en vez de `memory.py`, para dejar más claro que cada carpeta es un módulo con una sola responsabilidad. Ver `README.md` para la versión siempre actualizada de esta estructura.)

## Setup

1. `datahub docker quickstart` — levanta DataHub localmente.
2. (Opcional) `datahub datapack load nyc-taxi` (o el datapack elegido) para tener lineage real sobre el que diagnosticar.
3. `pip install -r requirements.txt` (usa un virtualenv; ver README.md).
4. `datahub properties upsert -f config/agent_memory_property.yaml`
5. `python3 spike_test.py` — confirma la conexión.
6. `python3 scripts/spike_writeback_test.py` — confirma el ciclo completo de memoria antes de correr el agente.
7. `python3 main.py diagnose "<urn>"` — corre el pipeline completo.

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
- [ ] Repo público, Apache 2.0 visible en "About"
- [ ] Descripción del proyecto
- [ ] Video demo <3 min, YouTube/Vimeo público
- [ ] `examples/` con outputs reales (diagnóstico generado, captura de la structured property en la UI de DataHub)
- [ ] Opcional: opt-in a la encuesta para el Bonus Prize ($50 x 10)
