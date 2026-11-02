# Población oficial de América Latina · repositorio de datos

Pipeline, datos crudos y procesados de la población total de 20 países, con series anuales y proyecciones oficiales. Alimenta la pieza [dashboards.javierforero.co/poblacion-latam/](https://dashboards.javierforero.co/poblacion-latam/). Este repositorio no publica sitio propio.

**La trazabilidad pesa más que la cobertura:** un país sin fuente verificable queda pendiente con su motivo. Nunca se rellena.

## Regla de fuentes
1. **Nacional:** instituto de estadística u organismo con mandato legal, incluidos sus portales de datos abiertos.
2. **Respaldo internacional:** ONU, World Population Prospects 2024, solo por país y tipo de serie cuando la institución nacional no publica esa serie de forma verificable y descargable. La nacional siempre prevalece.
3. **Fuera:** agregadores como Banco Mundial, Wikipedia, Statista, datosmacro u Our World in Data.

El respaldo son los CSV de la variante media de la ONU, publicados bajo CC BY 3.0 IGO. Son estimaciones y proyecciones de la ONU, no cifras de una institución nacional, y se marcan como tales (decisión D5 de `sources.yaml`). Reemplazaron a CEPAL/CELADE, cuyos términos no permiten redistribuir ni crear otros trabajos; las cifras coinciden salvo redondeo. El FMI se descartó: no trae a Cuba, empieza en 1980 o después y no tiene edad ni sexo.

## Estructura
```
sources.yaml              registro: una entrada por país y tipo de serie
latam_pop/adapters/       un adaptador por fuente (fetch → parse → normalize)
latam_pop/derive.py       crecimiento, CAGR, rupturas, año máximo
latam_pop/validate.py     validaciones: alertas, nunca correcciones
latam_pop/region.py       agregado regional: suma sin rellenar ni encadenar
latam_pop/build.py        orquesta y escribe las salidas
data/raw/<iso3>/<clave>/  <fecha>_<sha12>_<archivo> + .meta.json (hash, fecha, URL, quién lo obtuvo)
data/raw/_global/         archivos compartidos por varios países (ONU)
data/manual/              transcripciones de fuentes escaneadas
data/processed/           salidas de contrato
tests/fixtures/           crudos reales o recortados, para probar sin red
```

## Contrato de datos · `schema_version` 2.1
Las rutas son estables y el frontend depende de ellas. **Un cambio de esquema es un cambio de versión:** campo eliminado, renombrado o con otro significado sube la versión mayor. Los campos nuevos opcionales suben la menor.

| Ruta | Contenido |
|---|---|
| `data/processed/<iso3>.json` | Registro, segmentos de fuente, rupturas y año máximo de un país. Existe para los 20, aun sin datos. |
| `data/processed/pyramids/<iso3>.json` | Pirámide por año: hombres y mujeres en 17 grupos comunes, con su fuente. Existe para los 20, aun sin datos. |
| `data/processed/latam.csv` | Todos los registros, en formato largo. |
| `data/processed/region.json` · `region.csv` | Agregado propio de los 20 países: total, crecimiento, índice y pirámide. No es una cifra oficial. |
| `data/processed/aging.json` · `aging.csv` | Índice de envejecimiento por país y región, calculado con las pirámides. No es una cifra oficial. |
| `data/processed/manifest.json` | Fuentes, niveles, vintages y fechas vigentes por país y serie. |
| `data/processed/licenses.json` | Revisión de términos por institución: estado, texto leído, cita exigida y condiciones. |
| `data/status.json` | Estado, última actualización, nivel de fuente y error por país y serie. |
| `data/alerts.json` · `data/source_changes.json` | Alertas de la corrida y bitácora de cambios de fuente o vintage. |

**Cada registro:**

| Campo | Tipo | Significado |
|---|---|---|
| `iso3` | texto | País |
| `year` | entero | Año |
| `population` | número o null | Personas, con el valor publicado (sin redondear). La ONU publica en miles y se multiplica por 1000. |
| `series_type` | `observed` · `estimate` · `projection` | Sigue el rótulo de la fuente. Hoy no hay `observed`: las series históricas son estimaciones oficiales ancladas en censos. |
| `source_id` · `source_tier` | texto · `national` / `international_fallback` | Fuente y nivel |
| `vintage` · `scenario` | texto · `single` / `medium` / `recommended` / null | Edición y escenario |
| `reference_date` | `MM-DD` · `mid-year` · `census` · null | Fecha de referencia de la cifra; `census` es la fecha de cada censo |
| `retrieved_at` | fecha | Primera descarga de este archivo (mismo hash) |
| `interpolated` | booleano | Siempre `false` hoy: no se interpola |
| `growth` | número o null | `(P_t / P_{t-1}) − 1`, solo dentro de la misma fuente y vintage |
| `raw_file` | ruta | Archivo de `data/raw/` del que sale la cifra |

**Cambios:** la 1.1 admite `reference_date: census` (hoy sin uso). La 1.2 agrega las pirámides y `pyramid` en `status.json`. La 1.3 agrega `parts` y `part`, porque una pirámide puede combinar dos fuentes. La 1.4 agrega `licenses.json` y el campo `license` en segmentos, `status.json`, `parts` y `latam.csv`. La 1.5 agrega `region.json`, `region.csv` y `region` en `status.json`. Hasta la 1.5 son compatibles con la 1.0. La 2.0 reemplaza el valor `regional_fallback` por `international_fallback`, en `source_tier` y en `region.json` y `region.csv`, porque el respaldo ya no es regional. La 2.1 agrega `aging.json` y `aging.csv`.

**Pirámides:** `age_groups` lista 0-4 … 75-79 y 80+. `years["2025"]` trae `m` y `f` (17 valores) más `series_type`, `source_id`, `vintage`, `source_tier` y `reference_date`, los mismos del registro de ese año, y `part`, el índice de `parts`. Cada elemento de `parts` da `institution`, `source_url`, `source_tier`, `location_in_file` y `raw_files` (ruta, hash, fecha). Además `status`, `reason`, `note` y `raw_files` con todos los crudos. Cada año usa la parte del mismo nivel de fuente que la serie de ese año. Solo se suman grupos publicados; no se desagrega ni se interpola. Un año se publica únicamente si hombres + mujeres cuadra con el total oficial de ese año (tolerancia de 0,05 %); si no, se excluye y genera una alerta.

**Región (`region.json`):** agregado propio, con `official: false` y `derived: true`; `note` declara en español e inglés qué mezcla y de qué depende. `years` lista los años con dato de los 20 países. `points` trae por año `population` (suma redondeada a personas), `n_projection`, `international_fallback` (países con CEPAL/CELADE), `reference_dates`, `shares` y `components`, con fuente, vintage, `license` y `raw_file` de cada país. `periods` trae la tasa anual media entre años consecutivos (`rate`), `country_rates`, `n_countries`, `covers_share` y `excluded`. `index["2025"]` trae el índice de cada año contra esa base. `pyramid` suma las 20 pirámides en `years` y lista en `missing_by_year` qué países faltan en los demás años.

**Envejecimiento (`aging.json`):** `100 × población de 65 años y más / población de 0 a 14`, sumando hombres y mujeres de la pirámide publicada de cada año. `countries[<iso3>].rows` trae `year`, `aging_index`, `pop_0_14`, `pop_65_plus`, `series_type`, `source_id`, `vintage`, `source_tier` y `reference_date`, los mismos de la pirámide de ese año, y `breaks` lista los cambios de fuente o edición. `region` existe solo en los años con pirámide regional. Un año sin pirámide queda sin índice: nada se interpola. Es un cálculo propio que coincide con lo publicado por Costa Rica, Paraguay y Chile (este último, con un decimal), y las pruebas lo comprueban contra sus archivos. INE Guatemala publica otra definición (60 años y más sobre 15 y menos), así que su cifra no es comparable con esta.

**Por país**, además: `segments` (institución, URL, vintage, hash, ubicación en el archivo), `breaks` (ruptura con año de corte y sin ajuste), `peak` (`peak`, `no_peak_in_horizon` o `no_projection`) y `reasons` en español e inglés.

**Valores de `status`:** `ok`; `manual` (archivo aportado por una persona); `manual_pendiente` (falta ese archivo); `stale` (la fuente falló y se conservan sus últimos datos válidos); `error`; `pendiente`.

## Reglas que el código hace cumplir
- Las uniones entre fuentes o vintages no se encadenan ni se ajustan: se registran como ruptura y el crecimiento no se calcula a través de ellas.
- `cagr()` devuelve `None` si los dos años están en series distintas.
- Si un año tiene dato nacional e internacional, queda el nacional y se genera una alerta.
- Validaciones: años duplicados, huecos, variación anual fuera de ±4 %, discrepancia con la cifra de control, cambio de vintage o de nivel. Solo alertan.
- Si una fuente falla, los demás países siguen y esa conserva su último crudo válido.
- El total regional solo existe en años con dato de los 20 países: nunca se rellena un hueco ni se publica un total parcial. Crecimiento e índice regionales excluyen y listan al país que cambia de serie entre los dos años.
- Descarga con agente identificado, TLS activo y respeto de `robots.txt`. Login, captcha, bloqueos de red o `robots.txt` llevan a método manual. No se eluden.

## Ejecutar
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
python -m latam_pop run
```

## Automatización
`.github/workflows/update.yml` corre cada lunes y por disparo manual. Hace commit solo si cambian los datos y abre un issue con la etiqueta `pipeline` si un adaptador falla, salta una validación nueva o cambia un portal vigilado donde se usa la ONU. Una falla de fuente no pone el workflow en rojo: queda en `status.json` y en un issue.

**Respaldo en jsDelivr:** jsDelivr rechaza los paquetes de más de 50 MB, cachea las rutas de una rama hasta 12 horas y limita las purgas por ruta, así que no puede servir `main`, ni una rama archivo por archivo, de forma fiable. La rama `respaldo-cdn` contiene `data/` sin `data/raw/` y `respaldo.json`, que nombra el commit de la última publicación completa. Si falla raw.githubusercontent.com, la página lee ese puntero y pide cada archivo por commit: `https://cdn.jsdelivr.net/gh/jaforero/latam-population-official@<commit>/data/status.json`. Esas rutas son inmutables, así que nunca se mezclan dos publicaciones. La rama no se edita a mano. La mantiene `.github/workflows/respaldo-cdn.yml` con `scripts/publish_cdn.py`, en cada push a `main` que toque `data/`, después de cada corrida semanal y una vez al día como comprobación. Publica todo lo que haya bajo `data/`, así que un archivo nuevo del contrato no requiere cambios. Después compara el hash de cada archivo servido con el de `main` y purga solo el puntero; si algo sigue atrasado tras los reintentos, el workflow queda en rojo y abre un issue `pipeline`.

**Secrets:** `KAGGLE_API_TOKEN` solo para `kaggle.yml`. Ninguna fuente actual requiere token. Si alguna lo exige, léelo con `os.environ` desde un secret llamado `<ISO3>_API_TOKEN`, documenta el nombre aquí y nunca lo escribas en el código.

## Dataset en Kaggle
`scripts/build_kaggle_dataset.py` reconstruye `dist/kaggle/` (no versionado) desde `data/processed/`, `data/status.json` y `data/alerts.json`. No incluye `data/raw/` ni cambia cifras: añade nombres de país, institución, estado de licencia y la marca `source_break`, y comprueba que cada tabla reproduzca su producto canónico. Lo versionado está en `kaggle/`: `columns.yaml` (diccionario y encabezados esperados; si el contrato cambia, la exportación se detiene), plantillas de README y metadata, y `license_policy.yaml`.

La puerta de licencias bloquea la publicación pública mientras haya fuentes sin licencia localizada, con términos propios que no declaran redistribución o uso comercial, o share-alike incompatibles entre sí, salvo que el dueño registre su decisión en `license_policy.yaml`. El informe queda en `dist/PUBLICATION_BLOCKERS.md`. La licencia de Kaggle es `other`: cada cifra conserva la de su fuente.
```bash
python scripts/build_kaggle_dataset.py
python -m pytest -q tests/test_kaggle_export.py
python scripts/publish_kaggle.py status
```
`publish_kaggle.py create` sube una primera versión privada (`--public` exige la puerta en PASS) y `publish_kaggle.py version` crea una versión nueva solo si cambió el contenido, con commit, esquema y series cambiadas en la nota. Nunca borra versiones. `.github/workflows/kaggle.yml` hace lo mismo por disparo manual con el secret `KAGGLE_API_TOKEN`.

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
- **Cuba:** cualquier serie de ONEI verificable reemplazaría a la ONU.

La página del INE de Bolivia ofrece cuadros 2000-2050 casi idénticos de las revisiones 2014, 2020 y 2025: el pie del cuadro dice cuál es.

Si el archivo manual es de una pirámide, usa `ingest ISO3 pyramid ARCHIVO`.

## Cómo agregar un país o una fuente
1. Agrega o completa la entrada en `sources.yaml`: `source_tier`, URL exacta, `adapter`, `source_id`, `raw_key`, `year_from`, `year_to`, vintage, referencia temporal y una **cifra de control** leída en la fuente. Un país nuevo también va en `latam_pop/__init__.py` y en `NAMES` de `build.py`.
2. Escribe el adaptador en `latam_pop/adapters/sources.py` con `@register("nombre")`. Basta implementar `parse`, que devuelve `{año: población}` tal como se publica.
3. Agrega un fixture en `tests/fixtures/` y el caso en `tests/test_parsers.py`.
4. Para sustituir la ONU por una serie nacional, cambia la entrada a `source_tier: national`. El pipeline registra el cambio en `source_changes.json` y abre un issue. Ajusta `test_fallback_only_where_declared`.
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
- **Licencias:** seis instituciones no tienen licencia localizada. Ver [Términos de uso de las fuentes](#términos-de-uso-de-las-fuentes).
- **Vintages:** Perú, Honduras y El Salvador tienen una edición nueva esperada o citada; Venezuela usa una proyección de 2013. Rep. Dominicana usa una serie anterior a la edición con censo 2022 que la ONE anunció en junio de 2026.
- **Cuba:** usa la ONU porque ONEI no es verificable (certificado vencido). La vigilancia avisa si el portal vuelve a responder.
- **Peso:** `data/raw/` ocupa unos 230 MB y conserva cada versión de los archivos.
- **Respaldo:** jsDelivr permite pocas purgas por ruta y por hora. Tras varias publicaciones seguidas, el puntero puede tardar hasta una hora en cambiar y el workflow espera. Mientras tanto, si falla la fuente principal, la página lee la publicación anterior completa y avisa que puede no incluir lo más reciente.
- **Historial de Git:** `main` se reescribió el 2026-11-01 para quitar los archivos de CEPAL/CELADE, así que cambiaron los identificadores de todos los commits posteriores al de la Fase 0. El repo se borró y se recreó con el mismo nombre para cortar también el acceso por identificador a los commits viejos; por eso las corridas de Actions empiezan en esa fecha y los issues quedaron a nombre de su dueño. Los JSON y CSV procesados de commits anteriores conservan esas cifras, que coinciden con las de la ONU salvo redondeo.
- **Región:** hay total de 2010 a 2040, cada cinco años, porque Rep. Dominicana y Venezuela publican cada cinco años y Argentina solo cubre ese tramo. Hay pirámide regional solo en 2025 y 2030: Bolivia publica edades de 2024 a 2034, Argentina desde 2022 y Nicaragua desde 2023. El total depende de CEPAL/CELADE para Cuba, Haití, la historia de Honduras y la proyección de Nicaragua: sin esas cifras no habría total de los 20 países.
- **Red:** algunos sitios pueden bloquear los ejecutores de GitHub Actions aunque respondan desde otra conexión; en ese caso la serie pasa a `stale`.

## Términos de uso de las fuentes
Revisados el 2026-11-01. Es una lectura de textos publicados, no un dictamen jurídico. El registro está en `sources.yaml` (`licenses`) y se publica en `data/processed/licenses.json` con la cita exigida y el enlace a cada texto.

| Resultado | Instituciones | Qué implica |
|---|---|---|
| Licencia abierta leída | INDEC, INE Chile, INEC Costa Rica, ONE (Rep. Dominicana), INEC Ecuador, CONAPO, INEC Panamá, INE Paraguay, ONU | Permiten redistribuir con atribución. Argentina, Chile y Costa Rica (CC BY-SA 4.0) y Rep. Dominicana (ODbL) piden compartir lo derivado bajo la misma licencia. |
| Condiciones propias leídas | INE Bolivia, DANE, INEI, INE Uruguay | Bolivia y Perú permiten reproducir citando; Bolivia limita el uso comercial. DANE autoriza transformar y analizar con cita textual, sin mencionar la redistribución de archivos. INE Uruguay considera pública la información, sin regular su reutilización. |
| Sin licencia localizada | IBGE, INE Guatemala, INE Honduras, INIDE, ONEC/BCR, INE Venezuela | No hay permiso expreso para republicar los archivos. No equivale a una prohibición. |

**Copias crudas:** de los 36 archivos de `data/raw/`, 9 no tienen permiso expreso de redistribución, todos de instituciones sin licencia localizada. Siguen aquí por trazabilidad.

**CEPAL/CELADE:** se retiró el 2026-11-01. La cláusula 4 de [su acuerdo de uso](https://www.cepal.org/es/terminos-y-condiciones-sobre-el-uso-del-sitio-web-entre-la-cepal-y-el-usuario), que enlaza CEPALSTAT, limita la descarga a uso personal y no comercial, sin redistribuir ni crear otros trabajos.

**Cambios respecto a los originales:** se extrae la población total, los miles de la ONU pasan a personas, las edades se suman en 17 grupos comunes y aquí se calculan el crecimiento, el año máximo y el total regional. Ninguna cifra se corrige.

## Licencia
El código puede reutilizarse con atribución. Este repositorio no otorga una licencia nueva sobre los datos: cada cifra conserva las condiciones de su fuente, registradas en el campo `license`. `region.json` y `region.csv` son una base derivada que combina esas condiciones, incluidas CC BY-SA y ODbL; cada componente conserva la licencia de su fuente. Lo derivado de fuentes CC BY-SA 4.0 u ODbL se comparte bajo esa misma licencia.

Javier Forero · [javierforero.co](https://javierforero.co)
