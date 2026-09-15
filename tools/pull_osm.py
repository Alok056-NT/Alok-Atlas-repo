"""Bulk-pull OSM features for every Outlet Atlas city, resumable.

For each city (cities.json: slug + padded bbox built from the city's PO reference points and outlets)
the bbox is split into cells of at most CELL degrees per side. Each cell is ONE Overpass request that
runs all 8 OSM_CATS selector sets, each preceded by a `make cat name=<key>` marker element so the
response can be split back into categories. The selector strings (`q` arrays) are read straight out of
the Atlas HTML so they are exactly the app's own definitions.

Area categories (commercial/retail/industrial) are output with `out tags geom` (outlines are kept, then
simplified in build_osm.py); point categories with `out tags center`.

Raw cell responses are written to raw/<slug>__<cell>.json only after a complete, parsed response
(tmp file + rename), so a re-run skips finished cells and a crash never leaves a half file behind.
"""
import json, os, re, sys, time, math, urllib.request, urllib.parse, urllib.error, datetime

HERE = os.path.dirname(os.path.abspath(__file__))
HTML = sys.argv[1] if len(sys.argv) > 1 else None
RAW = os.path.join(HERE, 'raw'); os.makedirs(RAW, exist_ok=True)
LOG = os.path.join(HERE, 'progress.log')
CELL = 0.5
PRIMARY = 'https://overpass-api.de/api/interpreter'
STATUS = 'https://overpass-api.de/api/status'
FALLBACK = 'https://overpass.private.coffee/api/interpreter'
UA = 'OutletAtlas-OSM-bulk/1.0 (one-off bulk pull, sequential, paced)'


def log(msg):
    line = datetime.datetime.now().strftime('%H:%M:%S') + ' ' + msg
    print(line, flush=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def read_cats(html_path):
    src = open(html_path, encoding='utf-8').read()
    block = re.search(r'const OSM_CATS=\[([\s\S]*?)\n\];', src).group(1)
    cats = []
    for m in re.finditer(r"\{key:'(\w+)',label:'[^']*',color:'[^']*',area:(true|false),\s*q:\[(.*?)\],\s*match:", block):
        qs = re.findall(r"'((?:[^'\\]|\\.)*)'", m.group(3))
        cats.append({'key': m.group(1), 'area': m.group(2) == 'true', 'q': qs})
    assert len(cats) == 8 and all(c['q'] and all(s.startswith(('nwr[', 'node[')) for s in c['q']) for c in cats), cats
    return cats


def cells_for(bbox):
    s, w, n, e = bbox
    ny = max(1, math.ceil((n - s) / CELL)); nx = max(1, math.ceil((e - w) / CELL))
    out = []
    for i in range(ny):
        for j in range(nx):
            out.append([round(s + (n - s) * i / ny, 5), round(w + (e - w) * j / nx, 5),
                        round(s + (n - s) * (i + 1) / ny, 5), round(w + (e - w) * (j + 1) / nx, 5)])
    return out


def build_query(cats, cell):
    bb = ','.join(str(x) for x in cell)
    parts = ['[out:json][timeout:600][maxsize:1073741824];']
    for c in cats:
        sels = ''.join(sel + '(' + bb + ');' for sel in c['q'])
        parts.append('make cat name="%s";out;' % c['key'])
        parts.append('(' + sels + ');out tags ' + ('geom' if c['area'] else 'center') + ';')
    return '\n'.join(parts)


def slots_free():
    try:
        t = urllib.request.urlopen(urllib.request.Request(STATUS, headers={'User-Agent': UA}), timeout=30).read().decode()
        if 'slots available now' in t:
            return 0
        waits = [int(x) for x in re.findall(r'in (\d+) seconds', t)]
        return min(waits) if waits else 15
    except Exception:
        return 15


def post(ep, q, timeout=900):
    req = urllib.request.Request(ep, data=urllib.parse.urlencode({'data': q}).encode(), headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    d = json.loads(body)
    if d.get('remark') and ('runtime error' in d['remark'] or 'Timeout' in d['remark'] or 'out of memory' in d['remark']):
        raise RuntimeError('overpass remark: ' + d['remark'][:200])
    return d, len(body)


def main():
    cats = read_cats(HTML)
    cities = json.load(open(os.path.join(HERE, 'cities.json'), encoding='utf-8'))
    only = set(sys.argv[2].split(',')) if len(sys.argv) > 2 else None
    todo = []
    for c in cities:
        if only and c['slug'] not in only and c['city'] not in only:
            continue
        for k, cell in enumerate(cells_for(c['bbox'])):
            todo.append((c, k, cell))
    if os.environ.get('PULL_REVERSE'):
        todo.reverse()
    log('cells total %d%s' % (len(todo), ' (reverse order)' if os.environ.get('PULL_REVERSE') else ''))
    done = 0
    for c, k, cell in todo:
        fn = os.path.join(RAW, '%s__%d.json' % (c['slug'], k))
        if os.path.exists(fn):
            done += 1
            continue
        q = build_query(cats, cell)
        attempt = 0
        while True:
            attempt += 1
            if os.path.exists(fn):
                log('SKIP %s cell %d (saved by the other worker)' % (c['city'], k)); done += 1
                break
            ep = PRIMARY if attempt <= 6 else FALLBACK
            if ep == PRIMARY:
                w = slots_free()
                if w:
                    time.sleep(min(w, 120) + 1)
            t0 = time.time()
            try:
                d, nbytes = post(ep, q)
                markers = [e['tags']['name'] for e in d['elements'] if e.get('type') == 'cat']
                if markers != [c2['key'] for c2 in cats]:
                    raise RuntimeError('incomplete response, markers=%s' % markers)
                d['_meta'] = {'city': c['city'], 'slug': c['slug'], 'cell': cell, 'endpoint': ep,
                              'fetched': datetime.datetime.utcnow().isoformat() + 'Z'}
                tmp = fn + '.%d.tmp' % os.getpid()
                with open(tmp, 'w', encoding='utf-8') as f:
                    json.dump(d, f, ensure_ascii=False, separators=(',', ':'))
                os.replace(tmp, fn)
                done += 1
                log('OK %s cell %d  %d els  %.1f MB  %.1fs  (%d/%d)%s' % (
                    c['city'], k, len(d['elements']) - 8, nbytes / 1e6, time.time() - t0, done, len(todo),
                    '' if ep == PRIMARY else '  [fallback endpoint]'))
                time.sleep(2)
                break
            except Exception as ex:
                msg = str(ex)[:200]
                wait = min(300, 20 * attempt)
                log('RETRY %s cell %d attempt %d (%s) via %s — waiting %ds' % (c['city'], k, attempt, msg, ep, wait))
                if attempt >= 10:
                    log('FAILED %s cell %d — giving up for this run (re-run to retry)' % (c['city'], k))
                    break
                time.sleep(wait)
    log('finished run: %d/%d cells present' % (done, len(todo)))


if __name__ == '__main__':
    main()
