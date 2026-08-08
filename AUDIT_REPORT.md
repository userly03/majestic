# AUDIT_REPORT.md — Auditoría de jurado, sin filtro

> Escrito el 2026-08-08, leyendo el código fuente real (`src/`, `main.py`,
> `config/`, `tests/`), no solo la documentación — y con el contexto de
> haber corrido el pipeline completo contra una instancia real de DataHub
> hoy mismo (ver `docs/PROPOSAL.md`, Ronda 4). Cuando algo merece un 5, es
> un 5.

---

## Sección 1 — Puntuación por criterio

### 1. Uso de DataHub — **6/10**

**Lo que suma:**
- No es lectura pasiva. `src/memory/writer.py` escribe de vuelta al grafo (`structuredProperties` vía `DatasetPatchBuilder.add_structured_property` + `emit_mcps`) — el propio criterio dice explícitamente "las propuestas sólidas... contribuyen al gráfico cuando corresponde", y esto lo cumple de forma literal, no cosmética.
- Usa múltiples superficies reales del modelo de datos de DataHub, no una sola: lineage (`scroll_lineage`, `src/graph/traversal.py`), tags (`GlobalTagsClass`), ownership (`OwnershipClass`), schema (`SchemaMetadataClass`), y el framework de Structured Properties de punta a punta (definición en YAML + registro vía SDK + lectura/escritura). Eso es un uso genuinamente transversal del grafo de metadata, no un `get()` aislado.
- El framework de Structured Properties es, literalmente, el mecanismo que DataHub recomienda para extender su propio modelo de datos — usarlo para persistir memoria episódica es una elección correcta, no un atajo.

**Lo que resta puntos, y es serio:** el pitch del hackathon abre con una frase específica — *"With an MCP Server, end-to-end ML lineage, and DataHub Skills that give agents direct access to catalog workflows..."* — y el criterio 1 nombra explícitamente **MCP Server, Agent Context Kit, DataHub Skills, Analytics Agent**. Majestic no usa ninguno de los cuatro. `proyecto-majestic.md` lo admite sin rodeos: *"vía el SDK Python de DataHub (`DataHubGraph`, no un MCP Server — se evaluó y se optó por el SDK directo)"*. Es una decisión de ingeniería defendible (el SDK directo es más simple de depurar, y hoy funciona), pero es exactamente lo contrario de lo que este criterio premia. Tampoco hay lineage de ML (todo el proyecto es datasets/dashboards; cero `MLModel`, `MLFeature`, `MLModelGroup`) pese a que el hackathon lo menciona como diferenciador de DataHub. Un jurado que lea el criterio literal y compare contra el código va a notar el hueco en 30 segundos.

**Por qué 6 y no más/menos:** el uso *conceptual* del grafo (lineage + write-back + structured properties) es real y no trivial — no es un 3. Pero ignorar por completo las cuatro superficies que el criterio nombra explícitamente, en un hackathon que las pone en el primer párrafo de la convocatoria, no puede ser un 8+.

### 2. Calidad de ejecución técnica — **8/10**

**Lo que suma:**
- Separación de responsabilidades limpia y sin superposición: `src/graph` (cliente + traversal), `src/core` (orquestación + diagnóstico), `src/memory` (persistencia), `src/impact` (simulación) — cada módulo tiene una sola razón para cambiar.
- Fail-fast consistente: las 4 clases que dependen de DataHub (`LineageTraversal`, `RootCauseDiagnoser`, `ImpactSimulator`, `DiagnosisWriter`) chequean `client.is_connected` en su propio `__init__` y lanzan `RuntimeError` de inmediato — nadie queda construido a medias.
- Los números de timeout/retry en `config/settings.py` no son adivinados — están medidos (`HTTP_RETRY_MAX_TIMES` bajado de 4 a 2 después de medir 28s→90s contra un GMS caído, documentado en el propio código, línea 29-39).
- Paralelización real donde importa: `RootCauseDiagnoser._collect_evidence_parallel` y `ImpactSimulator._collect_owners` usan `ThreadPoolExecutor` para no pagar latencia lineal en nodos con fan-in ancho — y con un solo nodo, caen al camino secuencial sin overhead.
- **Validado en vivo hoy, no solo en CI con mocks**: corrí `doctor` (3/3), `seed_demo_data.py`, `diagnose --explain --write`, `impact`, y el reuso de memoria en una segunda entidad — contra una instancia real. Encontró y corrigió 2 bugs reales en el camino (ver Sección 2). Eso es evidencia de que "el código cumple lo que promete", no solo una afirmación.
- 46/46 tests unitarios pasan; CI corre tests + build de Docker en cada push.

**Lo que resta puntos:**
- La "cadena causal" no es realmente *path-aware*. `RootCauseDiagnoser.analyze()` agrupa los nodos upstream por profundidad (`nodes_by_hop`) y busca evidencia en *cualquier* nodo a esa profundidad — no en un camino específico desde el target. Si hay dos ramas de lineage distintas, la evidencia de la rama A a hop 2 puede aparecer en la cadena aunque el nodo relevante para el target real esté en la rama B. Esto no está roto — es una simplificación razonable para un hackathon — pero tampoco está documentado en ningún lado como limitación. Un jurado que lea el código con cuidado (no solo el README) lo va a notar.
- La función que arreglé hoy mismo (`_sanitize_urn_lookalikes` en `src/memory/writer.py`) tiene **cero tests**. Encontramos el bug, lo arreglamos, lo verificamos manualmente contra la API real — pero no quedó un test que lo proteja de una regresión futura. Es la clase de gap que un jurado técnico que lee el diff sí nota.
- `requirements.txt` mezcla dependencias de producción (`acryl-datahub`, `requests`) con `pytest` — la imagen Docker de producción carga el framework de test sin necesitarlo. Cosmético, pero es el tipo de detalle que un ingeniero senior "obsesionado con calidad" (la propia autodescripción del proyecto en su historial de commits) señalaría en el propio proyecto.

### 3. Originalidad — **7/10**

**Lo que suma:**
- La idea central — cruzar evidencia de *distinto dominio* (tags, schema, freshness, ownership) en una sola cadena causal, y generalizar ese diagnóstico a otras entidades por firma estructural — no es "otro monitor con umbral configurable". La tabla comparativa de `proyecto-majestic.md` es honesta sobre esto: DataHub ya hace detección de anomalías y automatización basada en reglas; lo que Majestic hace (razonamiento causal transversal + memoria generalizable) es un hueco real, no relleno de marketing.
- El mecanismo de "memoria" (firma de patrón `tipo:hop:upstream:downstream` → reutilizar diagnóstico) es un giro genuinamente creativo, no una copia obvia de un patrón de agentes genérico ni de una feature existente de DataHub.
- Composición correcta, no reinvención: el simulador de impacto (`ImpactSimulator`) es literalmente el mismo `LineageTraversal` invertido — no es un módulo nuevo duplicando lógica, es la prueba de que el diseño del traversal fue pensado para reutilizarse. Eso es exactamente el tipo de "extensión/composición" que las reglas piden, no reconstrucción desde cero.

**Lo que resta puntos:**
- La firma de patrón (`incident_tag:1:2:1`) es estructuralmente muy gruesa — ver el hallazgo crítico en la Sección 2 sobre falsos positivos de "memoria". Una idea original que generaliza mal en la práctica pierde parte de su mérito.
- Los 4 tipos de evidencia son heurísticas directas sobre aspectos básicos de DataHub (tag, owner, timestamp) — no hay nada aquí que un ingeniero de datos competente no hubiera podido escribir en un día. La originalidad está en la *composición y la memoria*, no en la sofisticación de la detección individual — y eso es correcto para un hackathon, pero limita el techo del puntaje.

### 4. Utilidad en el mundo real — **7/10**

**Lo que suma:**
- El problema ("el informe de ventas está vacío, ¿por qué?", saltar entre 3 herramientas para averiguarlo) es real y universalmente reconocible para cualquiera que haya operado un pipeline de datos en producción.
- Alcance disciplinado: `proyecto-majestic.md` lista explícitamente lo que NO construyeron y por qué (bot de Slack, traductor a glosario de negocio, predicción de fallos) — cada decisión de scope tiene una razón técnica, no "no tuvimos tiempo". Eso hace que lo que SÍ existe sea más creíble como algo que funciona, no una lista de features a medio hacer.
- `main.py doctor` y los mensajes de error humanizados (`_human_error` en `main.py`) muestran que se pensó en el operador real, no solo en el happy path de una demo.

**Lo que resta puntos, y es el hallazgo más importante de esta auditoría:**
- **La "memoria" puede generar falsos positivos estructurales, y esto no es hipotético — es matemáticamente inevitable a escala.** `pattern_signature = f"{evidence_type}:{hop}:{upstream_count}:{downstream_count}"` (`src/core/agent.py::_build_pattern_signature`) no captura nada semántico sobre el dominio, la plataforma, ni el contenido real del incidente. Dos datasets completamente no relacionados — uno de marketing, otro de finanzas — con un tag de incidente a 1 hop de distancia y casualmente el mismo conteo de upstream/downstream, producen la MISMA firma. Majestic diría "♻️ ya vi este patrón antes" y reutilizaría un diagnóstico que no tiene nada que ver. En una empresa real con miles de datasets, esto no es un caso raro — es estadísticamente garantizado que pase seguido. Ningún jurado técnico que piense en esto por 30 segundos va a dejarlo pasar, y es el corazón del diferencial del proyecto (la fila más fuerte de la tabla comparativa en `proyecto-majestic.md`).
- Las heurísticas de evidencia son señales *proxy*, no observabilidad real: "sin owner" no significa que algo se rompió, "schema modificado hace poco" no prueba causalidad (coincidencia temporal ≠ causa). El proyecto es honesto sobre esto en los comentarios de `diagnoser.py`, lo cual suma a la sección 5, pero resta acá — es una limitación real de utilidad, no solo de honestidad.

### 5. Calidad de la presentación — **7/10 (potencial 9/10, condicionado)**

**Lo que suma:**
- `README.md` tiene instalación paso a paso reproducible, arquitectura clara, y — a partir de hoy — un historial de validación en vivo con hallazgos reales, no afirmaciones genéricas.
- `proyecto-majestic.md` es un pitch honesto y bien escrito: problema, comparación explícita con DataHub (sin inflar diferenciación donde no la hay), qué no se construyó y por qué.
- La transparencia sobre riesgos conocidos ("Notas técnicas" en README, las 4 rondas de `docs/PROPOSAL.md`) es, paradójicamente, una fortaleza de presentación: un jurado confía más en un equipo que conoce el límite exacto de su propio sistema.
- `examples/` tiene outputs reales, no inventados, con fecha y comandos exactos documentados en `examples/README.md`.

**Por qué no es más alto todavía:** el criterio pide explícitamente "calidad del video de demostración" y **no existe ningún video grabado**, y "repo público" y **el repositorio no está en GitHub todavía** (verificado: `git remote -v` no devuelve nada). Por más pulida que esté la documentación, sin esas dos piezas el jurado no puede evaluar este criterio — hoy, literalmente, no hay nada que juzgar en esas dos dimensiones. El potencial es alto porque el material de base (guion cronometrado en `docs/DEMO_SCRIPT.md`, ya validado contra la instancia real) es sólido.

### 6. Bonificación — Contribución open source a DataHub — **1/10**

Cero contribuciones al repositorio de DataHub en sí (sin PR, sin issue, sin fix de documentación, sin RFC). Esto es 100% esperable para el estado actual del proyecto — nadie prometió esto — pero tal como está, no suma nada a esta bonificación. Ver Sección 3, idea #1: hay una oportunidad de bajísimo esfuerzo y alta credibilidad esperando acá, generada por el propio trabajo de hoy.

---

## Sección 2 — Problemas críticos detectados

Ordenados por qué tan probable es que un jurado los encuentre y qué tan mal se ve si lo hace.

1. **🔴 La firma de patrón puede generar falsos positivos de "memoria" — es el riesgo más grave porque ataca el diferencial central del proyecto.** Ya detallado en la Sección 1.4. Si un jurado prueba el proyecto con dos entidades no relacionadas que casualmente comparten `evidence_type:hop:upstream:downstream`, va a ver a Majestic "reconocer" un patrón inexistente — y eso es peor que no tener memoria, porque es un diagnóstico incorrecto presentado con confianza.

2. **🔴 Cero uso de MCP Server / Agent Context Kit / DataHub Skills / Analytics Agent, en un hackathon que los nombra en el primer párrafo de la convocatoria.** Ya detallado en Sección 1.1. Esto no se puede ocultar — está documentado por el propio proyecto (`proyecto-majestic.md`) como una decisión consciente, lo cual es honesto, pero un jurado que puntúa específicamente por esto va a ver el hueco sin importar qué tan bien esté redactado el resto.

3. **🟡 Repositorio todavía no está en GitHub, no hay video grabado.** Bloqueadores de submission, no de calidad de código — pero sin esto no hay nada que evaluar en los criterios 1, 5 y 6 (todos requieren un repo público/URL).

4. **🟡 `_sanitize_urn_lookalikes` (el fix de hoy) no tiene test.** Bajo riesgo de romperse solo, pero es exactamente el tipo de "código nuevo sin cobertura" que una revisión de código seria señala.

5. **🟡 La cadena causal no es realmente path-aware** (agrupa por profundidad, no por camino específico desde el target) — no documentado como limitación en ningún lado. No es un bug, pero es una brecha entre lo que el README implica ("cadena causal") y lo que el código realmente garantiza.

6. **🟢 El bug de UI de DataHub que encontramos hoy (`FabricType.$UNKNOWN`) es, en sí mismo, una prueba de que el proyecto no se probó contra una instancia real hasta hoy.** Ya está corregido y documentado (`docs/PROPOSAL.md`, Ronda 4) — lo marco acá no como problema pendiente, sino como evidencia de que vale la pena revisar si hay *otros* bugs de UI similares que todavía no se activaron simplemente porque no se probaron todas las combinaciones de texto libre que el agente puede llegar a escribir (por ejemplo, `--business-context` con texto arbitrario de un humano).

7. **🟢 `requirements.txt` sin separar prod/dev**, imagen Docker carga `pytest` innecesariamente. Cosmético, bajo impacto real, pero barato de arreglar.

---

## Sección 3 — Ideas brillantes (más allá de lo obvio)

### Idea 1 — Reportar el bug de DataHub que encontramos hoy, como issue público
**Qué es:** abrir un issue en `datahub-project/datahub` (GitHub) documentando el crash `IllegalArgumentException: No enum constant ...FabricType.$UNKNOWN` cuando un structured property de tipo string contiene una subcadena con forma de URN — con el repro exacto (ya lo tenemos, palabra por palabra, en `docs/PROPOSAL.md` Ronda 4 y en el historial de esta sesión: la query GraphQL exacta, el valor que lo dispara, el stack trace).
**Por qué impresiona al jurado:** el criterio de bonificación pide explícitamente "correcciones" y contribuciones que extiendan trabajo hecho durante el hackathon. Esto no es una idea hipotética — es un bug real, reproducible, que encontramos *hoy*, con toda la evidencia ya escrita. Reportarlo (con o sin PR de fix) es la contribución open-source más creíble posible porque nace del propio proyecto, no de buscar algo para cumplir un requisito.
**Esfuerzo:** trivial (30-45 min: traducir el hallazgo ya documentado a un issue en inglés, con el repro GraphQL). Si además se anima alguien a mandar un PR con el fix (probablemente en el resolver de `valueEntities` del lado de `datahub-graphql-core`), sube a moderado — pero el issue solo ya cuenta.
**Riesgo de romper algo:** ninguno — es una acción completamente externa al repo de Majestic.

### Idea 2 — Exponer `diagnose`/`impact` como herramientas MCP
**Qué es:** un servidor MCP mínimo (usando el SDK oficial `mcp` de Python) que envuelve `MajesticAgent.diagnose()` e `ImpactSimulator.simulate()` como dos tools (`majestic_diagnose(urn)`, `majestic_impact(urn)`). No hace falta tocar la lógica existente — `agent.py` y `simulator.py` ya están desacoplados de la CLI (`main.py` es una capa fina encima), así que el servidor MCP sería un tercer "frontend" sobre el mismo core, igual que `main.py` es uno hoy.
**Por qué impresiona al jurado:** es la respuesta más directa posible al hueco #2 de la Sección 2. Reposiciona a Majestic de "un script que lee DataHub" a "una capacidad que otros agentes pueden invocar" — literalmente lo que dice la convocatoria del hackathon ("agents that actually ship... composing DataHub"). Un jurado que pregunte "¿dónde está el MCP?" pasa de encontrar un hueco a ver una respuesta concreta.
**Esfuerzo:** moderado (medio día: instalar `mcp`, definir 2 tools con sus schemas, probarlo con un cliente MCP simple o el inspector oficial). El riesgo técnico es bajo porque no toca código existente, solo agrega un adaptador nuevo.
**Riesgo de romper algo:** ninguno si se implementa como módulo nuevo (`src/mcp_server.py` o similar) sin modificar `agent.py`/`simulator.py`.

### Idea 3 — Cerrar el hueco de falsos positivos de memoria con una firma más honesta
**Qué es:** en vez de (o además de) `evidence_type:hop:upstream:downstream`, incluir algo que ancle la firma a un contexto real — por ejemplo, el `platform` (hive, snowflake, etc.) de la causa raíz, o exigir que la entidad candidata comparta al menos un tag/dominio con la entidad actual antes de aceptar el reuso. Alternativa más simple: al mostrar "♻️ ya existe un diagnóstico", mostrar explícitamente qué tan "gruesa" es la coincidencia (ej. "misma estructura, plataforma distinta — revisar antes de confiar ciegamente") en vez de presentarlo como una coincidencia confiable sin matices.
**Por qué impresiona al jurado:** convierte el problema más grave detectado en esta auditoría (Sección 2, ítem 1) en una fortaleza demostrada — mostrar que el equipo pensó en el caso de falso positivo y lo maneja explícitamente es exactamente el tipo de rigor que distingue un proyecto de hackathon "que funciona en la demo" de uno que un equipo de datos real consideraría.
**Esfuerzo:** moderado si se hace bien (ajustar `_build_pattern_signature` + `find_previous_diagnosis` + tests); trivial si solo se agrega el matiz visual en el mensaje.
**Riesgo de romper algo:** bajo-medio — toca el corazón de la Fase 3, hay que correr los tests de integración de nuevo después.

### Idea 4 — Resolver nombres reales en el impacto, no solo URNs
**Qué es:** `ImpactSimulator._collect_owners` ya trae las `OwnershipClass` de cada nodo downstream — hoy solo se guardan los URNs crudos (`urn:li:corpuser:...`). Con una llamada extra a `CorpUserInfoClass` (o `CorpUserEditableInfoClass`) se puede mostrar el nombre para mostrar ("Sarah, del equipo de Finanzas, sería notificada") en vez de una URN ilegible.
**Por qué impresiona al jurado:** es el tipo de detalle "visceral" que pide la consigna — convierte `affected_owners: ["urn:li:corpuser:majestic_seed"]` en algo que un jurado no técnico también entiende de un vistazo, sin cambiar nada de la lógica de negocio.
**Esfuerzo:** trivial (una llamada `get_aspect` más, ya se tiene el patrón exacto en el propio archivo).
**Riesgo de romper algo:** ninguno — es aditivo, con fallback al URN si no hay `CorpUserInfo`.

### Idea 5 — Un comando `main.py memory` que liste todos los diagnósticos persistidos
**Qué es:** un nuevo subcomando que corra `get_urns_by_filter` sobre `structuredProperties.majestic.patternSignature` sin filtrar por valor específico, y liste todas las entidades con memoria activa, agrupadas por firma — una especie de "bitácora" de todo lo que Majestic ya diagnosticó en la instancia.
**Por qué impresiona al jurado:** hace tangible el diferencial de memoria de una forma que ningún `diagnose` individual puede mostrar — un jurado ve de un vistazo que esto no es "un diagnóstico aislado" sino un sistema que acumula conocimiento con el tiempo. Barato de demostrar en video (un comando, una tabla).
**Esfuerzo:** trivial-moderado (reutiliza `_search_by_pattern_signature` con un filtro más amplio; la parte nueva es formatear la salida).
**Riesgo de romper algo:** ninguno, es de solo lectura.

---

## Sección 4 — Plan de acción priorizado

### 🔴 CRÍTICO (sin esto, la submission está incompleta o vulnerable)
1. **Crear el repo en GitHub y pushear** (ya lo tenés vos, según lo último que hablamos) — sin esto, los criterios 1, 5 y 6 no se pueden evaluar.
2. **Grabar el video de 3 min** siguiendo `docs/DEMO_SCRIPT.md` — mismo motivo.
3. **Reportar el bug de DataHub como issue en GitHub (Idea 1, Sección 3).** Trivial, ya está todo documentado, y es la única acción concreta disponible para la Sección 6 (bonus) antes de la fecha límite.
4. **Agregar al menos un test para `_sanitize_urn_lookalikes`** (Sección 2, ítem 4) — 10 minutos, cierra un gap real y visible en el diff de hoy.

### 🟠 ALTO IMPACTO (te diferencia de la competencia, vale la pena si hay medio día más)
5. **Atacar el problema de falsos positivos de memoria (Idea 3)** — es el hallazgo más serio de esta auditoría y ataca directamente el corazón del pitch. Aunque sea la versión simple (mostrar el matiz en el mensaje, no la firma más rica), vale la pena antes que cualquier otra cosa de esta lista.
6. **Servidor MCP mínimo (Idea 2)** — es la respuesta más directa al hueco más grande del criterio 1. Si el tiempo alcanza para una sola cosa "ambiciosa", es esta.
7. **Resolver nombres reales en `impact` (Idea 4)** — esfuerzo trivial, sube visiblemente la calidad de la demo sin riesgo.
8. **Documentar explícitamente la limitación de "cadena causal no es path-aware"** (Sección 2, ítem 5) en el README — 15 minutos, cierra una brecha honestidad-vs-código antes de que un jurado la encuentre solo.

### 🟢 BONUS (si sobra tiempo)
9. **Comando `main.py memory` (Idea 5)** — buen efecto visual para el video, pero no crítico.
10. **Separar `requirements.txt` / `requirements-dev.txt`** — cosmético, bajo ROI, pero rápido.
11. Si de verdad sobra tiempo: convertir el issue reportado en un PR real con el fix, para subir la Sección 6 de "reportar" a "contribuir código".
