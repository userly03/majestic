# CLEANUP_REPORT.md — Auditoría de repositorio antes de la entrega final

> Modo seguro: este documento es un análisis. **No se borró ni movió nada.**
> Espera aprobación explícita, ítem por ítem si hace falta, antes de ejecutar
> cualquier cambio.

## Resumen ejecutivo

Escaneé los 48 archivos del repo (sin contar `.claude/settings.local.json`,
que ya está gitignoreado y no cuenta, ni este mismo reporte). El diagnóstico honesto: **el repo está más
limpio de lo que el pedido original suponía**. No encontré:

- Ningún `spike_*.py` que ya no corra — los dos que existen (`spike_test.py`,
  `scripts/spike_writeback_test.py`) siguen siendo herramientas activas y
  documentadas, no basura.
- Ningún `test_*.py` roto o huérfano — los 9 archivos de test tienen
  correspondencia 1:1 clara con un módulo de `src/`, y los 50 tests
  (46 unitarios + 4 de integración) pasan.
- Ninguna carpeta vacía.
- Ningún archivo con nombre genérico tipo `utils.py`, `helper.py`, `temp.py`,
  `misc.py`, `old_*`, `*_copy`, `*_backup` — busqué explícitamente por esos
  patrones y no aparece nada.
- Ninguna config duplicada.

Lo que sí encontré es **1 archivo de basura real** (caché de Python, ya
gitignoreada), **1 línea de código muerto**, **1 archivo mal ubicado** con
un blast radius concreto de 6 referencias, y **4 decisiones de criterio**
donde prefiero preguntar antes de mover algo con costo de romper enlaces.

---

## 1. Revisión de estructura de carpetas

| Carpeta | Veredicto | Comentario |
|---|---|---|
| `src/graph/`, `src/core/`, `src/memory/`, `src/impact/` | ✅ Sana | Una responsabilidad por carpeta, nombres descriptivos, sin cruces. No tocaría nada acá. |
| `scripts/` | ⚠️ Casi sana | Contiene herramientas de spike/debug/generación (`seed_demo_data.py`, `generate_example_outputs.py`, `spike_writeback_test.py`) — todas con un propósito distinto y documentado. El problema no es lo que *está* en `scripts/`, es lo que *falta*: ver hallazgo 3.1 (`spike_test.py` vive en la raíz en vez de acá). |
| `tests/` | ✅ Sana | Estructura plana (sin subcarpetas) es correcta para 9 archivos — no hace falta anidar. Nombres calcan 1:1 el módulo que testean (`test_client.py` ↔ `src/graph/client.py`, etc.), excepto `test_integration.py`, que correctamente no mapea a un solo módulo porque testea el flujo completo. |
| `config/` | ✅ Sana | `settings.py` + el YAML de la property + `__init__.py` vacío para hacerlo paquete. Nada fuera de lugar. |
| `examples/` | ✅ Sana, con una nota | Ver hallazgo 3.3 — quiero tu confirmación explícita de que commitear outputs generados es intencional (creo que sí lo es, pero es la clase de cosa que vale la pena que digas "sí, a propósito" en vez de que yo lo asuma). |
| Raíz del repo | ⚠️ Revisar | 13 archivos sueltos. La mayoría son estándar de cualquier repo (`README.md`, `LICENSE`, `Dockerfile`, `requirements.txt`, `.env.example`, `pytest.ini`, `.dockerignore`, `docker-compose.yml`, `main.py`). Los 3 que llaman la atención son `proyecto-majestic.md`, `PROPOSAL.md`, `DEMO_SCRIPT.md` — ver hallazgo 3.2. |

**No encontré ningún caso de "script utilitario en la raíz que debería estar
en `src/`"** (el ejemplo que diste en el pedido) — todo lo que hay en `src/`
es código de producción real, y todo lo que hay en la raíz o en `scripts/`
es entrypoint o herramienta de desarrollo, correctamente separado.

---

## 2. A Eliminar

| Archivo | Por qué |
|---|---|
| `src/__pycache__/` y `src/graph/__pycache__/` (con `.pyc` adentro) | Caché de bytecode de Python de corridas locales anteriores. Ya está en `.gitignore` (nunca se commiteó, cero riesgo para el historial), pero sigue ocupando lugar en el disco de trabajo. Se regenera solo la próxima vez que se importe el módulo — borrarlo no tiene downside. |
| `config/settings.py`, línea `MEMORY_PROPERTY_URN = "urn:li:structuredProperty:majestic.diagnosis"` | **Código muerto confirmado por grep**: es la única línea del repo donde aparece ese nombre — nadie lo importa. `src/memory/writer.py` define sus propias constantes privadas (`_PROP_PATTERN_SIGNATURE`, `_PROP_DIAGNOSIS`, etc.) y las usa a esas, no a esta. Quedó de una iteración temprana antes de que `writer.py` tuviera su propio esquema de constantes. Es una línea, no un archivo — pero es basura real, no falso positivo. |

Eso es todo lo que calificaría como "a eliminar" sin ninguna duda. No
propongo borrar ningún script ni test — todos los que existen se usan y
están documentados.

---

## 3. A Mover / Renombrar

### 3.1 `spike_test.py` (raíz) → `scripts/spike_test.py`

**Por qué:** todos los demás scripts de spike/debug/utilidad viven en
`scripts/` (`spike_writeback_test.py`, `seed_demo_data.py`,
`generate_example_outputs.py`). Tener a este como el único suelto en la
raíz es inconsistente — y no es una decisión de diseño documentada en
ningún lado, es un resabio de que este archivo ya existía antes de que
`scripts/` se creara en la Ronda 1.

**Blast radius real (6 referencias en 5 archivos), si se aprueba:**

| Archivo | Línea | Qué dice hoy |
|---|---|---|
| `Dockerfile` | 10 | `CMD ["python", "spike_test.py"]` |
| `docker-compose.yml` | 12 | comentario: `docker compose up  # corre spike_test.py (valida conexión)` |
| `main.py` | 149 | docstring de `cmd_doctor`: `(spike_test.py + datahub properties upsert + spike_writeback_test.py)` |
| `README.md` | 39 | árbol de arquitectura: `├── spike_test.py  # valida solo la conexión` |
| `README.md` | 81 | `python3 spike_test.py` en el texto de instalación |
| `README.md` | 120 | comentario en el bloque de Docker |
| `PROPOSAL.md` | 36 | mención en la lista de riesgos de Ronda 1 |

Ninguna de estas es difícil de actualizar, pero son 5 archivos distintos —
lo marco como una tarea de "mover + actualizar 6 referencias", no un simple
`mv`. Si lo apruebas, lo hago todo junto en el mismo cambio para no dejar
al repo en un estado intermedio inconsistente.

**Alternativa que también considero válida:** dejarlo en la raíz a
propósito, como el único comando de "¿está vivo el proyecto?" de un solo
paso, sin depender de `scripts/`. Es una convención razonable en otros
proyectos (un `smoke_test.py` o `healthcheck.py` en la raíz). No tengo una
preferencia fuerte — lo marco como pendiente de tu decisión, no como un
error a corregir sí o sí.

---

## 4. A Revisar (decisiones, no correcciones obvias)

### 4.1 ¿`proyecto-majestic.md`, `PROPOSAL.md` y `DEMO_SCRIPT.md` deberían vivir en `docs/`?

Son 3 de los 13 archivos de la raíz. `README.md` y `LICENSE` tienen que
quedarse en la raíz sí o sí (convención de GitHub, y requisito del
hackathon que la licencia sea visible). Los otros tres son documentos de
proceso/pitch, candidatos típicos a una carpeta `docs/` en un repo prolijo.

**A favor de mover:** raíz más limpia, más fácil de escanear para alguien
que abre el repo por primera vez.

**En contra:** `proyecto-majestic.md` es el pitch del hackathon — algunos
jurados/organizadores esperan encontrarlo sin tener que buscar en
subcarpetas. Y mover estos 3 archivos requiere actualizar referencias
cruzadas reales:

- `proyecto-majestic.md` está linkeado desde `README.md`, `PROPOSAL.md` y `examples/README.md`.
- `PROPOSAL.md` está linkeado desde `DEMO_SCRIPT.md` y `proyecto-majestic.md` (y se referencia a sí mismo).
- `DEMO_SCRIPT.md` no tiene ninguna referencia entrante todavía (nadie lo linkea desde `README.md` — dato aparte, no es parte de este cleanup, pero lo noto).

**Mi recomendación si me preguntás:** dejarlos en la raíz tal cual están.
El costo de mover (actualizar N enlaces, riesgo de romper uno) es real y el
beneficio (una raíz ligeramente más corta) es cosmético. Pero es tu
llamada — decime si preferís que los mueva y te devuelvo la lista exacta de
enlaces que actualizaría.

### 4.2 `requirements.txt` mezcla dependencias de producción y de test

`pytest` está en el mismo `requirements.txt` que `acryl-datahub`,
`requests`, `pydantic`, `python-dotenv`, `tenacity` — y el `Dockerfile`
instala ese archivo entero en la imagen de producción. Resultado: la
imagen que corre el agente en producción también carga `pytest`, que
nunca se usa ahí.

**Opción A (mínima):** separar en `requirements.txt` (producción) +
`requirements-dev.txt` (agrega `pytest`), y que el `Dockerfile` solo
instale el primero.
**Opción B:** dejarlo como está — para un proyecto de hackathon de este
tamaño, el costo real (unos MB extra en la imagen) es bajo, y un solo
archivo es más simple de mantener/explicar en el video.

No tengo una opinión fuerte acá tampoco; lo marco porque es la clase de
cosa que un ingeniero senior "obsesionado con la calidad" señalaría, pero
el ROI de arreglarlo antes de la entrega es bajo.

### 4.3 `examples/*.json` y `explain_output.txt` son artefactos generados, commiteados a git

`scripts/generate_example_outputs.py` los reescribe cada vez que se corre.
Commitear outputs generados suele ser un olor a código en otros contextos
(archivos derivados en control de versiones) — **pero acá creo que es
intencional y correcto**: el checklist de submission de Devpost pide
`examples/` con contenido visible sin que el jurado tenga que correr nada.
Lo marco como "a revisar" solo para que confirmes explícitamente que sí,
es a propósito, y no algo que se coló sin querer.

### 4.4 Nombres en `scripts/generate_example_outputs.py`: sufijo numérico

`URN_H`, `URN_G`, `URN_F`, `DASHBOARD2_URN`, `TAG2_URN` — son la segunda
copia del escenario A→B→C, para el ejemplo de reuso de memoria. El sufijo
numérico (`DASHBOARD2_URN`) es un poco menos descriptivo que el resto del
proyecto (que usa nombres como `URN_A`/`URN_B`/`URN_C` con letras, ya
medio numérico también, pero al menos consistente con el propio
`seed_demo_data.py`). Es un archivo interno de generación, no parte del
flujo de demo — prioridad baja. Si se aprueba, renombraría a algo como
`SECOND_SCENARIO_DASHBOARD_URN` / `SECOND_SCENARIO_TAG_URN` para que se
lea sin tener que mirar el código de al lado.

### 4.5 Verifiqué (no lo estoy reportando como problema): posible redundancia entre `main.py doctor`, `scripts/spike_writeback_test.py` y `tests/test_integration.py`

Los tres tocan el mismo mecanismo (conexión + ciclo write/read de
`structuredProperties`). Antes de escribir este reporte confirmé que NO es
duplicación accidental — cada uno tiene una audiencia distinta y ya está
documentado así en el README:

- `main.py doctor`: chequeo rápido, resumen ✅/❌, para correr antes de la demo.
- `scripts/spike_writeback_test.py`: debug profundo, imprime el JSON exacto y el traceback completo — para cuando `doctor` falla y hay que ver por qué.
- `tests/test_integration.py`: aserciones automatizadas, para CI/validación repetible, no para uso manual.

No propongo tocar ninguno de los tres.

### 4.6 `pytest.ini` vs. `pyproject.toml`

Convención más moderna sería centralizar config de herramientas en
`pyproject.toml`. Puramente estilístico, cero impacto funcional, no lo
haría antes de la entrega — lo menciono solo porque preguntaste
específicamente por estandarización.

---

## 5. Convenciones de nombres — veredicto

Revisé nombres de archivo, clases, funciones y constantes globales en todo
`src/`, `scripts/`, `config/`, `main.py`:

- **Archivos:** 100% `snake_case`, sin excepciones.
- **Clases:** `PascalCase` consistente y descriptivo — `MajesticAgent`,
  `RootCauseDiagnoser`, `DataHubClient`, `LineageTraversal`,
  `DiagnosisWriter`, `ImpactSimulator`. Ninguna clase con nombre genérico
  tipo `Manager`/`Helper`/`Handler`.
- **Constantes de módulo:** `UPPER_SNAKE_CASE` consistente en
  `config/settings.py`, `main.py`, `scripts/*.py`. Todas describen qué
  guardan, ninguna es `X`/`TMP`/`VALUE`.

No encontré ningún nombre confuso o genérico que corregir, más allá del
matiz menor del punto 4.4.

---

## Próximos pasos

Esperando tu aprobación. Cuando me digas qué de esto ejecutar, lo hago en
este orden (de menor a mayor blast radius):

1. Eliminar `__pycache__` y la línea muerta `MEMORY_PROPERTY_URN` — bajo
   riesgo, puedo hacerlo apenas confirmes.
2. Mover `spike_test.py` a `scripts/` (si lo aprobás) — actualizo las 6
   referencias en el mismo cambio.
3. Cualquiera de las decisiones de la sección 4 que quieras que ejecute.

No voy a tocar nada de esto hasta que me confirmes qué aprobás.
