# Ejemplos

El checklist de submission de Devpost pide `examples/` con **outputs reales**:
un diagnóstico generado de verdad y una captura de la structured property
en la UI de DataHub. Estos archivos **todavía no son eso** — son un paso
intermedio honesto, no una simulación de "output real".

## Qué son estos archivos (y qué NO son)

`diagnosis_output.json`, `impact_output.json`, `explain_output.txt` y
`memory_reuse_output.json` fueron generados por
[`scripts/generate_example_outputs.py`](../scripts/generate_example_outputs.py),
que corre el **código real de producción** —`MajesticAgent`,
`ImpactSimulator`, `DiagnosisWriter`, `narrator.explain`, los mismos
`src/*` que usa `main.py`, sin reimplementar ni simplificar nada— contra
un grafo falso en memoria (`FakeDataHub` en ese mismo script) que imita la
forma de las respuestas de `DataHubGraph`.

Esto es **mejor que un JSON escrito a mano** (que se desincroniza del
código real en cuanto algo cambia) pero **no reemplaza correr esto contra
una instancia de DataHub real**. El propio proyecto se toma en serio no
presentar como medido algo que no lo es (ver "Predicción de fallos
futuros" en `proyecto-majestic.md`) — por eso esta distinción está escrita
así de explícita, no escondida en un comentario.

## Qué falta agregar acá antes de la submission

1. **Regenerar estos 4 archivos contra DataHub real:**
   ```bash
   datahub docker quickstart
   python3 main.py doctor
   python3 scripts/seed_demo_data.py
   python3 main.py diagnose "urn:li:dataset:(urn:li:dataPlatform:hive,majestic_demo.sales_report,PROD)" --write --explain
   python3 main.py impact "urn:li:dataset:(urn:li:dataPlatform:hive,majestic_demo.sales_report,PROD)"
   ```
   y reemplazar los `.json`/`.txt` de esta carpeta con esos outputs.

2. **`structured_property_screenshot.png`** — captura de la UI de DataHub
   mostrando las structured properties `majestic.*` ya escritas sobre la
   entidad (Settings → Structured Properties, o la pestaña de properties
   del dataset). Esto el script no lo puede generar bajo ninguna
   circunstancia — es la única pieza que requiere sí o sí una instancia
   real y una captura manual.

3. **`memory_reuse_output.json` real** — correr `diagnose` sobre una
   *segunda* entidad con la misma firma de patrón (`seed_demo_data.py` no
   crea esta segunda entidad; `generate_example_outputs.py` sí, solo para
   este propósito — replicar ese mismo patrón contra datos reales, o
   sembrar manualmente una segunda entidad con la misma estructura).

## Cómo regenerar la versión "código real + grafo falso" mientras tanto

```bash
python3 scripts/generate_example_outputs.py
```

Reescribe los 4 archivos de esta carpeta. Útil para mantenerlos
sincronizados con el código mientras no hay una instancia real disponible
— pero no es un sustituto del paso 1 de arriba antes de grabar el video.
