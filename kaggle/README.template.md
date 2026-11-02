# Latin America Population: 20 Countries

Annual total population, official estimates and projections, and age-sex pyramids for 20 Latin American countries,
taken from national statistics offices and, only where a national series cannot be verified, from the UN World
Population Prospects 2024. Every row says who published the figure, which edition (vintage) it comes from, whether
it is an estimate or a projection, and under which terms it can be reused.

- **Source repository (single source of truth):** {{repo_url}}
- **Dashboard built on the same data:** {{dashboard_url}}
- **This version:** repository commit `{{commit_short}}` · data contract `schema_version {{schema_version}}` · data last updated {{data_updated}}

## About the dataset

**Countries (20):** {{country_list}}.

**Period:** {{year_min}}-{{year_max}}, depending on what each source publishes. `population_latam.csv` has {{n_rows}}
country-years: {{n_estimate}} estimates and {{n_projection}} projections; {{n_fallback}} come from the UN fallback.

{{countries_table}}

### Estimate, projection, observed

- `estimate`: official retrospective figure anchored in censuses (and, for the UN, in its own estimation).
- `projection`: official forward projection.
- `observed`: a raw census count. The contract allows it, but **no row uses it today**: no series in this dataset is
  a direct census count.

The label follows the source. A year can be an estimate in one country and a projection in another; the switch
year depends on each institution's base year.

### National sources and `international_fallback`

`source_tier = national` means the figure is published by the national statistics office (or the agency with a
legal mandate). `source_tier = international_fallback` means the UN World Population Prospects 2024 (medium
variant), used **only for the country and series where the national institution does not publish a verifiable,
downloadable series** (in this version: {{fallback_summary}}). A national figure always
takes precedence over the UN.

### Vintage

The `vintage` is the edition or revision of a source (for example `Rev. 2024`, `Censo 2022`, `ONU WPP 2024`).
Institutions revise their estimates after each census, so two vintages of the same institution can give different
numbers for the same year. This dataset keeps exactly one figure per country-year and records which vintage it is.

### Source breaks

A **source break** is the first year in which a country's series comes from a different source, vintage or tier
(for example a new census-based revision replacing the previous one). There are
{{n_breaks}} breaks, listed in `source_breaks.csv` and flagged with `source_break = True` in the main table. Series
are **never chained or adjusted** across a break, and `growth` is left empty at every break.

### Why gaps are not filled

Some sources publish every five years (Dominican Republic, part of Venezuela) or only cover recent years. Missing
years stay missing: nothing is interpolated, smoothed, back-cast or taken from secondary aggregators. A gap is
information about what the source publishes.

## Why this dataset exists

To offer a reproducible, traceable collection of official Latin American population series and projections, where
each number can be followed back to the institution, the file, its SHA-256 hash and the table it was read from.
Traceability takes precedence over coverage: a country without a verifiable source would be left pending, never
filled.

## Source hierarchy

1. **National statistics office** or agency with a legal mandate, including its open-data portal.
2. **International fallback:** UN World Population Prospects 2024 (medium variant), per country and per series,
   only when the national institution does not publish that series in a verifiable, downloadable form.
3. **No secondary aggregators:** World Bank, Wikipedia, Statista, Our World in Data and similar are never used to
   fill a gap.

## Files

{{files_table}}

See `DATA_DICTIONARY.md` for every column (type, unit, nullability, origin) and `SOURCES_AND_LICENSES.md` for the
terms of each institution. `manifest.json` and `SOURCE_COMMIT.txt` identify the exact repository commit, the
data-contract version and the SHA-256 of each file.

**What does each row represent?**

- `population_latam.csv`: one country-year (key `iso3 + year`).
- `population_pyramids.csv`: one country-year-sex-age group (key `iso3 + year + sex + age_group`).
- `aging_index.csv`: one country-year (key `iso3 + year`).
- `population_region.csv`: one year of the derived 20-country sum (key `year`).
- `sources.csv`: one source segment (key `iso3 + series + source_id + vintage`). Join it on `iso3`, `source_id` and
  `vintage`.

## Methodology

- **Source rules.** One registered source per country and series (`historical`, `projection`, `pyramid`), with its
  exact URL, file hash, location in the file and a control figure checked by the pipeline. If a year has both a
  national and an international figure, the national one is kept.
- **No interpolation.** `interpolated` is always `False`. Values are as published; UN figures (published in
  thousands) are multiplied by 1000.
- **Breaks.** Recorded, never adjusted. `growth = P_t / P_(t-1) - 1` is computed only within the same source and
  vintage.
- **Regional aggregate (`population_region.csv`) — derived, not official.** The repository's own sum of the 20
  countries. It exists **only** in years where all 20 countries have a figure ({{region_years}}); a partial total is
  never published. It mixes national and UN figures, estimates and projections, and different vintages and
  reference dates. The regional growth rate compares each country with itself and excludes (and lists) any country
  whose source or vintage changes between the two years.
- **Pyramids.** 17 common five-year groups (0-4 ... 75-79, 80+), males and females. Groups are built only by adding
  groups the source publishes; `80+` is open-ended and never split. A year is published only when males + females
  match the official total of that year within 0.05 %. The regional pyramid (`iso3 = REG`) exists only for
  {{region_pyramid_years}}, the years with a pyramid for all 20 countries.
- **Ageing index (`aging_index.csv`) — derived, not official.** `100 × population 65+ / population 0-14`, from each
  country's published pyramid. It matches the figures published by Costa Rica, Paraguay and Chile; other
  institutions may use other definitions (INE Guatemala publishes 60+ over 0-15), so national publications are not
  always comparable with this column.
- **Quality alerts.** `quality_alerts.csv` lists the pipeline's validation alerts (annual change beyond ±4 %,
  unusual sex ratios...). Alerts never change the data.

## Can I compare two years directly?

Within the same `source_id` and `vintage`, yes. Across a source break (`source_break = True`, `source_breaks.csv`)
the difference mixes real change with methodological differences between editions. Between countries, check
`reference_date` (mid-year vs 1 January) and `series_type`. The regional aggregate mixes all of these by design.

## Provenance

- Repository: {{repo_url}} (commit `{{commit}}`)
- Dashboard: {{dashboard_url}}
- Raw files are **not** redistributed here. The `raw_file` and `raw_sha256` columns identify each original file in
  the repository, where its download date and URL are recorded.

## Citation

Please cite both this dataset and the original institutions:

> Forero, J. (2026). *Latin America Population: 20 Countries* [Data set]. Kaggle.
> https://www.kaggle.com/datasets/jaforero/latin-america-population-20-countries. Built from {{repo_url}}, commit `{{commit_short}}`.

and, for each figure you use, the institution's citation in the `attribution` column of `sources.csv` (for example
*"Fuente: INDEC, Argentina"* or *"United Nations, Department of Economic and Social Affairs, Population Division
(2024). World Population Prospects 2024"*). The statistics belong to the institutions that publish them.

## Licence

This dataset does **not** grant a new licence over the data. The Kaggle licence field is `{{kaggle_license}}`:
each figure keeps the terms of its source, recorded per row in the `license` column and described in
`SOURCES_AND_LICENSES.md` ({{license_counts}}). Some institutions publish under CC BY-SA 4.0 or ODbL (share-alike);
some have their own terms (one limits commercial use without authorization); for some, no licence was found,
which is neither a permission nor a prohibition. Check the terms of the sources you use before reusing them,
especially for commercial purposes.

## Limitations

- **Mixed vintages and base years.** Some countries rely on old editions (Venezuela: projection based on the 2011
  census; several countries still use pre-2020-census revisions), and newer editions may exist or be announced.
- **UN fallback** for {{fallback_summary}}: these are UN estimates and projections, not national figures.
- **Uneven coverage.** Series lengths, pyramid years and reference dates differ by country. The regional total
  exists only every five years from 2010 to 2040, and the regional pyramid only for 2025 and 2030.
- **Projections are scenarios** made by each institution at a given time, with their own assumptions.
- **Derived products** (`population_region.csv`, `aging_index.csv`, `REG` rows) are the repository's own
  calculations, not official statistics.
- **Terms of use** differ by institution and some are undetermined (see `SOURCES_AND_LICENSES.md`).

## En español

Población total anual, estimaciones y proyecciones oficiales y pirámides por edad y sexo de 20 países de América
Latina, tomadas de los institutos nacionales de estadística y, solo donde la serie nacional no es verificable, de
la ONU (WPP 2024). Cada fila indica la institución, la edición (`vintage`), si es estimación o proyección y sus
condiciones de uso. No se interpola ni se rellena ningún hueco, y las series no se encadenan entre ediciones: los
cambios de fuente quedan en `source_breaks.csv`. El total regional y el índice de envejecimiento son cálculos
propios, no cifras oficiales. La fuente de verdad es el repositorio {{repo_url}}; el dashboard
{{dashboard_url}} es solo una capa de presentación. Cite siempre a la institución de origen.
