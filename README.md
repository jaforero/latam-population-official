# Población oficial de América Latina · repositorio de datos

Pipeline, datos crudos y procesados de la población total de 20 países, con series anuales y proyecciones oficiales. Alimenta la pieza [dashboards.javierforero.co/poblacion-latam/](https://dashboards.javierforero.co/poblacion-latam/). Este repositorio no publica sitio propio.

**La trazabilidad pesa más que la cobertura:** un país sin fuente verificable queda pendiente con su motivo. Nunca se rellena.

## Regla de fuentes
1. **Nacional:** instituto de estadística u organismo con mandato legal, incluidos sus portales de datos abiertos.
2. **Respaldo regional:** CEPAL/CELADE, solo por país y tipo de serie cuando la institución nacional no publica esa serie de forma verificable y descargable. La nacional siempre prevalece.
3. **Fuera:** agregadores como Banco Mundial, ONU/WPP, Wikipedia, Statista, datosmacro u Our World in Data.

El respaldo es el Excel de la Revisión 2024 de CEPAL/CELADE, que declara coproducción con la División de Población de la ONU. Se acepta y se cita así (decisión D1 de `sources.yaml`).

## Estructura
```
sources.yaml              registro: una entrada por país y tipo de serie
latam_pop/adapters/       un adaptador por fuente (fetch → parse → normalize)
latam_pop/derive.py       crecimiento, CAGR, rupturas, año máximo
latam_pop/validate.py     validaciones: alertas, nunca correcciones
latam_pop/build.py        orquesta y escribe las salidas
data/raw/<iso3>/<clave>/  <fecha>_<sha12>_<archivo> + .meta.json (hash, fecha, URL, quién lo obtuvo)
data/raw/_regional/       archivos compartidos por varios países (CEPAL)
data/manual/              transcripciones de fuentes escaneadas
data/processed/           salidas de contrato
tests/fixtures/           crudos reales o recortados, para probar sin red
```

## Contrato de datos · `schema_version` 1.4
Las rutas son estables y el frontend depende de ellas. **Un cambio de esquema es un cambio de versión:** campo eliminado, renombrado o con otro significado sube la versión mayor. Los campos nuevos opcionales suben la menor.

| Ruta | Contenido |
|---|---|
| `data/processed/<iso3>.json` | Registro, segmentos de fuente, rupturas y año máximo de un país. Existe para los 20, aun sin datos. |
| `data/processed/pyramids/<iso3>.json` | Pirámide por año: hombres y mujeres en 17 grupos comunes, con su fuente. Existe para los 20, aun sin datos. |
| `data/processed/latam.csv` | Todos los registros, en formato largo. |
| `data/processed/manifest.json` | Fuentes, niveles, vintages y fechas vigentes por país y serie. |
| `data/processed/licenses.json` | Revisión de términos por institución: estado, texto leído, cita exigida y condiciones. |
| `data/status.json` | Estado, última actualización, nivel de fuente y error por país y serie. |
| `data/alerts.json` · `data/source_changes.json` | Alertas de la corrida y bitácora de cambios de fuente o vintage. |

**Cada registro:**

| Campo | Tipo | Significado |
|---|---|---|
| `iso3` | texto | País |
| `year` | entero | Año |
| `population` | número o null | Personas, con el valor publicado (sin redondear). CEPAL publica en miles y se multiplica por 1000. |
| `series_type` | `observed` · `estimate` · `projection` | Sigue el rótulo de la fuente. Hoy no hay `observed`: las series históricas son estimaciones oficiales ancladas en censos. |
| `source_id` · `source_tier` | texto · `national` / `regional_fallback` | Fuente y nivel |
| `vintage` · `scenario` | texto · `single` / `medium` / `recommended` / null | Edición y escenario |
| `reference_date` | `MM-DD` · `mid-year` · `census` · null | Fecha de referencia de la cifra; `census` es la fecha de cada censo |
| `retrieved_at` | fecha | Primera descarga de este archivo (mismo hash) |
| `interpolated` | booleano | Siempre `false` hoy: no se interpola |
| `growth` | número o null | `(P_t / P_{t-1}) − 1`, solo dentro de la misma fuente y vintage |
| `raw_file` | ruta | Archivo de `data/raw/` del que sale la cifra |

**Cambios:** la 1.1 admite `reference_date: census` (hoy sin uso). La 1.2 agrega las pirámides y `pyramid` en `status.json`. La 1.3 agrega `parts` y `part`, porque una pirámide puede combinar dos fuentes. La 1.4 agrega `licenses.json` y el campo `license` en segmentos, `status.json`, `parts` y `latam.csv`. Todas son compatibles con la 1.0.

**Pirámides:** `age_groups` lista 0-4 … 75-79 y 80+. `years["2025"]` trae `m` y `f` (17 valores) más `series_type`, `source_id`, `vintage`, `source_tier` y `reference_date`, los mismos del registro de ese año, y `part`, el índice de `parts`. Cada elemento de `parts` da `institution`, `source_url`, `source_tier`, `location_in_file` y `raw_files` (ruta, hash, fecha). Además `status`, `reason`, `note` y `raw_files` con todos los crudos. Cada año usa la parte del mismo nivel de fuente que la serie de ese año. Solo se suman grupos publicados; no se desagrega ni se interpola. Un año se publica únicamente si hombres + mujeres cuadra con el total oficial de ese año (tolerancia de 0,05 %); si no, se excluye y genera una alerta.

**Por país**, además: `segments` (institución, URL, vintage, hash, ubicación en el archivo), `breaks` (ruptura con año de corte y sin ajuste), `peak` (`peak`, `no_peak_in_horizon` o `no_projection`) y `reasons` en español e inglés.

**Valores de `status`:** `ok`; `manual` (archivo aportado por una persona); `manual_pendiente` (falta ese archivo); `stale` (la fuente falló y se conservan sus últimos datos válidos); `error`; `pendiente`.

## Reglas que el código hace cumplir
- Las uniones entre fuentes o vintages no se encadenan ni se ajustan: se registran como ruptura y el crecimiento no se calcula a través de ellas.
- `cagr()` devuelve `None` si los dos años están en series distintas.
- Si un año tiene dato nacional y regional, queda el nacional y se genera una alerta.
- Validaciones: años duplicados, huecos, variación anual fuera de ±4 %, discrepancia con la cifra de control, cambio de vintage o de nivel. Solo alertan.
- Si una fuente falla, los demás países siguen y esa conserva su último crudo válido.
- Descarga con agente identificado, TLS activo y respeto de `robots.txt`. Login, captcha, bloqueos de red o `robots.txt` llevan a método manual. No se eluden.

## Ejecutar
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
python -m latam_pop run
```

## Automatización
`.github/workflows/update.yml` corre cada lunes y por disparo manual. Hace commit solo si cambian los datos y abre un issue con la etiqueta `pipeline` si un adaptador falla, salta una validación nueva o cambia un portal vigilado donde se usa CEPAL. Una falla de fuente no pone el workflow en rojo: queda en `status.json` y en un issue.

**Secrets:** ninguna fuente actual requiere token. Si alguna lo exige, léelo con `os.environ` desde un secret llamado `<ISO3>_API_TOKEN`, documenta el nombre aquí y nunca lo escribas en el código.

## Cargar una fuente manual
Para fuentes que no admiten descarga automática:
1. Abre la URL de `sources.yaml` en tu navegador y descarga el archivo.
2. Registra el archivo con el país y la serie a los que corresponde, y ejecuta el pipeline:
```bash
python -m latam_pop ingest BOL projection ~/Downloads/PC20107.xlsx
```
```bash
python -m latam_pop run
```
3. Revisa que no haya alerta `control_mismatch` y haz commit de `data/`.

Un archivo cubre las dos series cuando comparten `raw_key`, y basta ingerirlo una vez. Si el archivo no es el que indica la entrada, primero corrige la entrada (URL, años, `vintage_label`, `raw_key` y control): `ingest` guarda la URL registrada como procedencia. Si el país estaba `pendiente`, complétalo como en la sección siguiente, con `status: manual`.

**Archivos que mejorarían lo cargado:**
- **Rep. Dominicana:** la edición 1950-2100 con censo 2022 que la ONE anunció en junio de 2026.
- **México:** una copia de `00_Pob_Mitad_1950_2070.csv` con filas nacionales agregaría 1950-1969 a la pirámide.
- **Cuba:** cualquier serie de ONEI verificable reemplazaría a CEPAL.

La página del INE de Bolivia ofrece cuadros 2000-2050 casi idénticos de las revisiones 2014, 2020 y 2025: el pie del cuadro dice cuál es.

Si el archivo manual es de una pirámide, usa `ingest ISO3 pyramid ARCHIVO`.

## Cómo agregar un país o una fuente
1. Agrega o completa la entrada en `sources.yaml`: `source_tier`, URL exacta, `adapter`, `source_id`, `raw_key`, `year_from`, `year_to`, vintage, referencia temporal y una **cifra de control** leída en la fuente. Un país nuevo también va en `latam_pop/__init__.py` y en `NAMES` de `build.py`.
2. Escribe el adaptador en `latam_pop/adapters/sources.py` con `@register("nombre")`. Basta implementar `parse`, que devuelve `{año: población}` tal como se publica.
3. Agrega un fixture en `tests/fixtures/` y el caso en `tests/test_parsers.py`.
4. Para sustituir CEPAL por una serie nacional, cambia la entrada a `source_tier: national`. El pipeline registra el cambio en `source_changes.json` y abre un issue. Ajusta `test_cepal_only_where_declared`.
5. Para su pirámide, escribe un parser en `latam_pop/pyramids.py` con `@parser("nombre")`, registra el bloque `pyramid` del país en `sources.yaml` y agrega el caso en `tests/test_pyramids.py`.
6. Ejecuta `python -m pytest -q` y `python -m latam_pop run`.

## Cuando una fuente cambia de formato
Los síntomas son un issue de falla, `status: error` o una alerta `control_mismatch`. Los datos publicados no cambian mientras tanto, salvo que el parser siga leyendo cifras que ya no coinciden: por eso la alerta de control se revisa siempre.
1. **Mira el crudo nuevo** en `data/raw/<iso3>/<clave>/`. El anterior sigue ahí con su fecha y hash.
2. **Si llegó una página de bloqueo**, el archivo se rechaza antes de guardarse. Revisa si la URL cambió y actualízala en `sources.yaml`; si ahora exige captcha o login, pasa la entrada a `status: manual`.
3. **Si cambió el diseño**, ajusta `parse` y agrega un fixture del formato nuevo sin borrar el anterior si aún sirve.
4. **Si cambió la vintage**, actualiza `vintage`, `vintage_label`, `source_id` y la cifra de control, leída otra vez en la fuente. Nunca copies el valor que produce el parser: el control existe para contrastarlo.
5. **Decide sobre las alertas:** una variación de ±4 % puede ser real. No se corrige; se documenta en el issue.

## Límites conocidos
- **Licencias:** CEPAL/CELADE restringe la redistribución, según un texto leído solo por extracto de buscador, y seis instituciones no tienen licencia localizada. Ver [Términos de uso de las fuentes](#términos-de-uso-de-las-fuentes).
- **Vintages:** Perú, Honduras y El Salvador tienen una edición nueva esperada o citada; Venezuela usa una proyección de 2013. Rep. Dominicana usa una serie anterior a la edición con censo 2022 que la ONE anunció en junio de 2026.
- **Cuba:** usa CEPAL porque ONEI no es verificable (certificado vencido). La vigilancia avisa si el portal vuelve a responder.
- **Peso:** `data/raw/` ocupa unos 205 MB y conserva cada versión de los archivos.
- **Red:** algunos sitios pueden bloquear los ejecutores de GitHub Actions aunque respondan desde otra conexión; en ese caso la serie pasa a `stale`.

## Términos de uso de las fuentes
Revisados el 2026-11-01. Es una lectura de textos publicados, no un dictamen jurídico. El registro está en `sources.yaml` (`licenses`) y se publica en `data/processed/licenses.json` con la cita exigida y el enlace a cada texto.

| Resultado | Instituciones | Qué implica |
|---|---|---|
| Licencia abierta leída | INDEC, INE Chile, INEC Costa Rica, ONE (Rep. Dominicana), INEC Ecuador, CONAPO, INEC Panamá, INE Paraguay | Permiten redistribuir con atribución. Argentina, Chile y Costa Rica (CC BY-SA 4.0) y Rep. Dominicana (ODbL) piden compartir lo derivado bajo la misma licencia. |
| Condiciones propias leídas | INE Bolivia, DANE, INEI, INE Uruguay | Bolivia y Perú permiten reproducir citando; Bolivia limita el uso comercial. DANE autoriza transformar y analizar con cita textual, sin mencionar la redistribución de archivos. INE Uruguay considera pública la información, sin regular su reutilización. |
| Sin licencia localizada | IBGE, INE Guatemala, INE Honduras, INIDE, ONEC/BCR, INE Venezuela | No hay permiso expreso para republicar los archivos. No equivale a una prohibición. |
| Restringe | CEPAL/CELADE | El acuerdo de uso que enlaza CEPALSTAT limita la descarga a uso personal y no comercial, sin redistribuir ni crear otros trabajos. Afecta a Cuba, Haití, la historia de Honduras y la proyección de Nicaragua, con sus pirámides. Se leyó solo por extracto de buscador porque cepal.org bloquea la lectura automática; falta confirmarlo y pedir permiso. |

**Copias crudas:** de los 42 archivos de `data/raw/`, 17 no tienen permiso expreso de redistribución: 8 de CEPAL/CELADE y 9 de instituciones sin licencia localizada. Siguen aquí por trazabilidad mientras se resuelve.

**Cambios respecto a los originales:** se extrae la población total, los miles de CEPAL pasan a personas, las edades se suman en 17 grupos comunes y aquí se calculan el crecimiento y el año máximo. Ninguna cifra se corrige.

## Licencia
El código puede reutilizarse con atribución. Este repositorio no otorga una licencia nueva sobre los datos: cada cifra conserva las condiciones de su fuente, registradas en el campo `license`. Lo derivado de fuentes CC BY-SA 4.0 u ODbL se comparte bajo esa misma licencia.

Javier Forero · [javierforero.co](https://javierforero.co)
