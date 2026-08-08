# Mecanismo "lag-aware" de Majestic — plan de implementación

> **Aviso de origen, primero que nada, sin letra chica:** esta idea NO está
> basada en un paper académico verificado. Surgió de una cita alucinada
> ("LagRCA", supuesto Distinguished Paper Award de FSE 2026) que se
> verificó contra la fuente primaria (el programa oficial de la
> conferencia) y no existe ahí. La *idea técnica* subyacente, sin embargo,
> es buena y resuelve un problema real de `RootCauseDiagnoser` — así que
> se implementa como diseño original de Majestic, con el apodo interno
> "LagRCA" únicamente como broma/homenaje a su origen, **nunca como cita
> de investigación real**. No debe aparecer en `proyecto-majestic.md` ni
> en el video como "basado en el paper LagRCA" — eso sería falso. Sí puede
> mencionarse como "un mecanismo propio, inspirado en cómo la
> investigación real de RCA en microservicios (MicroRCA, TraceDiag,
> DynaCausal — esos sí verificados, ver `docs/PROPOSAL.md`) trata el
> tiempo y la herencia de síntomas".

## Qué problema real resuelve (en términos de Majestic, no del paper fantasma)

1. **Los pesos de evidencia son estáticos.** `_EVIDENCE_WEIGHTS` no distingue
   "esto pasó hace 10 minutos" de "esto pasó hace 3 semanas". Una anomalía
   reciente es más probable causa activa que una vieja.
2. **No hay distinción entre evidencia independiente y heredada.** Si un
   nodo downstream muestra síntomas porque su upstream ya estaba roto,
   tratarlo como señal independiente infla la cadena causal.
3. **Una sola respuesta esconde la ambigüedad** cuando hay 2+ candidatos
   con evidencia comparable — `root_cause_urn` es siempre un solo URN, aunque
   el segundo candidato esté casi empatado.

## Los 3 mecanismos a construir

### Mecanismo 1 — Decaimiento por antigüedad (recency decay)
Para los tipos de evidencia que YA calculan `age_hours` (`schema_change`,
`stale_data`), aplicar un factor de decaimiento exponencial al peso:

```
adjusted_weight = base_weight * decay(age_hours)
decay(age_hours) = 0.5 ** (age_hours / LAG_DECAY_HALFLIFE_HOURS)
```

Nunca cae a cero — evidencia vieja pesa menos, no se descarta. Para
`incident_tag` y `unowned` (sin timestamp confiable vía los aspectos
estándar que ya leemos), el peso queda fijo como hoy — no se fabrica un
timestamp que no existe.

### Mecanismo 2 — Descuento por herencia upstream
Si el mismo `evidence_type` aparece en dos hops consecutivos de la cadena,
el hop más cercano al target (downstream) se descuenta con
`UPSTREAM_INHERITANCE_DISCOUNT` — es más probable que esté heredando el
problema del hop más lejano que aportando una señal independiente.

### Mecanismo 3 — Top-K candidatos rankeados
`analyze()` agrega un campo nuevo `ranked_candidates` (hasta
`RANKED_CANDIDATES_TOP_K` candidatos, cada uno con `urn`/`hop`/
`evidence_type`/`adjusted_weight`), ordenado descendente. Los campos
existentes (`root_cause_urn`, `reason`, `confidence`, `causal_chain`)
se siguen calculando igual que hoy pero usando los pesos ajustados —
**cambio aditivo**, nada que ya consume el report se rompe.

## Checklist de implementación

- [x] `config/settings.py` — agregar `LAG_DECAY_HALFLIFE_HOURS` (default
      48), `UPSTREAM_INHERITANCE_DISCOUNT` (default 0.5),
      `RANKED_CANDIDATES_TOP_K` (default 3). Todos configurables por env var,
      mismo patrón que el resto del archivo.
- [x] `src/core/diagnoser.py`:
  - [x] `_recency_decay(age_hours) -> float`
  - [x] Aplicar el decaimiento donde se calcula `age_hours` (schema_change,
        stale_data) al construir el diccionario de evidencia.
  - [x] `_apply_upstream_inheritance_discount(causal_chain) -> causal_chain`
  - [x] `analyze()`: usar la cadena ya ajustada para elegir `root_cause_urn`
        (sigue siendo `max(..., key=hop,weight)`, pero sobre pesos ajustados)
        y agregar `ranked_candidates` al dict de retorno.
- [x] `tests/test_diagnoser.py` — casos nuevos:
  - [x] decaimiento reduce el peso de evidencia vieja sin llegar a 0
  - [x] evidencia reciente (age_hours≈0) casi no se descuenta
  - [x] descuento de herencia baja el score del hop downstream cuando el
        tipo coincide con el del hop upstream
  - [x] `incident_tag`/`unowned` no se ven afectados por el decaimiento
        (sin timestamp fabricado)
  - [x] `ranked_candidates` ordenado correctamente, tope en `RANKED_CANDIDATES_TOP_K`
- [x] Correr los 61 tests existentes — revisar si alguno asumía un peso
      fijo exacto que ahora cambia por el decaimiento (es esperable que
      algún test necesite ajustar un valor, no la lógica).
- [x] Probar en vivo contra el DataHub real que sigue corriendo: re-diagnosticar
      `sales_report`, confirmar que `marketing_etl` sigue apareciendo como
      causa raíz con el mecanismo nuevo.
- [x] `main.py cmd_diagnose` — imprimir `ranked_candidates` cuando haya
      más de un candidato (opcional, solo si `len(ranked_candidates) > 1`).
- [x] Documentar en `README.md` (sección "Notas técnicas") como mecanismo
      propio de Majestic, con el aviso de origen de arriba.

## Criterio de éxito

`diagnose` sobre el grafo sembrado hoy sigue encontrando `marketing_etl`
como causa raíz de `sales_report` (no debería cambiar el resultado en un
caso tan simple de 1 solo hop de evidencia) — la diferencia se nota en
grafos con evidencia en múltiples hops o de distinta antigüedad, que hoy
no tenemos sembrados. Puede valer la pena sembrar un tercer escenario de
demo con evidencia vieja + nueva para que el mecanismo se vea en el video.
