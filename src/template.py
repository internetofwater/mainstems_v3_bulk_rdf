# Copyright 2026 Lincoln Institute of Land Policy
# SPDX-License-Identifier: MIT

import argparse
import ast
import json
import logging
import sqlite3
from multiprocessing import Pool, cpu_count
from pathlib import Path
from typing import Final

import requests
import shapely

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)

# The dataset described in AGENTS.md. Mainstems is a static, versioned
# reference dataset (unlike e.g. WQP or a live API), so the container reads
# it directly -- there is no separate crawl/geoparquet-export stage.
#
# This is the v3.2 release from internetofwater/ref_rivers on GitHub, not the
# mainstems_v3.gpkg published on HydroShare. The HydroShare copy has a known
# data bug where downstream_mainstem_id is blank or self-referential for
# effectively every row (see git history / README.md); this release fixes
# that -- see downstream_waterbody() below.
DEFAULT_GPKG_URL: Final[str] = (
    "https://github.com/internetofwater/ref_rivers/releases/download/"
    "v3.2/mainstems.gpkg"
)

# Columns pulled from the gpkg's `mainstems` table. See README.md for how
# these map onto the JSON-LD produced below, and for two columns
# (name_at_outlet_gnis_id/primary_name_gnis_id, encompassing_mainstem_basins)
# that exist in the table but are intentionally left out to match what
# reference.geoconnex.us currently publishes for this collection.
COLUMNS: Final[list[str]] = [
    "uri",
    "name_at_outlet",
    "primary_name",
    "downstream_mainstem_id",
    "lengthkm",
    "outlet_drainagearea_sqkm",
    "outlet_nhdpv2_COMID",
    "outlet_nhdpv2HUC12",
    "new_mainstemid",
    "geom",
]

BATCH_ROWS: Final[int] = 20_000


def clean(value: object) -> object:
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def clean_str(value: object) -> str | None:
    cleaned = clean(value)
    return cleaned if isinstance(cleaned, str) else None


def gpkg_geometry_to_wkt(blob: bytes) -> str:
    """
    Parse a GeoPackage binary geometry ("GPB") blob into a WKT string.
    GPB is a small header (magic "GP", version, flags, SRS id, and an
    optional envelope controlled by the flags) followed by standard WKB;
    see OGC GeoPackage spec clause 2.1.3. Parsed directly with shapely so
    the container doesn't need a GDAL/pyogrio dependency just to read one
    static file.
    """
    flags = blob[3]
    envelope_indicator = (flags >> 1) & 0x07
    envelope_sizes = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}
    header_len = 8 + envelope_sizes[envelope_indicator]
    return shapely.from_wkb(bytes(blob[header_len:])).wkt


def realized_catchment(row: dict) -> list[dict] | None:
    # Only the outlet's catchment is used, matching what
    # reference.geoconnex.us currently publishes for this collection.
    catchments = [
        {"@id": uri}
        for uri in (
            clean(row["outlet_nhdpv2_COMID"]),
            clean(row["outlet_nhdpv2HUC12"]),
        )
        if uri
    ]
    return catchments or None


def superseded_by(row: dict) -> dict | list[dict] | None:
    # new_mainstemid holds a Python-repr'd list of 0+ URIs (e.g.
    # "['https://.../1815586', 'https://.../1921673']"), not JSON.
    raw = clean_str(row["new_mainstemid"])
    if not raw:
        return None
    nodes = [{"@id": uri} for uri in ast.literal_eval(raw)]
    return nodes[0] if len(nodes) == 1 else nodes


def downstream_waterbody(row: dict) -> dict | None:
    downstream = clean(row["downstream_mainstem_id"])
    # A blank downstream_mainstem_id is legitimate (e.g. a terminal mainstem
    # draining to the ocean or the edge of the network). A self-referential
    # value shouldn't occur in this release (unlike the HydroShare
    # mainstems_v3.gpkg -- see README.md), but is guarded against anyway
    # rather than emitting a nonsensical self-loop.
    if not downstream or downstream == row["uri"]:
        return None
    return {"@id": downstream}


def row_to_jsonld(row: dict) -> dict | None:
    uri = clean(row["uri"])
    geom = row["geom"]
    if not uri or not geom:
        return None

    place = {
        "@context": {
            "@vocab": "https://schema.org/",
            "gsp": "http://www.opengis.net/ont/geosparql#",
            "hyf": "https://www.opengis.net/def/schema/hy_features/hyf/",
            "qudt": "http://qudt.org/schema/qudt/",
            "unit": "http://qudt.org/vocab/unit/",
        },
        "@id": uri,
        "@type": ["hyf:HY_FlowPath", "hyf:HY_WaterBody", "Place"],
        # Required by the Geoconnex SHACL LocationOrientedShape (minCount 1),
        # but roughly 80% of mainstems (mostly minor headwater segments) have
        # no name in the source data. reference.geoconnex.us currently
        # serves "" for these; fall back to primary_name first since a
        # handful of rows have that populated when name_at_outlet is not.
        "name": clean(row["name_at_outlet"]) or clean(row["primary_name"]) or "",
        "hyf:downstreamWaterbody": downstream_waterbody(row),
        "hyf:realizedCatchment": realized_catchment(row),
        "gsp:hasArea": (
            {
                "qudt:unit": "unit:KiloM2",
                "qudt:value": clean(row["outlet_drainagearea_sqkm"]),
            }
            if clean(row["outlet_drainagearea_sqkm"]) is not None
            else None
        ),
        "gsp:hasLength": (
            {"qudt:unit": "unit:KiloM", "qudt:value": clean(row["lengthkm"])}
            if clean(row["lengthkm"]) is not None
            else None
        ),
        "supersededBy": superseded_by(row),
        "gsp:hasGeometry": {
            "@type": "http://www.opengis.net/ont/sf#LineString",
            "gsp:asWKT": {
                "@type": "gsp:wktLiteral",
                "@value": gpkg_geometry_to_wkt(geom),
            },
        },
    }
    # remove nulls (SHACL cleanliness)
    return {k: v for k, v in place.items() if v is not None}


def get_gpkg_path(file_location: str) -> Path:
    if Path(file_location).exists():
        LOGGER.info("Found GeoPackage locally")
        return Path(file_location)

    download_path = Path(__file__).parent / "mainstems.gpkg"
    if download_path.exists():
        LOGGER.info(f"Reusing previously downloaded GeoPackage at {download_path}")
        return download_path

    LOGGER.info(f"Downloading GeoPackage from {file_location}")
    with requests.get(file_location, stream=True, timeout=600) as response:
        response.raise_for_status()
        with open(download_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
    return download_path


def iter_row_batches(gpkg_path: Path, limit: int | None):
    con = sqlite3.connect(gpkg_path)
    try:
        cur = con.cursor()
        query = f"SELECT {', '.join(COLUMNS)} FROM mainstems"
        if limit:
            query += f" LIMIT {limit}"
        cur.execute(query)
        while batch := cur.fetchmany(BATCH_ROWS):
            yield [dict(zip(COLUMNS, row)) for row in batch]
    finally:
        con.close()


def process_row(row: dict) -> str | None:
    jsonld = row_to_jsonld(row)
    if jsonld is None:
        return None
    return json.dumps(jsonld, allow_nan=False)


def main(file_location: str, limit: int | None) -> None:
    gpkg_path = get_gpkg_path(file_location)
    num_workers = max(cpu_count() - 1, 1)

    total = 0
    with Pool(processes=num_workers) as pool:
        for batch in iter_row_batches(gpkg_path, limit):
            lines = [
                line for line in pool.map(process_row, batch, chunksize=500) if line
            ]
            if lines:
                print("\n".join(lines))
            total += len(lines)

    LOGGER.info(f"Streamed {total} JSON-LD records")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--gpkg_file", type=str, default=DEFAULT_GPKG_URL)
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only read the first N rows of the GeoPackage, for local testing",
    )
    args = parser.parse_args()
    main(args.gpkg_file, args.limit)
