# Ejemplos

El checklist de submission de Devpost pide `examples/` con **outputs reales**:
un diagnóstico generado de verdad y una captura de la structured property
en la UI de DataHub.

## Qué son estos archivos

`diagnosis_output.json`, `impact_output.json`, `explain_output.txt` y
`memory_reuse_output.json` son outputs reales de `main.py` corridos contra
una instancia real de DataHub (`datahub docker quickstart`), sobre el grafo
sembrado por `scripts/seed_demo_data.py` (A→B→C, anomalía en B) y una
segunda entidad con la misma firma de patrón (H→G→F, sembrada reutilizando
`_seed_second_matching_entity` de `scripts/generate_example_outputs.py`
contra el cliente real en vez del `FakeDataHub`).

Comandos exactos usados:

```bash
datahub docker quickstart
python3 main.py doctor
python3 scripts/seed_demo_data.py
python3 main.py diagnose "urn:li:dataset:(urn:li:dataPlatform:hive,majestic_demo.sales_report,PROD)" --write --explain
python3 main.py impact "urn:li:dataset:(urn:li:dataPlatform:hive,majestic_demo.sales_report,PROD)"
# + segunda entidad (H→G→F) para el reuso de memoria, luego:
python3 main.py diagnose "urn:li:dataset:(urn:li:dataPlatform:hive,majestic_demo.finance_report,PROD)"
```

Validar esto contra una instancia real (en vez de solo el `FakeDataHub` de
`generate_example_outputs.py`) encontró un bug real: `_seed_second_matching_entity`
intentaba emitir el aspecto `globalTags` sobre una entidad `tag` (inválido —
DataHub lo rechazó con 422; el `FakeDataHub` no valida compatibilidad
aspecto/entidad, así que nunca lo hubiera atrapado). Ya está corregido en
`scripts/generate_example_outputs.py` (usa `TagPropertiesClass`, como hace
correctamente `seed_demo_data.py`).

## Qué falta agregar acá

1. **`structured_property_screenshot.png`** — captura de la UI de DataHub
   mostrando las structured properties `majestic.*` ya escritas sobre la
   entidad (Settings → Structured Properties, o la pestaña de properties
   del dataset). Esto ningún script lo puede generar — es la única pieza
   que requiere una captura manual.

## Cómo regenerar

Contra una instancia real ya levantada, repetir los comandos de arriba y
reemplazar los `.json`/`.txt` de esta carpeta con esos outputs.

Si no hay una instancia real disponible, `scripts/generate_example_outputs.py`
regenera una versión equivalente corriendo el mismo código de producción
contra un grafo falso en memoria (`FakeDataHub`) — útil para mantener los
archivos sincronizados con el código mientras tanto, pero no sustituye
correr esto contra DataHub de verdad antes de grabar el video.
