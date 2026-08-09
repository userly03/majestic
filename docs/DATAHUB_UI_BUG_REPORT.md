# Bug real de DataHub, encontrado validando Majestic en vivo

> Borrador de issue para `datahub-project/datahub`, listo para copiar/pegar
> o adaptar. **No se publicó todavía** — publicarlo es una acción visible
> en un repositorio público de terceros, así que queda a criterio de quien
> lo suba (necesita su propia cuenta de GitHub / `gh auth login`, no
> disponible en este entorno). Ver `AUDIT_REPORT.md`, Sección 3, Idea 1.

## Título sugerido

`Entity page/search crashes with "IllegalArgumentException: No enum constant ...FabricType.$UNKNOWN" when a structured property STRING value contains a URN-shaped substring`

## Versión

`v1.7.0` (`acryldata/datahub-gms:v1.7.0`, `acryldata/datahub-frontend-react:v1.7.0`, vía `datahub docker quickstart`).

## Resumen

El resolver de GraphQL que arma `valueEntities` para structured properties
intenta interpretar como referencia a otra entidad *cualquier* valor de
tipo `STRING` que contenga una subcadena con forma de URN de DataHub
(`urn:li:...(...)`) — no solo valores que sean *enteramente* un URN. Al
intentar parsear una subcadena que no es un URN válido y completo, el
parser lanza `IllegalArgumentException: No enum constant
com.linkedin.common.FabricType.$UNKNOWN` en vez de tratar el valor como
texto libre. Esa excepción no se maneja con gracia: rompe por completo la
ficha de la entidad, y cualquier búsqueda/listado que la incluya, con un
genérico "Something went wrong" en la UI.

## Cómo reproducirlo

1. Definir una structured property de tipo `STRING` sobre cualquier
   entidad (dataset, dashboard, etc.) — cualquier definición vale, no hace
   falta nada especial en el YAML.
2. Asignarle un valor de texto libre que **contenga**, como subcadena, algo
   con forma de URN de DataHub — por ejemplo, una oración que embeba el URN
   de otra entidad:

   ```
   "urn:li:dataset:(urn:li:dataPlatform:hive,marketing_etl,PROD) (hop 1): sin actualizar hace 30.0h"
   ```

   (Este es literalmente el tipo de valor que un texto explicativo generado
   por una herramienta — no solo un URN "pelado" — produce con naturalidad:
   la oración es válida como texto, pero contiene un URN completo adentro.)
3. Emitir esa structured property sobre la entidad (vía SDK Python,
   `DatasetPatchBuilder.add_structured_property` + `emit_mcps`, o
   equivalente).
4. Abrir la ficha de esa entidad en la UI, o listarla en una búsqueda que
   incluya esa property.

**Resultado esperado:** la property se muestra como texto libre.

**Resultado real:** la página tira "Something went wrong"; el log del GMS
muestra `IllegalArgumentException: No enum constant
com.linkedin.common.FabricType.$UNKNOWN` en el resolver que arma
`valueEntities` a partir del valor.

## Impacto

Cualquier producto/integración que escriba texto libre generado
dinámicamente (explicaciones, resúmenes, logs) como structured property de
tipo `STRING`, y ese texto mencione un URN de otra entidad como parte de la
oración (un patrón común: "la causa está en `<urn>`"), puede romper la UI
de DataHub sin darse cuenta — el bug está en el lado de DataHub, no en
quien escribe la property, pero el disparador es fácil de producir sin
querer.

## Workaround aplicado (del lado del emisor, no arregla la causa)

Insertar un espacio de ancho cero (`​`) dentro de la subcadena
`urn:li:` antes de persistir el valor — invisible al leerlo, pero rompe la
detección de URN del lado de la UI/resolver. Ver
`src/memory/writer.py::_sanitize_urn_lookalikes` en este repo
(`majestic`) para la implementación exacta. Confirmado antes/después
contra la API real de GMS: con el espacio de ancho cero, la misma entidad
carga sin error.

## Fix sugerido (del lado de DataHub, no implementado acá)

En el resolver de `valueEntities` (lado de `datahub-graphql-core`), al
intentar parsear una subcadena con forma de URN, capturar la excepción de
parseo (o validar que la subcadena sea un URN completo y válido antes de
intentar resolverla como entidad) y, si falla, tratar el valor como texto
plano en vez de propagar la excepción hacia la respuesta GraphQL.
