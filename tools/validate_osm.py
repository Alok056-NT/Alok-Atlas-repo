"""Validate the packaged osm-data/ against the Atlas: every CLUSTER_REF city present, every file parses,
all 8 categories present, every empty category has a logged reason, every geometry well-formed and
inside (or adjacent to) its city extent, per-category totals and file sizes."""
import json, os, sys, collections, re, subprocess
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'repo', 'osm-data')
ORDER = ['commercial', 'retail', 'industrial', 'education', 'hospital', 'bus', 'railway', 'metro']
cities = json.load(open(os.path.join(HERE, 'cities.json'), encoding='utf-8'))
idx = json.load(open(os.path.join(DATA, 'index.json'), encoding='utf-8'))
problems = []; totals = collections.Counter(); empties = collections.Counter(); sizes = []; kinds = collections.Counter()
empty_list = collections.defaultdict(list)
missing = [c['city'] for c in cities if c['city'] not in idx['cities']]
if missing: problems.append('index missing cities: %s' % missing)
for c in cities:
    fn = os.path.join(DATA, c['slug'] + '.json')
    if not os.path.exists(fn):
        problems.append('missing file ' + fn); continue
    sizes.append((os.path.getsize(fn), c['city']))
    d = json.load(open(fn, encoding='utf-8'))
    if d.get('v') != 1 or d.get('city') != c['city']: problems.append('bad header ' + c['city'])
    s, w, n, e = d['bbox']; pad = 1.0
    for k in ORDER:
        if k not in d['f']: problems.append('%s missing category %s' % (c['city'], k)); continue
        arr = d['f'][k]
        if d['counts'][k] != len(arr): problems.append('%s %s count mismatch' % (c['city'], k))
        if not arr:
            empties[k] += 1; empty_list[k].append(c['city'])
            if k not in d.get('empty', {}): problems.append('%s %s empty without reason' % (c['city'], k))
        ids = set()
        for f in arr:
            fid, tags, g = f
            if fid in ids: problems.append('%s %s duplicate id %s' % (c['city'], k, fid))
            ids.add(fid)
            if not re.match(r'^[nwr]\d+$', fid): problems.append('bad id ' + fid)
            if isinstance(g[0], (int, float)):
                kinds[k + ':point'] += 1
                pts = [g]
            else:
                kinds[k + ':area'] += 1
                pts = []
                for ring in g:
                    if len(ring) < 8 or len(ring) % 2 or ring[0] != ring[-2] or ring[1] != ring[-1]:
                        problems.append('%s %s %s bad ring' % (c['city'], k, fid)); break
                    pts += [(ring[i], ring[i + 1]) for i in range(0, len(ring), 2)]
            if not any(s - pad <= p[0] <= n + pad and w - pad <= p[1] <= e + pad for p in pts):
                problems.append('%s %s %s far outside city extent' % (c['city'], k, fid))
        totals[k] += len(arr)
print('cities in index:', len(idx['cities']), '/ expected', len(cities))
print('features by category:', dict(totals), '| total', sum(totals.values()))
print('points/areas:', dict(kinds))
print('cities with 0 features per category (query succeeded, nothing tagged in OSM):', dict(empties))
for k in ORDER:
    if empty_list[k]: print('   ', k, '->', ', '.join(empty_list[k][:40]) + (' …' if len(empty_list[k]) > 40 else ''))
sizes.sort(reverse=True)
print('largest files (MB):', [(n, round(b / 1e6, 2)) for b, n in sizes[:10]])
print('all-in MB: %.2f | median file KB: %.0f | index KB: %.0f' % (sum(b for b, _ in sizes) / 1e6, sizes[len(sizes) // 2][0] / 1e3, os.path.getsize(os.path.join(DATA, 'index.json')) / 1e3))
print('PROBLEMS:', len(problems)); [print(' -', p) for p in problems[:30]]
