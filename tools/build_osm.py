"""Package raw Overpass cell responses (raw/<slug>__<cell>.json) into one JSON per city:
osm-data/<slug>.json plus osm-data/index.json.

City file format (v1):
{
  "v": 1, "city": "Pune", "slug": "pune", "bbox": [s, w, n, e],
  "osm_base": "<Overpass data timestamp>", "built": "<UTC ISO>",
  "counts": {"commercial": n, ...},            # features per category
  "empty": {"metro": "no OSM features tagged for this category inside the city extent"},
  "f": {"commercial": [[id, tags, geom], ...], ...}
}
  id   : "n123" / "w123" / "r123"  (OSM type letter + id)
  tags : only the keys the Atlas reads: name, name:en and the tag keys used by OSM_CATS[].match
  geom : point -> [lat, lon]
         area  -> [[lat,lon,lat,lon,...], ...]   one flat closed ring per outline (outer rings only)
Area categories keep their outlines, simplified with Douglas-Peucker (SIMPLIFY_DEG) and rounded to
5 decimals (~1 m); nothing tagged as an area is reduced to a centroid unless it has no usable ring.
"""
import json, os, re, glob, datetime, sys, collections

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, 'raw')
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'repo', 'osm-data')
os.makedirs(OUT, exist_ok=True)
AREA = {'commercial', 'retail', 'industrial'}
ORDER = ['commercial', 'retail', 'industrial', 'education', 'hospital', 'bus', 'railway', 'metro']
KEEP = ('name', 'name:en', 'landuse', 'office', 'shop', 'amenity', 'highway', 'railway', 'station')
SIMPLIFY_DEG = 0.00002   # ~2 m
R5 = lambda x: round(x, 5)


def dp(pts, tol):
    """Douglas-Peucker on [(lat,lon),...] (iterative)."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts); keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = pts[a]; bx, by = pts[b]
        dx, dy = bx - ax, by - ay; L2 = dx * dx + dy * dy
        best, bi = -1, -1
        for i in range(a + 1, b):
            px, py = pts[i]
            if L2 == 0:
                d = (px - ax) ** 2 + (py - ay) ** 2
            else:
                t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / L2))
                d = (px - ax - t * dx) ** 2 + (py - ay - t * dy) ** 2
            if d > best:
                best, bi = d, i
        if bi >= 0 and best > tol * tol:
            keep[bi] = True
            stack.append((a, bi)); stack.append((bi, b))
    return [p for p, k in zip(pts, keep) if k]


def ring_out(pts):
    """Close, simplify and flatten one ring; None if it can't form a polygon."""
    pts = [(R5(a), R5(b)) for a, b in pts]
    dedup = [pts[0]]
    for p in pts[1:]:
        if p != dedup[-1]:
            dedup.append(p)
    pts = dedup
    if len(pts) < 3:
        return None
    if pts[0] != pts[-1]:
        pts = pts + [pts[0]]
    s = dp(pts, SIMPLIFY_DEG)
    if len(s) < 4:           # simplification collapsed a tiny ring: keep the (rounded) original
        s = pts
    if len(s) < 4:
        return None
    flat = []
    for a, b in s:
        flat += [a, b]
    return flat


def assemble(ways):
    """Join relation member ways (lists of (lat,lon)) end-to-end into rings. Unclosed leftovers are
    returned as-is (closed later), mirroring the live renderer which closes each outline itself."""
    ways = [list(w) for w in ways if len(w) >= 2]
    rings = []
    while ways:
        cur = ways.pop(0)
        changed = True
        while cur[0] != cur[-1] and changed:
            changed = False
            for i, w in enumerate(ways):
                if w[0] == cur[-1]:
                    cur += w[1:]
                elif w[-1] == cur[-1]:
                    cur += w[::-1][1:]
                elif w[-1] == cur[0]:
                    cur = w[:-1] + cur
                elif w[0] == cur[0]:
                    cur = w[::-1][:-1] + cur
                else:
                    continue
                ways.pop(i); changed = True
                break
        rings.append(cur)
    return rings


def tags_of(e):
    t = e.get('tags') or {}
    return {k: t[k] for k in KEEP if k in t}


def feature(cat, e):
    fid = e['type'][0] + str(e['id'])
    tags = tags_of(e)
    if e['type'] == 'node':
        return [fid, tags, [R5(e['lat']), R5(e['lon'])]]
    if cat not in AREA:
        c = e.get('center')
        if not c and e.get('bounds'):
            b = e['bounds']; c = {'lat': (b['minlat'] + b['maxlat']) / 2, 'lon': (b['minlon'] + b['maxlon']) / 2}
        if not c and e.get('geometry'):
            g = [x for x in e['geometry'] if x]; c = {'lat': sum(x['lat'] for x in g) / len(g), 'lon': sum(x['lon'] for x in g) / len(g)}
        return [fid, tags, [R5(c['lat']), R5(c['lon'])]] if c else None
    rings = []
    if e['type'] == 'way' and e.get('geometry'):
        ll = [(g['lat'], g['lon']) for g in e['geometry'] if g]
        if len(ll) > 2:
            r = ring_out(ll)
            if r:
                rings.append(r)
        elif ll:
            return [fid, tags, [R5(sum(p[0] for p in ll) / len(ll)), R5(sum(p[1] for p in ll) / len(ll))]]
    elif e['type'] == 'relation':
        outer = [[(g['lat'], g['lon']) for g in m['geometry'] if g] for m in e.get('members', [])
                 if m.get('type') == 'way' and m.get('geometry') and m.get('role') in ('outer', '', None)]
        for ring in assemble(outer):
            if len(ring) > 2:
                r = ring_out(ring)
                if r:
                    rings.append(r)
    if rings:
        return [fid, tags, rings]
    b = e.get('bounds')
    if b:
        return [fid, tags, [R5((b['minlat'] + b['maxlat']) / 2), R5((b['minlon'] + b['maxlon']) / 2)]]
    return None


def main():
    cities = json.load(open(os.path.join(HERE, 'cities.json'), encoding='utf-8'))
    index = {'v': 1, 'built': datetime.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z', 'cities': {}}
    totals = collections.Counter(); missing = []
    for c in cities:
        files = sorted(glob.glob(os.path.join(RAW, c['slug'] + '__*.json')),
                       key=lambda p: int(re.search(r'__(\d+)\.json$', p).group(1)))
        from pull_osm import cells_for
        need = len(cells_for(c['bbox']))
        if len(files) != need:
            missing.append((c['city'], len(files), need))
            continue
        feats = {k: {} for k in ORDER}; base = None
        for fn in files:
            d = json.load(open(fn, encoding='utf-8'))
            base = base or d.get('osm3s', {}).get('timestamp_osm_base')
            cur = None
            for e in d['elements']:
                if e['type'] == 'cat':
                    cur = e['tags']['name']; continue
                key = e['type'][0] + str(e['id'])
                if key in feats[cur]:
                    continue
                f = feature(cur, e)
                if f:
                    feats[cur][key] = f
        out = {'v': 1, 'city': c['city'], 'slug': c['slug'], 'bbox': c['bbox'], 'osm_base': base,
               'built': index['built'], 'counts': {k: len(feats[k]) for k in ORDER}, 'empty': {},
               'f': {k: list(feats[k].values()) for k in ORDER}}
        for k in ORDER:
            if not feats[k]:
                out['empty'][k] = 'no OSM features tagged for this category inside the city extent (query succeeded, 0 results)'
            totals[k] += len(feats[k])
        txt = json.dumps(out, ensure_ascii=False, separators=(',', ':'))
        with open(os.path.join(OUT, c['slug'] + '.json'), 'w', encoding='utf-8') as f:
            f.write(txt)
        index['cities'][c['city']] = {'slug': c['slug'], 'bbox': c['bbox'], 'counts': out['counts'],
                                      'bytes': len(txt.encode('utf-8'))}
    index['totals'] = dict(totals)
    with open(os.path.join(OUT, 'index.json'), 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, separators=(',', ':'))
    print('built', len(index['cities']), 'cities; missing', len(missing), missing[:10])
    print('totals', dict(totals), 'sum', sum(totals.values()))
    sizes = sorted(((v['bytes'], k) for k, v in index['cities'].items()), reverse=True)
    if sizes:
        print('largest', [(k, round(b / 1e6, 2)) for b, k in sizes[:8]], 'all-in MB', round(sum(b for b, _ in sizes) / 1e6, 2))


if __name__ == '__main__':
    main()
