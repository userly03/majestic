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
├── main.py                      # entrypoint CLI (diagnose / impact / doctor)
├── config/
│   ├── settings.py               # configuración centralizada (URL/token DataHub, umbrales)
│   └── agent_memory_property.yaml  # definición de las structured properties de memoria
├── src/
│   ├── graph/
│   │   ├── client.py              # DataHubClient — wrapper sobre DataHubGraph
│   │   └── traversal.py           # LineageTraversal — BFS upstream/downstream
│   ├── core/
│   │   ├── agent.py               # MajesticAgent — orquesta las 3 fases
│   │   └── diagnoser.py           # RootCauseDiagnoser — evidencia + cadena causal
│   ├── memory/
│   │   └── writer.py              # DiagnosisWriter — write-back y lectura de memoria
│   └── impact/
│       └── simulator.py           # ImpactSimulator — impacto downstream de un cambio
├── scripts/
│   ├── spike_test.py              # valida solo la conexión a DataHub
│   ├── seed_demo_data.py          # siembra un grafo sintético con anomalía garantizada para la demo
│   ├── generate_example_outputs.py  # regenera examples/ corriendo el agente real (no una instancia real de DataHub)
│   └── spike_writeback_test.py   # valida el ciclo completo de memoria, con el JSON exacto que se envía
├── docker-compose.yml            # un comando para correr todo en contenedor
├── tests/                        # 46 unitarios (mocks) + 4 de integración (opt-in, DataHub real)
├── examples/                     # outputs de ejemplo — ver examples/README.md sobre qué tan "reales" son hoy
└── docs/
    ├── PROPOSAL.md                # análisis técnico y bitácora de las 4 rondas de blindaje
    └── DEMO_SCRIPT.md             # guion cronometrado (≤3:00) para grabar el video de submission
```

- `src/graph`: cliente y traversal sobre DataHub (GMS).
- `src/core`: orquestación del agente y razonamiento de causa raíz (Fase 1 y 2).
- `src/memory`: lectura/escritura de la memoria episódica como structured properties (Fase 3).
- `src/impact`: simulador de impacto downstream (bonus).

## ⚙️ Instalación y ejecución

### 1. Levantar DataHub localmente

```bash
datahub docker quickstart
```

### 2. Instalar dependencias

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
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

## 🧪 Tests

```bash
pip install -r requirements.txt
pytest                                          # 46 tests unitarios (mocks, siempre corren)
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
- **Tests**: 46 unitarios (100% mocks, corren siempre) + 4 de integración (`tests/test_integration.py`, marcados `@pytest.mark.integration`, se saltan por defecto — requieren `MAJESTIC_RUN_INTEGRATION_TESTS=1` y una instancia real). `.github/workflows/ci.yml` corre `pytest -m "not integration"` y valida que la imagen Docker construye en cada push. Los de integración cubren, contra DataHub real: el ciclo write/read de memoria, que `find_previous_diagnosis` encuentra lo que se acaba de escribir (valida en runtime si Plan A funciona o si hizo falta Plan B), y que diagnosticar el grafo sembrado por `seed_demo_data.py` encuentra la causa raíz en B.
- **`_EVIDENCE_WEIGHTS` (en `src/core/diagnoser.py`) es un ranking razonado, no una calibración estadística — a propósito.** No existe un dataset de incidentes reales resueltos contra el cual ajustar `incident_tag=0.9 > schema_change=0.7 > stale_data=0.5 > unowned=0.3`. Lo defendible es el *orden*: especificidad y fuerza causal de la señal (una etiqueta puesta por un humano dice más que la mera ausencia de owner). Los valores absolutos son arbitrarios dentro de ese orden. Si un jurado pregunta "¿por qué 0.75 y no 0.9?", la respuesta honesta es esa — no fingir una precisión que no se midió, mismo criterio que el proyecto ya aplica para no inventar "80% de probabilidad de fallo en 48h" sin datos históricos (ver `proyecto-majestic.md`).
- **`--explain` no llama a ningún LLM todavía, a propósito.** `src/core/narrator.py` tiene la interfaz lista (`explain(report) -> str`) pero hoy es una plantilla determinística sobre la `causal_chain` ya extraída — sin API key, sin costo, sin un nuevo punto de falla de red en la demo. La pregunta de un *Agent Hackathon* ("¿dónde está el agente/LLM?") tiene una respuesta a propósito: el razonamiento sobre el grafo (qué es evidencia, qué es la causa raíz) es 100% determinístico y trazable — eso no se delega a un LLM ni ahora ni si se agrega uno después. Si en algún momento se elige un proveedor, el lugar exacto para enchufarlo es el cuerpo de `explain()`; la firma no cambia, así que no hay que tocar `agent.py` ni `main.py`.

## Licencia

Apache 2.0 — ver [`LICENSE`](LICENSE).
