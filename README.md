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
├── main.py                      # entrypoint CLI (diagnose / impact)
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

### 4. Aplicar la definición de memoria episódica

```bash
datahub properties upsert -f config/agent_memory_property.yaml
```

### 5. Validar el setup (en orden)

```bash
python3 spike_test.py                     # ¿DataHub responde?
python3 scripts/spike_writeback_test.py   # ¿el ciclo completo de memoria funciona?
```

### 6. Correr el agente

```bash
# Diagnosticar la causa raíz de un URN
python3 main.py diagnose "urn:li:dataset:(urn:li:dataPlatform:hive,SampleHiveDataset,PROD)"

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
- [ ] Búsqueda de diagnósticos previos por firma de patrón (`find_previous_diagnosis`) — el nombre exacto del campo de búsqueda para structured properties en Elasticsearch no está confirmado contra una instancia real; validar antes de la demo.

Ver la sección "Estado de validación técnica" en [`proyecto-majestic.md`](proyecto-majestic.md) para el detalle completo y el razonamiento detrás de cada decisión.

## Notas técnicas (riesgos conocidos)

Transparencia sobre lo que todavía no está probado contra una instancia real, para que nadie lo descubra en vivo durante la demo:

- **`DiagnosisWriter.find_previous_diagnosis` es el punto de mayor riesgo del proyecto.** Busca entidades con la misma firma de patrón usando un filtro de búsqueda (`get_urns_by_filter` con `extraFilters` sobre `structuredProperties.<qualifiedName>`). El *método* del SDK está confirmado por introspección directa contra `acryl-datahub==1.7.0`, pero **el nombre exacto del campo indexado en Elasticsearch para structured properties custom depende de cómo DataHub construye el mapping de búsqueda**, y eso solo se confirma corriéndolo contra una instancia real — no hay forma de validarlo por lectura de código o por tests unitarios con mocks. Si el campo real difiere (por ejemplo, si necesita el URN completo `urn:li:structuredProperty:...` en vez del `qualifiedName` corto, o un sufijo `.keyword`), la función devuelve `None` silenciosamente en vez de fallar con un error. **Se valida en runtime con `scripts/spike_writeback_test.py` antes de la demo**, y si el nombre de campo no es el asumido, es el primer fix a aplicar.
- **Reintentos de conexión**: `DataHubClient` ahora reintenta la conexión inicial hasta 3 veces con backoff exponencial (`tenacity`) antes de darse por vencido — ver `src/graph/client.py`. Esto cubre que DataHub tarde en levantar o tenga un hiccup momentáneo al arrancar el agente; no reintenta requests individuales una vez conectado (eso ya lo maneja `DataHubGraphConfig` internamente vía sus propios parámetros de retry HTTP).
- **CI**: `.github/workflows/ci.yml` corre los 24 tests unitarios y valida que la imagen Docker construye en cada push. Los tests son 100% mocks sobre `DataHubClient` — no hay integration tests contra una instancia real de DataHub en el pipeline de CI, justamente porque ese es el paso manual que hace `scripts/spike_writeback_test.py`.

## Licencia

Apache 2.0 — ver [`LICENSE`](LICENSE).
