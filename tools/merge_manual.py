"""Merge hand-added Atlas places (tools/manual_features.json) into the packaged osm-data/ files.

A manual place is skipped when OpenStreetMap already has it: an education feature within 300 m that
shares a distinctive name word (generic words like "college", "faculty", "university", "baroda" don't
count), or one within 40 m with the same normalised name. Everything else is added to its city's file
as id "m<n>" with tags {name, amenity} so the Atlas treats it exactly like an OSM feature
(amenity is inferred from the name: university / college / school). A place outside every city extent
goes to the nearest city's file and that city's bbox is widened to include it.
Idempotent: previously merged "m" records are removed first, so re-running never duplicates.
usage: python merge_manual.py [osm-data dir] [manual_features.json]
"""
import json, os, sys, math, re, datetime, collections

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, 'repo', 'osm-data')
MANUAL = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, 'repo', 'tools', 'manual_features.json')
GENERIC = set('the and of for in at to school schools college colleges university universities institute institutes '
              'faculty technology engineering management medical commerce arts science sciences research centre center campus deemed '
              'be vidyalaya vidyapeeth vishwavidyalaya public private government govt polytechnic pharmacy law studies hotel '
              'education educational academy baroda vadodara gujarat msu maharaja sayajirao bhubaneswar odisha dehradun india smt shri '
              'sri girls boys college'.split())


def hav(a, b, c, d):
    t = math.radians
    h = math.sin(t(c - a) / 2) ** 2 + math.cos(t(a)) * math.cos(t(c)) * math.sin(t(d - b) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def norm(s):
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9 ]', ' ', (s or '').lower())).strip()


def distinct(s):
    return {w for w in norm(s).split() if len(w) > 2 and w not in GENERIC}


def amenity_for(name):
    n = norm(name)
    if re.search(r'universit|vishwavidyalaya|vidyapeeth|deemed', n):
        return 'university'
    if re.search(r'college|institute|polytechnic|campus|faculty|pharmacy|management|law|medical|engineering|technology', n):
        return 'college'
    return 'school'


def centre(g):
    if isinstance(g[0], (int, float)):
        return g[0], g[1]
    r = g[0]
    return sum(r[0::2]) / (len(r) // 2), sum(r[1::2]) / (len(r) // 2)


def main():
    idx = json.load(open(os.path.join(DATA, 'index.json'), encoding='utf-8'))
    manual = json.load(open(MANUAL, encoding='utf-8'))
    files = {}
    def city_file(city):
        if city not in files:
            files[city] = json.load(open(os.path.join(DATA, idx['cities'][city]['slug'] + '.json'), encoding='utf-8'))
        return files[city]
    # drop earlier merges (idempotent) in every city file that has any
    for city, v in idx['cities'].items():
        if v['counts'].get('education_manual'):
            d = city_file(city)
            d['f']['education'] = [f for f in d['f']['education'] if not f[0].startswith('m')]
    report = []; added = collections.Counter(); seq = 0
    for m in manual:
        seq += 1
        lat, lon, name = m['lat'], m['lon'], m['name']
        inside = [c for c, v in idx['cities'].items() if v['bbox'][0] <= lat <= v['bbox'][2] and v['bbox'][1] <= lon <= v['bbox'][3]]
        # existing OSM education features nearby (any city file whose bbox is within ~2 km)
        near = []
        for c, v in idx['cities'].items():
            b = v['bbox']
            if b[0] - .02 <= lat <= b[2] + .02 and b[1] - .02 <= lon <= b[3] + .02:
                for f in city_file(c)['f']['education']:
                    if f[0].startswith('m'):
                        continue
                    fl, fo = centre(f[2])
                    dd = hav(lat, lon, fl, fo)
                    if dd <= 300:
                        near.append((dd, f[1].get('name') or f[1].get('name:en') or ''))
        near.sort()
        dm = distinct(name)
        nn = norm(name)
        match = next(((dd, n) for dd, n in near if dm & distinct(n)), None) or \
                next(((dd, n) for dd, n in near if norm(n) == nn), None) or \
                next(((dd, n) for dd, n in near if dd <= 60 and norm(n) and (norm(n) in nn or nn in norm(n))), None)
        if match:
            report.append({'name': name, 'status': 'already in OSM', 'match': match[1], 'distance_m': round(match[0])})
            continue
        if inside:
            # the city whose extent centre is closest (extents overlap near city edges)
            city = min(inside, key=lambda c: hav(lat, lon, (idx['cities'][c]['bbox'][0] + idx['cities'][c]['bbox'][2]) / 2, (idx['cities'][c]['bbox'][1] + idx['cities'][c]['bbox'][3]) / 2))
            widened = False
        else:
            city = min(idx['cities'], key=lambda c: hav(lat, lon, (idx['cities'][c]['bbox'][0] + idx['cities'][c]['bbox'][2]) / 2, (idx['cities'][c]['bbox'][1] + idx['cities'][c]['bbox'][3]) / 2))
            widened = True
        d = city_file(city)
        rec = ['m%d' % seq, {'name': name, 'amenity': amenity_for(name)}, [round(lat, 5), round(lon, 5)]]
        d['f']['education'].append(rec)
        if widened:
            pad = 0.01
            b = d['bbox']
            d['bbox'] = [round(min(b[0], lat - pad), 4), round(min(b[1], lon - pad), 4), round(max(b[2], lat + pad), 4), round(max(b[3], lon + pad), 4)]
        added[city] += 1
        report.append({'name': name, 'status': 'added', 'city': city, 'amenity': rec[1]['amenity'], 'widened_city_extent': widened})
    now = datetime.datetime.utcnow().replace(microsecond=0).isoformat() + 'Z'
    for city, d in files.items():
        manual_n = sum(1 for f in d['f']['education'] if f[0].startswith('m'))
        d['counts']['education'] = len(d['f']['education'])
        if manual_n:
            d['counts']['education_manual'] = manual_n
            d['manual_merged'] = now
            d['empty'].pop('education', None)
        else:
            d['counts'].pop('education_manual', None); d.pop('manual_merged', None)
        txt = json.dumps(d, ensure_ascii=False, separators=(',', ':'))
        open(os.path.join(DATA, d['slug'] + '.json'), 'w', encoding='utf-8').write(txt)
        v = idx['cities'][city]; v['counts'] = d['counts']; v['bbox'] = d['bbox']; v['bytes'] = len(txt.encode('utf-8'))
    idx['totals']['education'] = sum(v['counts']['education'] for v in idx['cities'].values())
    idx['manual_merged'] = now
    json.dump(idx, open(os.path.join(DATA, 'index.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
    json.dump(report, open(os.path.join(HERE, 'manual_merge_report.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('manual places:', len(manual), '| already in OSM:', sum(r['status'] != 'added' for r in report), '| added:', sum(added.values()), dict(added))
    for r in report:
        print('  %-14s %-58s %s' % (r['status'], r['name'][:58], ('~ "%s" %dm' % (r['match'], r['distance_m'])) if r['status'] != 'added' else (r['city'] + ' (' + r['amenity'] + ')' + (' [extent widened]' if r['widened_city_extent'] else ''))))


if __name__ == '__main__':
    main()
