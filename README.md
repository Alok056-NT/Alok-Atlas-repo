# Outlet Atlas — pre-loaded OpenStreetMap layers

Data for the Outlet Atlas **Map Layers → OSM features → Load in this view** panel. It is pulled in bulk
from OpenStreetMap, so the Atlas doesn't depend on the busy free Overpass servers every time someone
loads a layer.

## Layout

```
osm-data/index.json        every city: file slug, extent [south, west, north, east], feature counts
osm-data/<city-slug>.json  one file per Atlas city, all 8 categories
tools/                     the scripts that produced it (pull + package)
```

There is one file per city, not one per city and category. A single click usually loads several
categories for one city, so one file means one request. The largest city file is still only a few MB.

### City file (`v: 1`)

```jsonc
{
  "v": 1, "city": "Pune", "slug": "pune", "bbox": [s, w, n, e],
  "osm_base": "2026-09-15T15:09:01Z",        // OpenStreetMap data timestamp
  "counts": { "commercial": 892, ... },
  "empty":  { "metro": "no OSM features tagged ..." },   // only categories with 0 results
  "f": { "commercial": [ [id, tags, geom], ... ], ... }
}
```

* `id`: OSM type letter plus id (`n123`, `w123`, `r123`).
* `tags`: only the keys the Atlas reads (`name`, `name:en`, `landuse`, `office`, `shop`, `amenity`,
  `highway`, `railway`, `station`).
* `geom`: a point is `[lat, lon]`. An area is `[[lat,lon,lat,lon,…], …]`, one flat closed ring per
  outline.

Commercial, retail and industrial **keep their outlines**: rings are simplified (Douglas-Peucker, about 2 m)
and rounded to 5 decimals (about 1 m). Catchment and coverage in the Atlas still measure from a mall's or
estate's edge, not its centre.

## How it was pulled

* The city list and extents come from the Atlas file itself: each city's post-office reference points
  plus its outlets, padded by 0.02° (about 2 km).
* Extents are split into cells of at most 0.5° × 0.5°. Each cell is one Overpass request that runs all 8
  categories. The selectors are read verbatim from `OSM_CATS[].q` in the Atlas HTML.
* Requests go to overpass-api.de one at a time, honouring its slot/rate status, with retries. The pull is
  resumable: every finished cell is saved, and a re-run skips it.

## Refreshing the data

```bash
node tools/city_extents.js <Atlas.html> cities.json      # only if cities changed
python tools/pull_osm.py <Atlas.html>                    # writes raw/<slug>__<cell>.json (resumable)
python tools/build_osm.py osm-data                       # packages raw/ -> osm-data/
git add osm-data && git commit -m "Refresh OSM data" && git push
```

Run all three from one working folder, with `pull_osm.py`, `build_osm.py` and `cities.json` side by side.

**Then update the Atlas.** It fetches from a pinned commit, not from `main`:

```js
const OSM_DATA={base:'https://raw.githubusercontent.com/Alok056-NT/Alok-Atlas-repo/',ref:'<commit SHA>',dir:'osm-data'};
```

Paste the new commit SHA into `ref`, then Save page / re-host. A commit URL never changes, so the
raw.githubusercontent.com CDN cache can never serve a half-updated mix of old and new files. The page
switches to the new data at the exact moment its `ref` changes.

Data © OpenStreetMap contributors, available under the Open Database License (ODbL).
