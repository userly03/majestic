# 🚀 Proyecto Majestic

**El investigador de causa raíz para tu ecosistema de datos**

> Construido para *Build with DataHub: The Agent Hackathon*. Ver [`proyecto-majestic.md`](proyecto-majestic.md) para el pitch completo (problema, comparación honesta con DataHub, qué no construimos y por qué).

## 📖 Descripción

Majestic es un agente que lee el grafo de linaje de DataHub, cruza señales de distinta naturaleza (frescura, cambios de schema, ownership) en una sola cadena causal, y escribe ese diagnóstico de vuelta al grafo como metadata auditable. La próxima vez que ve el mismo patrón estructural en otra entidad, reutiliza el diagnóstico en vez de razonar desde cero. También simula el impacto downstream de un cambio antes de ejecutarlo, reutilizando el mismo traversal en dirección inversa.

## 🛠️ Requisitos

- Docker y Docker Compose instalados (para levantar DataHub localmente).
- Python 3.10+ para desarrollo local (aunque se recomienda Docker para correr el agente).

## 🏗️ Arquitectura

```
Majestic/
├── main.py                      # entrypoint CLI (diagnose / impact / check-change / doctor)
├── config/
│   ├── settings.py               # configuración centralizada (URL/token DataHub, umbrales)
│   └── agent_memory_property.yaml  # definición de las structured properties de memoria
├── src/
│   ├── graph/
│   │   ├── client.py              # DataHubClient — wrapper sobre DataHubGraph
│   │   └── traversal.py           # LineageTraversal — BFS upstream/downstream
│   ├── core/
│   │   ├── agent.py               # MajesticAgent — orquesta las 3 fases
│   │   ├── diagnoser.py           # RootCauseDiagnoser — evidencia + cadena causal + lag-aware
│   │   └── narrator.py            # explain() — síntesis en lenguaje natural del diagnóstico
│   ├── memory/
│   │   └── writer.py              # DiagnosisWriter — write-back y lectura de memoria
│   ├── impact/
│   │   ├── simulator.py           # ImpactSimulator — impacto downstream de un cambio
│   │   └── risk_assessor.py       # RiskAssessor — blast radius + orfandad → gate de CI/CD
│   ├── events/
│   │   └── listener.py            # IncidentListener — polling que dispara diagnose automático
│   └── mcp_server.py              # servidor MCP — expone diagnose/impact a otros agentes
├── scripts/
│   ├── spike_test.py              # valida solo la conexión a DataHub
│   ├── seed_demo_data.py          # siembra un grafo sintético con anomalía garantizada para la demo
│   ├── seed_lag_aware_demo.py     # siembra un escenario fan-in para exhibir el decaimiento por antigüedad
│   ├── generate_example_outputs.py  # regenera examples/ corriendo el agente real (no una instancia real de DataHub)
│   └── spike_writeback_test.py   # valida el ciclo completo de memoria, con el JSON exacto que se envía
├── docker-compose.yml            # un comando para correr todo en contenedor
├── tests/                        # 79 unitarios (mocks) + 4 de integración (opt-in, DataHub real)
├── examples/                     # outputs de ejemplo — ver examples/README.md sobre qué tan "reales" son hoy
├── AUDIT_REPORT.md                # autoauditoría sin filtro contra los criterios del jurado
└── docs/
    ├── PROPOSAL.md                # análisis técnico y bitácora de las 4 rondas de blindaje
    ├── LAG_AWARE_DIAGNOSIS.md     # diseño y validación en vivo del mecanismo lag-aware
    └── DEMO_SCRIPT.md             # guion cronometrado (≤3:00) para grabar el video de submission
```

- `src/graph`: cliente y traversal sobre DataHub (GMS).
- `src/core`: orquestación del agente y razonamiento de causa raíz (Fase 1 y 2), más la síntesis narrativa opcional.
- `src/memory`: lectura/escritura de la memoria episódica como structured properties (Fase 3).
- `src/impact`: simulador de impacto downstream y el gate de riesgo que lo consume (`check-change`).
- `src/events`: listener de incidentes por polling (dispara `diagnose` sin que nadie lo pida).
- `src/mcp_server.py`: mismo core, expuesto como herramientas MCP en vez de CLI — ver "Servidor MCP" más abajo.

## ⚙️ Instalación y ejecución

### 1. Levantar DataHub localmente

```bash
datahub docker quickstart
```

### 2. Instalar dependencias

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt          # solo lo que necesita la CLI en producción
# pip install -r requirements-dev.txt    # + pytest y el SDK de MCP, para desarrollo/demo
```

### 3. Configurar variables de entorno

```bash
cp .env.example .env
# Editar .env si tu instancia no corre en http://localhost:8080 o requiere token
```

### 4. Validar el setup

```bash
python3 main.py doctor
```

Un solo comando que reemplaza 3 pasos manuales: revisa la conexión a DataHub, registra `config/agent_memory_property.yaml` si todavía no está aplicado (equivalente a `datahub properties upsert -f ...`), y corre un ciclo rápido de escritura/lectura para confirmar permisos. Termina con un resumen ✅/❌ por paso.

(La versión larga, paso a paso, sigue disponible: `python3 scripts/spike_test.py` para solo probar conexión, y `python3 scripts/spike_writeback_test.py` para ver el JSON exacto del ciclo de memoria — útil para debuggear si `doctor` da ❌ en el paso 3.)

### 5. Sembrar datos de demo (recomendado)

El datapack de muestra de `datahub docker quickstart` no garantiza tener una anomalía real en su lineage. Este script sí:

```bash
python3 scripts/seed_demo_data.py
```

Crea un mini-grafo A → B → C con una anomalía real en B (tag de incidente + sin owner) y un dashboard downstream de C, para que diagnosticar C siempre encuentre una causa raíz y `impact` siempre tenga un dashboard que contar.

### 6. Correr el agente

```bash
# Diagnosticar la causa raíz de un URN (usar el URN de C que imprime el seed script)
python3 main.py diagnose "urn:li:dataset:(urn:li:dataPlatform:hive,majestic_demo.sales_report,PROD)"

# Persistir el diagnóstico en DataHub como structured properties
python3 main.py diagnose "<urn>" --write --business-context "texto opcional"

# Redactar la cadena de evidencia en lenguaje natural (plantilla
# determinística hoy, no llama a ningún LLM externo — ver "Notas técnicas")
python3 main.py diagnose "<urn>" --explain

# Simular el impacto downstream de un cambio antes de ejecutarlo
python3 main.py impact "<urn>"

# --quiet suprime los logs internos (conexión, traversal...) y deja solo
# el resultado final — para compartir pantalla en la demo. Va ANTES del
# subcomando.
python3 main.py --quiet diagnose "<urn>" --explain
```

### Con Docker

Con `docker compose` (recomendado — un solo comando, ver `docker-compose.yml`):

```bash
docker compose up                                                  # corre scripts/spike_test.py, valida conexión
docker compose run --rm majestic python main.py doctor
docker compose run --rm majestic python main.py diagnose "<urn>" --explain
docker compose run --rm majestic python scripts/seed_demo_data.py
```

El primer build tarda varios minutos (la dependencia `acryl-datahub` es pesada); los siguientes usan cache. Verificado de punta a punta: build real + `docker compose run ... python main.py doctor` contra un DataHub inexistente falla en ~15s con el mensaje esperado, no se cuelga ni tira un traceback.

O sin compose, directo con `docker`:

```bash
docker build -t majestic .
docker run --rm --network host --env-file .env majestic
docker run --rm --network host --env-file .env majestic python main.py diagnose "<urn>"
```

## 🔌 Servidor MCP

`main.py` no es el único frontend sobre `MajesticAgent`/`ImpactSimulator` — `src/mcp_server.py` expone el mismo core como dos herramientas MCP (`majestic_diagnose`, `majestic_impact`) para que otros agentes las invoquen directamente, sin pasar por la CLI:

```bash
pip install -r requirements-dev.txt   # instala el SDK de MCP
python3 -m src.mcp_server              # sirve por stdio (el transporte que usan
                                         # Claude Desktop y la mayoría de clientes MCP)
```

No es una reimplementación: es un adaptador nuevo (~100 líneas) sobre las mismas clases que ya usa `main.py`, sin tocar `agent.py`/`simulator.py`. Probado de punta a punta contra el DataHub real que corrió esta sesión (`majestic_diagnose`/`majestic_impact` invocados directamente, mismo resultado que la CLI).

## 🧪 Tests

```bash
pip install -r requirements-dev.txt
pytest                                          # 79 tests unitarios (mocks, siempre corren)
MAJESTIC_RUN_INTEGRATION_TESTS=1 pytest -m integration   # 4 tests contra DataHub real (ver Notas técnicas)
```

Los unitarios corren automáticamente en cada push vía `.github/workflows/ci.yml` (junto con el build de la imagen Docker). Los de integración son manuales — no hay DataHub disponible en CI.

## Estado de validación técnica

- [x] Traversal de lineage upstream/downstream, incluida paginación multi-página, vía `DataHubGraph.scroll_lineage` — verificado por introspección directa del SDK instalado (`acryl-datahub==1.7.0`) y por tests unitarios.
- [x] Write-back de `structuredProperties` vía `DatasetPatchBuilder.add_structured_property` + `emit_mcps` — cubierto por tests unitarios y por `tests/test_integration.py` (opt-in, contra una instancia real).
- [x] Lectura de vuelta de la memoria escrita — `DiagnosisWriter.read_diagnosis`, mismo mecanismo de validación.
- [x] Búsqueda de diagnósticos previos por firma de patrón (`find_previous_diagnosis`) — confirmado contra una instancia real: Plan A (filtro estructurado) encontró el diagnóstico previo correctamente; el plan B (texto libre) también se ejercitó en runtime, en una corrida donde la indexación de Elasticsearch todavía no había alcanzado al documento, y funcionó como respaldo sin romper el flujo.
- [x] `python3 main.py doctor` — conexión + registro de properties + ciclo write/read en un solo comando, con timeout y retry acotados (~15s peor caso si DataHub no responde).
- [x] **Pipeline completo corrido de punta a punta contra una instancia real de DataHub** (2026-08-08): `doctor` → `seed_demo_data.py` → `diagnose --explain --write` → `impact` → reuso de memoria en una segunda entidad. Encontró y corrigió un bug real en el camino (ver primera nota técnica abajo) — exactamente el tipo de hallazgo que ningún test contra mocks puede atrapar.

Ver la sección "Estado de validación técnica" en [`proyecto-majestic.md`](proyecto-majestic.md) para el detalle completo y el razonamiento detrás de cada decisión.

## Notas técnicas (riesgos conocidos y hallazgos reales)

- **Bug real de la UI de DataHub, encontrado validando en vivo y neutralizado en nuestro código.** La UI de DataHub intenta resolver como referencia a otra entidad (`valueEntities`) cualquier valor de structured property que *contenga* algo con forma de URN (`urn:li:...(...)`) — y ese resolver tiene un bug propio de DataHub que rompe la página completa (`IllegalArgumentException: No enum constant ...FabricType.$UNKNOWN`). El `reason` que arma `RootCauseDiagnoser` siempre embebe el URN de la entidad causal en la oración, así que cualquier diagnóstico real lo disparaba. No es un bug nuestro, pero es nuestro texto el que lo activaba — `src/memory/writer.py::_sanitize_urn_lookalikes` lo neutraliza insertando un espacio de ancho cero dentro de `"urn:li:"` antes de persistir el valor (invisible al leerlo, rompe la detección de la UI). Confirmado antes/después contra la API real de GMS.
- **`DiagnosisWriter.find_previous_diagnosis` tiene un plan B, y ambos caminos ya se ejercitaron contra una instancia real.** Busca entidades con la misma firma de patrón con un filtro estructurado (`get_urns_by_filter` con `extraFilters` sobre `structuredProperties.<qualifiedName>` — Plan A). Si Plan A lanza una excepción, o "funciona" pero no devuelve nada, `_search_by_pattern_signature` cae automáticamente a una búsqueda de texto libre (`query=`, Plan B) que no depende de ese nombre de campo — y cualquier resultado de Plan B se re-valida contra la firma exacta antes de reutilizarlo, para no dar por buena una coincidencia parcial de texto libre. Ninguno de los dos planes puede tirar abajo `diagnose`: si ambos fallan, `find_previous_diagnosis` devuelve `None` (equivalente a "no se encontró memoria previa"), nunca una excepción.
- **Reintentos de conexión, con un hallazgo real detrás.** `DataHubClient` reintenta la conexión inicial hasta 3 veces con backoff exponencial (`tenacity`) antes de darse por vencido. Pero el SDK *ya* reintenta cada request HTTP internamente (`DatahubClientConfig.retry_max_times`, default 4, con backoff propio) — y ese default retría incluso "connection refused", no solo 5xx. Medido contra un GMS caído: un solo `test_connection()` con el default tardaba **28s** en fallar; con nuestro retry de 3 intentos encima, hasta **~90s** antes de reportar "no se pudo conectar" — inaceptable en vivo. Bajamos `retry_max_times` a 2 (`config/settings.py`), lo que baja el peor caso medido a **~15s**. Este hallazgo salió de escribir `tests/test_integration.py` y correrlo de verdad contra un endpoint inexistente, no de leer el código — es exactamente el tipo de bug que un test 100% mockeado no puede atrapar.
- **Tests**: 79 unitarios (100% mocks, corren siempre) + 4 de integración (`tests/test_integration.py`, marcados `@pytest.mark.integration`, se saltan por defecto — requieren `MAJESTIC_RUN_INTEGRATION_TESTS=1` y una instancia real). `.github/workflows/ci.yml` corre `pytest -m "not integration"` y valida que la imagen Docker construye en cada push. Los de integración cubren, contra DataHub real: el ciclo write/read de memoria, que `find_previous_diagnosis` encuentra lo que se acaba de escribir (valida en runtime si Plan A funciona o si hizo falta Plan B), y que diagnosticar el grafo sembrado por `seed_demo_data.py` encuentra la causa raíz en B.
- **Los pesos de evidencia son configurables y auditables, no una caja negra.** El *orden* relativo (`incident_tag > schema_change > stale_data > unowned`) refleja especificidad y fuerza causal de cada señal (una etiqueta puesta por un humano dice más que la mera ausencia de owner). Los valores por defecto (0.9/0.7/0.5/0.3, en `config/settings.py` vía `MAJESTIC_EVIDENCE_WEIGHT_*`) no están calibrados contra un dataset de incidentes reales — pero, a diferencia de una constante enterrada en el código, cualquier equipo con ese historial puede recalibrarlos sin tocar `diagnoser.py`. Si un jurado pregunta "¿por qué 0.75 y no 0.9?", la respuesta es: ese es exactamente el número que ustedes pueden cambiar una vez que tengan datos — el proyecto no finge una precisión que no midió, pero tampoco la deja fuera de alcance.
- **El razonamiento causal es 100% determinístico y trazable — decisión de arquitectura, no una feature pendiente.** `RootCauseDiagnoser` nunca alucina un eslabón: cada uno en `causal_chain` está respaldado por un dato concreto leído del grafo (tag, schema, freshness, ownership), y si un salto no tiene evidencia, la cadena se corta ahí en vez de rellenarse con una suposición. `--explain` (`src/core/narrator.py`) redacta esa cadena ya verificada en una plantilla determinística — sin llamar a ningún proveedor externo, sin API key, sin un punto de falla de red nuevo en producción. La pregunta de un *Agent Hackathon* ("¿dónde está el agente/LLM?") tiene una respuesta concreta: separar "qué es evidencia" (el grafo, nunca un LLM) de "cómo se redacta" (donde un LLM sí podría enchufarse después, sin poder inventar un eslabón que el grafo no respalde) es la garantía de cero alucinación del sistema, no un hueco a tapar. La firma de `explain(report) -> str` ya está lista para ese día sin tocar `agent.py` ni `main.py`.
- **La cadena causal agrupa por profundidad (hop), no por camino específico desde el target — limitación conocida, no un bug.** `RootCauseDiagnoser.analyze()` busca evidencia en *cualquier* nodo a una profundidad dada (`nodes_by_hop`), no en un único camino de lineage desde el target. Si hay dos ramas de lineage distintas, la evidencia de la rama A a hop 2 puede aparecer en la cadena aunque el nodo relevante para el target real esté en la rama B. Es una simplificación razonable para el alcance de un hackathon — el escenario típico (una sola cadena lineal o un fan-in simple, como los que siembran `scripts/seed_demo_data.py` y `scripts/seed_lag_aware_demo.py`) no la ejercita — pero un grafo con ramas anchas y evidencia dispersa sí la notaría. Documentado acá para que no sea un hallazgo sorpresa de un jurado que lee el código.
- **La firma de patrón de memoria puede generar falsos positivos — mitigado, no eliminado.** `pattern_signature` (`src/core/agent.py::_build_pattern_signature`) reconoce el mismo patrón estructural en otra entidad para reutilizar un diagnóstico. Hasta el 2026-08-08 el formato era `tipo:hop:upstream:downstream`, sin ningún ancla de dominio — dos datasets completamente no relacionados con la misma forma estructural producían la misma firma. Se agregó la plataforma del nodo causal (`urn:li:dataPlatform:...`, ya disponible en el URN, sin llamada extra) como cuarto componente (`tipo:hop:upstream:downstream:plataforma`): reduce colisiones entre plataformas distintas, pero **no** entre dos datasets no relacionados de la misma plataforma. Por eso el mensaje de reuso en `main.py cmd_diagnose` es explícito ("coincidencia ESTRUCTURAL, no confirmación de mismo incidente") en vez de presentar la reutilización como un hecho confiable sin matices. Ver `AUDIT_REPORT.md`, Sección 2, ítem 1, para el hallazgo original.
- **Mecanismo "lag-aware": pesos dinámicos por antigüedad + descuento por herencia + top-K rankeado — diseño propio, no una cita académica.** `RootCauseDiagnoser` ya no usa solo el peso fijo del tipo de evidencia: para `schema_change`/`stale_data` (que sí tienen timestamp real) aplica un decaimiento exponencial por antigüedad (`adjusted_weight`, nunca llega a cero), y si el mismo tipo de evidencia aparece en dos hops consecutivos, descuenta el más cercano al target por ser probablemente heredado del hop más lejano, no una señal independiente. `analyze()` también devuelve `ranked_candidates` (top-K, no solo una respuesta) para no esconder la ambigüedad cuando hay 2+ causas plausibles. **Aviso de origen, sin vueltas:** esta idea nació de un intento de citar un paper ("LagRCA", supuesto premio de FSE 2026) que resultó ser una alucinación — verificado contra el programa oficial de la conferencia, no existe ahí. La idea técnica en sí era buena, así que se implementó como diseño original de Majestic (ver `docs/LAG_AWARE_DIAGNOSIS.md` para el detalle completo), sin ninguna cita falsa. Lo que sí está citado y verificado en fuente primaria es el prior art real de RCA en microservicios — MicroRCA, Microscope, TraceDiag, DynaCausal, IDI — ver `docs/PROPOSAL.md`.

## Licencia

Apache 2.0 — ver [`LICENSE`](LICENSE).
