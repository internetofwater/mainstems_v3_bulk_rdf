# mainstems-bulk-rdf

Geoconnex [bulk integration](https://docs.geoconnex.us/contributing/bulk/) for the
mainstems reference dataset published by
[internetofwater/ref_rivers](https://github.com/internetofwater/ref_rivers/releases),
which is also what backs the `mainstems` collection on
[reference.geoconnex.us](https://reference.geoconnex.us/collections/mainstems).

Unlike the other bulk integrations in this org (`wqp_bulk_exports`,
`usgs_monitoring_locations_bulk_exports`), mainstems is a single static,
versioned GeoPackage rather than a paginated live API, so there is no
separate crawl/geoparquet-export stage. The one container
(`src/template.py`) downloads `mainstems.gpkg` from the
[ref_rivers v3.2 release](https://github.com/internetofwater/ref_rivers/releases/tag/v3.2)
(or reads a local/pre-downloaded copy), reads its `mainstems` table directly with
`sqlite3` (a GeoPackage is just SQLite; geometry blobs are parsed by hand,
so no GDAL/pyogrio dependency is needed), and streams one JSON-LD document
per line to standard out, conforming to the
[Geoconnex SHACL shape](https://docs.geoconnex.us/reference/data-formats/shacl_shape).
Built and pushed to `ghcr.io/internetofwater/mainstems_v3_bulk_rdf` by
[`.github/workflows/push_to_ghcr.yml`](.github/workflows/push_to_ghcr.yml) on every
push to `main`.

Earlier versions of this container read `mainstems_v3.gpkg` from
[HydroShare](https://www.hydroshare.org/resource/3295a17b4cc24d34bd6a5c5aaf753c50/)
instead. That copy has the same table schema as the v3.2 GitHub release, but
see "Known data quality issue" below for why it was dropped.

Identifiers match the `https://geoconnex.us/ref/mainstems/{id}` PIDs already used
by reference.geoconnex.us — this bulk container is a replacement for how that
data enters the Geoconnex graph, not a new namespace.

## Known data quality issue: `downstream_mainstem_id` (fixed as of v3.2)

The `mainstems_v3.gpkg` published on HydroShare has a `downstream_mainstem_id`
column that is either blank or **equal to the record's own `uri`** for
effectively every row (852,469 of 852,653; 0 rows point anywhere else). This
is inconsistent with reference.geoconnex.us's live database, which does serve
real `hyf:downstreamWaterbody` links (e.g. mainstem `2092505` correctly points
downstream to `2091907`) — the ref_rivers R pipeline that builds this dataset
visibly computes real cross-references for this field, so the HydroShare file
appears stale or affected by a publishing bug relative to what's deployed
live.

The [v3.2 release](https://github.com/internetofwater/ref_rivers/releases/tag/v3.2)
on GitHub fixes this: 840,106 of 852,673 rows now carry a real, non-self-referential
`downstream_mainstem_id`, and 0 rows are self-referential (the remaining
12,567 are legitimately blank -- e.g. mainstems draining to the ocean or the
edge of the network). That's why `DEFAULT_GPKG_URL` in `src/template.py`
points at this GitHub release instead of HydroShare. `downstream_waterbody()`
still guards against a self-referential value rather than trusting the source
data unconditionally, but it's no longer expected to trigger.

## Other deviations from the old JSON-LD template

AGENTS.md points at the
[old pygeoapi JSON-LD template](https://github.com/internetofwater/reference.geoconnex.us/blob/main/pygeoapi-skin-dashboard/templates/jsonld/mainstems/collections/items/item.jsonld)
used for the v2 gpkg. A few of its fields/quirks don't carry over cleanly to v3
and were intentionally fixed rather than reproduced:

- It reads `data.outlet_drainagearea`; the actual column (both in v3 and in
  the live API) is `outlet_drainagearea_sqkm`. Using the stale name would have
  silently dropped `gsp:hasArea` from every feature.
- It gates `gsp:hasLength` behind the same `if` as `gsp:hasArea` (`{% if
  data.outlet_drainagearea %}`), which would drop length for the ~1 row
  missing drainage area. Each is now gated on its own value.
- For a superseded mainstem with more than one successor, it renders
  `"@id": ['url1', 'url2']` (a raw Python list spliced into a JSON string) —
  this is what reference.geoconnex.us serves live today, but it's invalid
  JSON-LD (`@id` must be a single IRI). This export instead emits
  `schema:supersededBy` as an array of `{"@id": ...}` nodes, one per
  successor.
- `qudt:value` is emitted as a plain JSON number (e.g. `808.9`) instead of the
  template's `"{{ value }}"^^xsd:double` (Turtle syntax spliced into a JSON
  string, only usable because pygeoapi's renderer isn't a strict JSON
  serializer). JSON-LD's default numeric coercion already maps a JSON number
  with a decimal point to `xsd:double`.

`name_at_outlet_gnis_id` / `primary_name_gnis_id` and
`encompassing_mainstem_basins` exist in the GeoPackage but aren't surfaced in
the live JSON-LD either, so they're left out here too for parity.

## Development

Requires [uv](https://docs.astral.sh/uv/) and network access to
`github.com` / `release-assets.githubusercontent.com` (see
[`dev-kit/spec.yaml`](dev-kit/spec.yaml)).

```bash
make deps                             # uv sync
make run_test                         # stream JSON-LD for the first 2000 rows only
make run_full                         # stream JSON-LD for the full dataset (852k+ rows)
make build_geoconnex_bulk_container
make run_geoconnex_bulk_container            # downloads the gpkg from GitHub itself
make run_geoconnex_bulk_container_local      # reuses ./mainstems.gpkg if already downloaded
```

`prek` (pre-commit) handles linting/formatting/license headers:

```bash
make prek
```
