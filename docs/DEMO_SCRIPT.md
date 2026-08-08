# DEMO_SCRIPT.md — Guion de grabación (≤ 3:00)

> Nota de idioma: escrito en español, igual que el resto del proyecto. Si el
> video final necesita ser en inglés para el jurado, avisar y se traduce
> manteniendo la misma estructura de tiempos.

Este documento asume que **ya corriste todo esto antes de grabar** — la
grabación en sí no debe incluir instalación, debugging, ni esperas. Todo lo
de "Preparación" es *off camera*. Lo único que se graba es la sección
"El guion".

---

## 0. Comandos, en orden (para tener a mano durante el ensayo)

```bash
# --- Preparación (off camera, con margen antes de grabar) ---
datahub docker quickstart
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python3 main.py doctor
python3 scripts/seed_demo_data.py

export URN_C="urn:li:dataset:(urn:li:dataPlatform:hive,majestic_demo.sales_report,PROD)"
export URN_B="urn:li:dataset:(urn:li:dataPlatform:hive,majestic_demo.marketing_etl,PROD)"

# --- Toma de calentamiento, NO se graba (ver sección 1) ---
python3 main.py --quiet diagnose "$URN_C"

# --- Grabación: los 3 comandos que aparecen en cámara ---
python3 main.py --quiet diagnose "$URN_C" --explain --write
python3 main.py --quiet impact "$URN_B"
```

Nada más se tipea en cámara. Todo lo demás (instalar, sembrar, `doctor`) ya
corrió antes y quedó validado.

---

## 1. Preparación (off camera)

Correr esto con tiempo de sobra antes de la sesión de grabación — si algo
falla acá, hay margen para arreglarlo sin presión de cámara.

```bash
# 1. DataHub arriba y con tiempo de indexar (dejarlo unos minutos, no lo
#    uses apenas termina el quickstart)
datahub docker quickstart

# 2. Entorno
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# 3. Un solo comando valida TODO — si algo de esto da ❌, resolverlo antes
#    de seguir. No se muestra en el video (o si se muestra, ver sección 3
#    sobre cómo hablar de un ❌ si aparece a propósito).
python3 main.py doctor

# 4. Sembrar el grafo de demo (A → B → C + dashboard, anomalía garantizada en B)
python3 scripts/seed_demo_data.py
```

### Cómo obtener los URN sin copiar/pegar en cámara

Los URN de `scripts/seed_demo_data.py` son **strings fijos, no aleatorios**
(ver `URN_A`/`URN_B`/`URN_C` en ese archivo) — no hace falta parsear la
salida del script cada vez. Definilos como variables de entorno una sola
vez, antes de grabar:

```bash
export URN_C="urn:li:dataset:(urn:li:dataPlatform:hive,majestic_demo.sales_report,PROD)"
export URN_B="urn:li:dataset:(urn:li:dataPlatform:hive,majestic_demo.marketing_etl,PROD)"
echo "$URN_C"   # confirmar que imprime completo antes de seguir
```

A partir de acá, todos los comandos en cámara usan `"$URN_C"` / `"$URN_B"`
— cero riesgo de tipear mal un URN largo en vivo. (Si en algún momento
cambiás los nombres de dataset en `seed_demo_data.py`, la fuente de verdad
para los URN nuevos es lo que ese mismo script imprime al final, bajo
"Probar con:".)

### La corrida de calentamiento (tampoco se graba)

DataHub indexa lineage/búsqueda de forma asíncrona. Corré `diagnose` una
vez, sin grabar, inmediatamente después de sembrar:

```bash
python3 main.py --quiet diagnose "$URN_C"
```

Si `root_cause_urn` sale `null` la primera vez, esperá 10-15s y corré de
nuevo — es indexación, no un bug (`seed_demo_data.py` ya avisa esto en su
propio output). Una vez que esta corrida de calentamiento devuelve la causa
raíz en B, recién ahí empezar a grabar.

**No uses Docker para la toma en vivo.** `docker compose run` funciona (se
verificó en la Ronda 3), pero cada corrida tiene overhead de arranque de
contenedor — para grabar, correr todo directo con el venv activado, más
rápido y con menos partes móviles en cámara. Docker queda como la opción
para quien quiera reproducir el proyecto después de ver el video.

---

## 2. El guion, paso a paso

### 0:00–0:30 — El problema (30s)

**Opción A (recomendada si la UI de DataHub está lista):** pantalla en el
grafo de lineage de `sales_report` en la UI de DataHub, mostrando la
cadena `raw_marketing → marketing_etl → sales_report`.

**Opción B (fallback, sin UI):** slide o directamente hablando a cámara
sobre el escenario, sin mostrar pantalla todavía.

**Narración (~75 palabras, ritmo natural ≈ 30s):**

> "Imaginate esto: el reporte de ventas de hoy está vacío. La alerta te dice
> qué pasó, pero no por qué. Acá tenemos tres datasets encadenados:
> `raw_marketing` alimenta a `marketing_etl`, y ese alimenta al reporte de
> ventas. En algún punto de esa cadena hay un problema — pero hoy,
> encontrarlo significa saltar a mano entre Airflow, Snowflake y Slack.
> Majestic hace ese salto por vos."

---

### 0:30–1:30 — Ejecutar el diagnóstico (60s)

**En cámara, tipear:**

```bash
python3 main.py --quiet diagnose "$URN_C" --explain --write
```

`--quiet` dejá la pantalla limpia (sin logs internos) — la narración lleva
el "bajo el capó", no el texto en pantalla. `--explain` agrega la síntesis
en lenguaje natural. `--write` persiste en el mismo paso (así el output
sirve también para la sección 1:30–2:15, sin correr un segundo comando).

**Narración mientras corre / mientras aparece el output (~140 palabras ≈ 60s):**

> "Mientras corre esto: Majestic se conecta a DataHub y recorre el linaje
> hacia atrás desde el reporte de ventas — un salto, dos saltos — buscando
> evidencia real en el grafo. No tags inventados, no especulación de un
> modelo de lenguaje: tags de incidente, ownership, freshness, cambios de
> schema. Ahí está: encontró que `marketing_etl` tiene un tag de incidente
> y no tiene owner asignado — esa es la causa raíz, a un salto de distancia.
> Miren la cadena causal en el JSON: hop 1, tipo de evidencia
> `incident_tag`, con el dato exacto que lo respalda, no una corazonada.
> Y esto de acá abajo, la explicación en texto, es una síntesis
> determinística sobre esa misma evidencia — el LLM, si algún día se agrega
> uno acá, redacta, pero nunca decide qué es evidencia."

**Qué debe verse en pantalla para cuando termine la narración:** el bloque
`🩺 Diagnóstico:` con `root_cause_urn` apuntando a B, `causal_chain` con un
eslabón `incident_tag`, y el bloque `📝 Explicación:` debajo.

---

### 1:30–2:15 — Mostrar la persistencia (45s)

**Opción A (recomendada — la más convincente):** cambiar a la pestaña de
DataHub UI (ya abierta y logueada de antes, no navegar en vivo), ir a la
entidad `sales_report` → Properties / Structured Properties, y mostrar
`majestic.patternSignature`, `majestic.diagnosis`, `majestic.confidenceScore`
y `majestic.diagnosedAt` ya escritos ahí.

**Narración (~60 palabras ≈ 25s, dejando 20s para que la UI cargue/se navegue):**

> "Y esto no quedó solo en la terminal. Majestic lo escribió de vuelta al
> grafo como structured properties, sobre la misma entidad — acá está:
> firma de patrón, diagnóstico, score de confianza, timestamp. La próxima
> vez que Majestic vea esta misma firma estructural en otro dataset, no
> vuelve a investigar desde cero: recupera este diagnóstico."

**Opción B (fallback, sin UI o si la UI no coopera en vivo):** quedarse en
la terminal, señalar la línea `💾 Write-back: OK` que ya está en pantalla
desde el paso anterior.

> "Y la línea `Write-back: OK` significa que esto no es un print — quedó
> persistido como structured properties sobre la entidad en DataHub,
> consultable por cualquiera que abra el grafo, no solo por quien corrió
> este comando."

No inventar una demo de "reutilización de memoria" en vivo si no la
ensayaste — `seed_demo_data.py` no siembra una segunda entidad con firma
coincidente (eso lo hace `scripts/generate_example_outputs.py`, aparte, no
como parte de este flujo). Es mejor **decir** que la memoria se reutiliza
(como en la narración de arriba) que intentar mostrarlo en vivo sin
haberlo ensayado.

---

### 2:15–2:45 — Mostrar el impacto (30s)

**En cámara, tipear:**

```bash
python3 main.py --quiet impact "$URN_B"
```

Nota: es `impact` sobre **B**, no sobre C — B es donde está la anomalía, y
correr `impact` ahí muestra el radio de explosión completo (C *y* el
dashboard downstream de C), no solo un salto. Es la corrida más
convincente con los datos que ya tenemos sembrados.

**Narración (~65 palabras ≈ 30s):**

> "Ahora el otro lado de la moneda: antes de tocar `marketing_etl`, ¿qué se
> rompe? Mismo mecanismo de traversal que el diagnóstico, la misma línea de
> código, recorriendo el grafo al revés. Ahí está: dos datasets afectados
> downstream, uno de ellos el dashboard ejecutivo de ventas — riesgo alto.
> Esto es lo que hoy nadie te dice *antes* de hacer el cambio, solo
> *después* de que ya rompiste algo."

---

### 2:45–3:00 — Cierre (15s)

**Narración (~35 palabras ≈ 15s):**

> "Majestic no es 'alertar más rápido' — es explicar el *por qué*, con
> evidencia trazable, y no olvidarlo la próxima vez. Todo el código está
> verificado contra el SDK real de DataHub, con tests, y documentado sin
> vueltas en el repo. Gracias."

(Opcional, si sobra un segundo: mostrar la URL del repo en pantalla.)

---

## 3. Plan de contingencia

Reglas generales primero:

- **Si algo fallа en vivo, no lo escondas — nárralo.** El proyecto entero
  se construyó sobre la idea de ser honestos sobre lo que no está
  garantizado (ver `PROPOSAL.md`, `README.md` sección "Notas técnicas").
  Un jurado técnico confía más en alguien que explica un fallo en tiempo
  real que en alguien que corta la grabación y reintenta sin decir nada.
- **Si vas a narrar un manejo de errores a propósito, sacá el `--quiet`
  para esa toma.** Con `--quiet` los WARNING de retry no se ven — sin él,
  se ve el reintento con backoff en pantalla, que es la prueba visual de lo
  que estás diciendo.
- **Preferí cortar y reeditar antes que forzar una toma en vivo que no
  está saliendo.** Devpost no exige una sola toma continua — grabar cada
  bloque de la sección 2 por separado y editarlos juntos es más seguro que
  un plano secuencia de 3 minutos.

Casos concretos:

| Qué pasa | Qué decir |
|---|---|
| `main.py doctor` da ❌ en "Conexión a DataHub" (esto no debería pasar en cámara si se corrió antes, pero por si acaso) | "Como ven, el agente no se cuelga esperando: reintenta con backoff exponencial un par de veces y, si DataHub sigue sin responder, lo dice en un mensaje claro — no un traceback de Python. Vamos a levantar DataHub y seguimos." (cortar, arreglar, retomar) |
| `diagnose` devuelve `root_cause_urn: null` / cadena vacía | "Esto pasa cuando la indexación del grafo en DataHub todavía no propagó — es asíncrono. Le damos unos segundos." (esperar 10-15s, correr de nuevo — no seguir grabando sobre un resultado vacío) |
| Un URN se tipeó mal (no debería pasar si se usan las variables de entorno de la sección 1, pero por si acaso) | "Y acá el agente devuelve un mensaje humano — 'dataset no encontrado, revisá el URN' — en vez de un error críptico. Por suerte tenemos el URN guardado en una variable, así que esto no debería repetirse." |
| La UI de DataHub no carga / está lenta | Pasar directo a la Opción B de la sección 1:30–2:15 (quedarse en terminal, señalar `Write-back: OK`) sin perder tiempo de grabación esperando que cargue. |
| `impact` devuelve `risk_level: "none"` o 0 afectados (URN equivocado, ej. corriste sobre C en vez de B) | Cortar y confirmar `echo $URN_B` antes de retomar — es casi seguro una variable mal seteada, no un bug. |
| Docker (si por algún motivo se usa en vivo) tarda en arrancar | No usar Docker en la toma en vivo — ver nota en sección 1. Si ya se está grabando y pasa, cortar; no narrar un build de 4 minutos. |

---

## 4. Checklist de grabación

**Antes de apretar rec:**

- [ ] `python3 main.py doctor` corrido y en verde, **no en cámara**.
- [ ] `scripts/seed_demo_data.py` corrido de nuevo justo antes de grabar (es
      idempotente — reescribe sobre lo mismo, y deja `diagnosedAt`/timestamps
      frescos si se llega a mostrar algo con fecha).
- [ ] Corrida de calentamiento de `diagnose` ya devolvió la causa raíz en B
      (confirma que la indexación de DataHub ya propagó).
- [ ] `export URN_C=...` y `export URN_B=...` ya seteados en la sesión de
      terminal que vas a grabar (`echo $URN_C` para confirmar).
- [ ] Si vas a mostrar la UI de DataHub: pestaña ya abierta, ya logueada, ya
      navegada cerca de la página de `sales_report` — no navegar en vivo.
- [ ] Notificaciones del sistema apagadas (Slack, mail, banners del SO).
- [ ] Otras pestañas/terminales con posible output inesperado, cerradas.

**Visual:**

- [ ] Terminal en modo oscuro, fuente monoespaciada, **tamaño 18-20pt o
      más** (se graba a 1080p pero se va a ver reducido en Devpost/YouTube).
- [ ] Ventana de terminal ni muy angosta (los URN son largos y van a
      wrappear feo) ni ocupando toda la pantalla (dejar aire).
- [ ] `clear` antes de cada comando nuevo — no dejar que el output de un
      paso se mezcle visualmente con el siguiente.
- [ ] Si se muestra la UI de DataHub: mismo tema oscuro/claro que la
      terminal, para que no haya un salto brusco de contraste entre tomas.
- [ ] Resolución de grabación 1920×1080 mínimo.

**Guion y ensayo:**

- [ ] Este archivo (`DEMO_SCRIPT.md`) abierto en un **segundo monitor**, no
      en la pantalla que se graba.
- [ ] Al menos un ensayo completo cronometrado contra los 3:00 antes de la
      toma final.
- [ ] Grabar por bloques (uno por cada rango de tiempo de la sección 2) y
      editar juntos, en vez de intentar una sola toma continua de 3 minutos.
- [ ] Nivel de audio probado antes de la toma real.
- [ ] (Opcional, en edición) subtítulos o un lower-third con los números
      clave (`confidence`, `risk_level`) para quien mire sin audio.
