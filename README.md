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
│   ├── seed_demo_data.py          # siembra un grafo sintético con anomalía garantizada para la demo
│   └── spike_writeback_test.py   # valida el ciclo completo de memoria antes de correr el agente
├── spike_test.py                 # valida solo la conexión a DataHub
├── tests/                        # tests de humo por módulo (mocks sobre DataHubClient)
└── examples/                     # outputs reales de ejemplo (para la submission)
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

(La versión larga, paso a paso, sigue disponible: `python3 spike_test.py` para solo probar conexión, y `python3 scripts/spike_writeback_test.py` para ver el JSON exacto del ciclo de memoria — útil para debuggear si `doctor` da ❌ en el paso 3.)

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

# Simular el impacto downstream de un cambio antes de ejecutarlo
python3 main.py impact "<urn>"
```

### Con Docker

```bash
docker build -t majestic .
docker run --rm --network host --env-file .env majestic
```

Por defecto el contenedor corre `spike_test.py` (valida conexión). Para correr el agente completo, sobrescribe el comando:

```bash
docker run --rm --network host --env-file .env majestic python main.py diagnose "<urn>"
```

## 🧪 Tests

```bash
pip install -r requirements.txt
pytest
```

Corre automáticamente en cada push vía `.github/workflows/ci.yml` (24 tests unitarios + build de la imagen Docker).

## Estado de validación técnica

- [x] Traversal de lineage upstream/downstream vía `DataHubGraph.scroll_lineage` — verificado por introspección directa del SDK instalado (`acryl-datahub==1.7.0`).
- [x] Write-back de `structuredProperties` vía `DatasetPatchBuilder.add_structured_property` + `emit_mcps` — implementado, cubierto por tests unitarios con mocks; **falta correrlo contra una instancia real** con `scripts/spike_writeback_test.py`.
- [x] Lectura de vuelta de la memoria escrita — implementado en `DiagnosisWriter.read_diagnosis`, mismo caveat que el punto anterior.
- [x] Búsqueda de diagnósticos previos por firma de patrón (`find_previous_diagnosis`) — el nombre exacto del campo de búsqueda para structured properties en Elasticsearch sigue sin confirmar contra una instancia real, pero ahora tiene un plan B de texto libre si el filtro estructurado falla o no encuentra nada (ver "Notas técnicas"). Igual es el primer ítem a correr con `scripts/spike_writeback_test.py` antes de la demo.

Ver la sección "Estado de validación técnica" en [`proyecto-majestic.md`](proyecto-majestic.md) para el detalle completo y el razonamiento detrás de cada decisión.

## Notas técnicas (riesgos conocidos)

Transparencia sobre lo que todavía no está probado contra una instancia real, para que nadie lo descubra en vivo durante la demo:

- **`DiagnosisWriter.find_previous_diagnosis` sigue siendo el punto de mayor incertidumbre del proyecto, aunque ya tiene un plan B.** Busca entidades con la misma firma de patrón con un filtro estructurado (`get_urns_by_filter` con `extraFilters` sobre `structuredProperties.<qualifiedName>` — Plan A). El *método* del SDK está confirmado por introspección directa contra `acryl-datahub==1.7.0`, pero **el nombre exacto del campo indexado en Elasticsearch para structured properties custom depende de cómo DataHub construye el mapping de búsqueda**, y eso solo se confirma corriéndolo contra una instancia real. Si Plan A lanza una excepción, o "funciona" pero no devuelve nada, `_search_by_pattern_signature` cae automáticamente a una búsqueda de texto libre (`query=`, Plan B) que no depende de ese nombre de campo — y cualquier resultado de Plan B se re-valida contra la firma exacta antes de reutilizarlo, para no dar por buena una coincidencia parcial de texto libre. Ninguno de los dos planes puede tirar abajo `diagnose`: si ambos fallan, `find_previous_diagnosis` devuelve `None` (equivalente a "no se encontró memoria previa"), nunca una excepción. **Igual se valida en runtime con `scripts/spike_writeback_test.py` antes de la demo** — Plan B reduce el riesgo de que la demo se vea rota, pero no reemplaza confirmar que Plan A funciona de verdad.
- **Reintentos de conexión**: `DataHubClient` ahora reintenta la conexión inicial hasta 3 veces con backoff exponencial (`tenacity`) antes de darse por vencido — ver `src/graph/client.py`. Esto cubre que DataHub tarde en levantar o tenga un hiccup momentáneo al arrancar el agente; no reintenta requests individuales una vez conectado (eso ya lo maneja `DataHubGraphConfig` internamente vía sus propios parámetros de retry HTTP).
- **CI**: `.github/workflows/ci.yml` corre los 24 tests unitarios y valida que la imagen Docker construye en cada push. Los tests son 100% mocks sobre `DataHubClient` — no hay integration tests contra una instancia real de DataHub en el pipeline de CI, justamente porque ese es el paso manual que hace `scripts/spike_writeback_test.py`.

## Licencia

Apache 2.0 — ver [`LICENSE`](LICENSE).
