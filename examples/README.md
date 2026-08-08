# Ejemplos

El checklist de submission de Devpost pide `examples/` con **outputs reales**:
un diagnóstico generado de verdad y una captura de la structured property
en la UI de DataHub. Esta carpeta todavía no los tiene — no se pueden
generar sin una instancia de DataHub corriendo, y este proyecto se toma en
serio no inventar datos que parezcan medidos (ver "Predicción de fallos
futuros" en `proyecto-majestic.md`, la misma lógica aplica acá).

## Qué falta agregar aquí antes de la submission

1. **`diagnosis_output.json`** — resultado real de:
   ```bash
   python3 main.py diagnose "<urn>" --write
   ```
   sobre un dataset con un problema real o simulado en un datapack de DataHub.

2. **`structured_property_screenshot.png`** — captura de la UI de DataHub
   mostrando las structured properties `majestic.*` ya escritas sobre esa
   entidad (Settings → Structured Properties, o la pestaña de properties
   del dataset).

3. (Opcional pero recomendable) **`memory_reuse_output.json`** — resultado
   de correr `diagnose` sobre una *segunda* entidad con la misma firma de
   patrón, mostrando el mensaje "♻️ Ya existe un diagnóstico con esta firma
   de patrón en otra entidad" — es la prueba de que la Fase 3 (memoria)
   funciona de verdad, no solo que persiste datos.

## Formato esperado (ejemplo sintético, no un diagnóstico real)

Para referencia de formato mientras no hay una instancia real conectada,
así se ve la salida de `diagnose` (generada con los mismos datos sintéticos
que usan los tests en `tests/test_agent.py`, **no** proviene de DataHub):

```json
{
  "target_urn": "urn:li:dataset:(urn:li:dataPlatform:hive,sales_report,PROD)",
  "upstream_count": 2,
  "downstream_count": 1,
  "root_cause_urn": "urn:li:dataset:(urn:li:dataPlatform:snowflake,marketing_raw,PROD)",
  "reason": "urn:li:dataset:(urn:li:dataPlatform:snowflake,marketing_raw,PROD) (hop 2): schema modificado hace 3.2h (umbral 24h)",
  "causal_chain": [
    {
      "urn": "urn:li:dataset:(urn:li:dataPlatform:hive,marketing_etl,PROD)",
      "hop": 1,
      "evidence_type": "unowned",
      "evidence": "dataset sin owner asignado",
      "weight": 0.3
    },
    {
      "urn": "urn:li:dataset:(urn:li:dataPlatform:snowflake,marketing_raw,PROD)",
      "hop": 2,
      "evidence_type": "schema_change",
      "evidence": "schema modificado hace 3.2h (umbral 24h)",
      "weight": 0.7
    }
  ],
  "confidence": 0.75,
  "pattern_signature": "schema_change:2:2:1"
}
```

Reemplazar este bloque (o borrarlo) una vez exista un output real.
