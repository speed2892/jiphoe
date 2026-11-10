"""jw.org 공식 다운로드(EPUB)에서 이번 주와 다음 몇 주의
집회 교재·파수대 연구 기사·성경 읽기 범위를 글로 바꿔, 나만 보는 비공개 Gist에 넣는다.
앱(집회 준비)은 열릴 때 이 Gist 파일(jw-weekly.json)을 읽어 자동으로 채운다.

환경 변수: JW_GIST_TOKEN (gist 권한 토큰), WEEKS (몇 주 받을지, 기본 4)
공개 저장소에는 아무 내용도 남기지 않는다(로그에는 파일 이름과 글자 수만 찍는다).
"""
import io, json, os, re, sys, zipfile, datetime as dt
from html.parser import HTMLParser
import urllib.request, urllib.parse

KST = dt.timezone(dt.timedelta(hours=9))
API = 'https://b.jw-cdn.org/apis/pub-media/GETPUBMEDIALINKS?output=json&pub={pub}{issue}&fileformat=EPUB&alllangs=0&langwritten=KO&txtCMSLang=KO'
GIST_DESC, GIST_FILE = 'jiphoe-hub-sync', 'jw-weekly.json'
UA = {'User-Agent': 'Mozilla/5.0 (jiphoe weekly)'}

def get(url, data=None, headers=None, method=None):
    req = urllib.request.Request(url, data=data, headers={**UA, **(headers or {})}, method=method)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()

_cache = {}
_titles = {}
def week_titles(pub, issue):
    """주별 RTF 파일 제목 목록 (예: '11월 9-15일 (예레미야 51-52장)') — 성경 읽기 범위를 알아내는 데 쓴다"""
    key = (pub, issue)
    if key not in _titles:
        try:
            j = json.loads(get(API.format(pub=pub, issue=f'&issue={issue}').replace('fileformat=EPUB', 'fileformat=RTF')))
            _titles[key] = [x.get('title', '') for x in j['files']['KO']['RTF']]
        except Exception: _titles[key] = []
    return _titles[key]

RANGE = re.compile(r'([가-힣]+(?:\s[가-힣]+)?\s\d{1,3}(?:\s*[-–]\s*\d{1,3})?\s*장)')
def epub(pub, issue=''):
    key = (pub, issue)
    if key in _cache: return _cache[key]
    try:
        j = json.loads(get(API.format(pub=pub, issue=f'&issue={issue}' if issue else '')))
        url = j['files']['KO']['EPUB'][0]['file']['url']
        z = zipfile.ZipFile(io.BytesIO(get(url)))
        print(f'  받음: {pub} {issue}'.rstrip())
    except Exception as e:
        print(f'  없음: {pub} {issue} ({e.__class__.__name__})'); z = None
    _cache[key] = z
    return z

def spine(z):
    """책 순서대로 xhtml 이름 목록"""
    opf = next(n for n in z.namelist() if n.endswith('.opf'))
    base = opf.rsplit('/', 1)[0] + '/' if '/' in opf else ''
    s = z.read(opf).decode('utf-8')
    items = dict(re.findall(r'<item[^>]*?id="([^"]+)"[^>]*?href="([^"]+)"', s))
    items.update({a: b for b, a in re.findall(r'<item[^>]*?href="([^"]+)"[^>]*?id="([^"]+)"', s)})
    order = re.findall(r'<itemref[^>]*idref="([^"]+)"', s)
    return [base + items[i] for i in order if i in items and items[i].endswith(('.xhtml', '.html'))]

BLOCK = {'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'dt', 'dd', 'figcaption', 'td', 'th', 'header', 'title'}
class Text(HTMLParser):
    """블록마다 한 줄. 같은 data-pid 문단(성경 시 구절)은 한 줄로 잇는다. 각주 표시(*)는 뺀다."""
    def __init__(self):
        super().__init__(); self.blocks = []; self.cur = None; self.skip = 0; self.pid = None; self.title = ''; self.in_title = False
    def handle_starttag(self, tag, a):
        a = dict(a)
        if tag == 'title': self.in_title = True; return
        if self.skip: self.skip += 1 if tag not in ('br', 'img') else 0; return
        if tag == 'a' and 'noteref' in (a.get('epub:type') or ''): self.skip = 1; return
        if 'w_navigation' in (a.get('class') or ''): self.skip = 1; return
        if tag in BLOCK:
            pid = a.get('data-pid')
            if pid and pid == self.pid and self.blocks: self.cur = self.blocks[-1]; self.cur.append(' ')
            else: self.cur = []; self.blocks.append(self.cur)
            self.pid = pid
        elif tag == 'br' and self.cur is not None: self.cur.append('\n')
        elif tag == 'sup' and self.cur and ''.join(self.cur).strip(): self.cur.append('\n')   # 성경: 절 번호마다 새 줄
    def handle_endtag(self, tag):
        if tag == 'title': self.in_title = False; return
        if self.skip:
            if tag not in ('br', 'img'): self.skip -= 1
            return
        if tag in BLOCK: self.cur = None
    def handle_data(self, d):
        if self.in_title: self.title += d; return
        if self.skip: return
        if self.cur is None: self.cur = []; self.blocks.append(self.cur); self.pid = None
        self.cur.append(d)
    def lines(self):
        out = []
        for b in self.blocks:
            t = re.sub(r'[ \t ]+', ' ', ''.join(b)).strip()
            if t: out.append(t)
        return out

def doc(z, name):
    p = Text(); p.feed(z.read(name).decode('utf-8', 'replace')); return p

def citations(z, name, limit=12000):
    """EPUB 안의 '-extracted.xhtml'에 들어 있는 출판물 참조 본문(JW Library가 오프라인에서 보여 주는 것)을 꺼낸다.
       반환: [{ref:'「파17.10」 23면 9-10항', text:'…'}]"""
    ext = re.sub(r'\.xhtml$', '-extracted.xhtml', name)
    if ext not in z.namelist(): return []
    main = z.read(name).decode('utf-8', 'replace')
    labels = {}
    for m in re.finditer(r'<a [^>]*href="[^"]*#(pcitation\d+)"[^>]*>(.*?)</a>', main, re.S):
        labels[m[1]] = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', m[2])).strip()
    last = ''
    for cid in sorted(labels, key=lambda x: int(x[9:])):       # '167면 25항' 처럼 약호가 빠진 링크는 앞 링크의 「약호」를 붙인다
        m = re.match(r'(「[^」]+」)', labels[cid])
        if m: last = m[1]
        elif last and re.match(r'\d', labels[cid]): labels[cid] = f'{last} {labels[cid]}'
    body = z.read(ext).decode('utf-8', 'replace')
    parts = re.split(r'<span id="(pcitation\d+)"\s*>', body)
    out = []
    for k in range(1, len(parts) - 1, 2):
        cid, seg = parts[k], parts[k + 1]
        p = Text(); p.feed('<div><p>' + seg); t = '\n\n'.join(l for l in p.lines() if l != '^')
        t = re.sub(r'^\^\s*', '', t).strip()
        if t: out.append({'ref': labels.get(cid, cid), 'text': t[:limit]})
    return out

def md(d): return (d.month, d.day)

def find_workbook(monday):
    """이번 주 집회 교재: 첫 줄이 'M월 D-…일' 로 시작하는 문서"""
    y, m = monday.year, monday.month
    issues = []
    for k in range(0, 4):                     # 홀수 달 발행(격월). 해당 달·앞 호까지 찾아본다
        mm, yy = m - k, y
        while mm < 1: mm += 12; yy -= 1
        if mm % 2 == 1: issues.append(f'{yy}{mm:02d}')
    for iss in issues:
        z = epub('mwb', iss)
        if not z: continue
        for n in spine(z):
            ls = doc(z, n).lines()
            head = ' '.join(ls[:2])
            mt = re.match(r'\s*(\d{1,2})월\s*(\d{1,2})일?\s*[-–~]', head)
            if mt and (int(mt[1]), int(mt[2])) == md(monday) and any('성경에 담긴 보물' in l for l in ls):
                rng = ''
                for t in week_titles('mwb', iss):
                    t2 = re.match(r'\s*(\d{1,2})월\s*(\d{1,2})', t)
                    if t2 and (int(t2[1]), int(t2[2])) == md(monday) and RANGE.search(t): rng = RANGE.search(t)[1]; break
                if not rng:
                    for l in ls[:30]:
                        if RANGE.search(l): rng = RANGE.search(l)[1]; break
                print('  교재 첫 줄:', ' / '.join(x[:24] for x in ls[:5]))
                cites = citations(z, n)
                print(f'  교재 참조 출판물 {len(cites)}개')
                return ls, rng, cites
    return None, '', []

def find_wt(monday):
    """이번 주 파수대 연구 기사: 앞부분에 'YYYY년 M월 D-…일' 이 있는 문서"""
    for k in range(1, 5):                     # 연구 기사는 보통 2달 전 호
        mm, yy = monday.month - k, monday.year
        while mm < 1: mm += 12; yy -= 1
        z = epub('w', f'{yy}{mm:02d}')
        if not z: continue
        for n in spine(z):
            ls = doc(z, n).lines()
            head = ' '.join(ls[:4])
            mt = re.search(r'(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일?\s*[-–~]', head)
            if mt and (int(mt[1]), int(mt[2]), int(mt[3])) == (monday.year, monday.month, monday.day) and len(ls) > 20:
                return ls
    return None

_bible = None
def bible_chapters():
    global _bible
    if _bible is None:
        _bible = {}
        z = epub('nwt')
        if z:
            for n in z.namelist():
                if not n.endswith('.xhtml') or 'extracted' in n: continue
                p = doc(z, n); mt = re.fullmatch(r'\s*(.+?)\s+(\d{1,3})\s*', p.title or '')
                if mt: _bible[(mt[1], int(mt[2]))] = p.lines()
    return _bible

def bible_text(rng):
    """'예레미야 51-52장', '예레미야 애가 3-5장', '에스겔 1장' → [책 N장] 머리 + 절 줄"""
    mt = re.match(r'\s*(.+?)\s+(\d{1,3})(?:\s*[-–]\s*(\d{1,3}))?\s*장', rng)
    if not mt: return None
    book, a, b = mt[1], int(mt[2]), int(mt[3] or mt[2])
    ch = bible_chapters(); out = []
    for c in range(a, b + 1):
        ls = ch.get((book, c))
        if not ls: return None
        out.append(f'[{book} {c}장]'); out.append(book); out.extend(ls)
    return '\n'.join(out)

# 회중 성서 연구 교재: 「약호」 → 출판물 기호 (모르면 jw.org 검색으로 찾는다)
PUB_ABBR = {'용하': 'wcg'}
def pub_code(abbr):
    if abbr in PUB_ABBR: return PUB_ABBR[abbr]
    try:
        tok = get('https://b.jw-cdn.org/tokens/jworg.jwt').decode().strip()
        j = json.loads(get('https://b.jw-cdn.org/apis/search/results/KO/publications?q=' + urllib.parse.quote(abbr) + '&limit=5',
                           headers={'Authorization': 'Bearer ' + tok}))
        items = []
        def walk(n):
            if n.get('type') == 'item': items.append(n)
            for c in n.get('results', []) or []: walk(c)
        walk({'results': j.get('results', [])})
        for it in items:
            lank = it.get('lank', '')
            if lank.startswith('pub-'): PUB_ABBR[abbr] = lank[4:]; return lank[4:]
    except Exception as e: print('  출판물 기호 찾기 실패:', abbr, e.__class__.__name__)
    return None

def find_cbs(wb):
    """교재의 '회중 성서 연구' 순서에서 「약호」 N장(과) 을 찾아 그 장 본문을 가져온다"""
    i = next((k for k, l in enumerate(wb) if '회중 성서 연구' in l), None)
    if i is None: return None
    ref = next((l for l in wb[i:i+4] if '「' in l), '')
    mt = re.search(r'「([^」]+)」\s*(\d{1,3})\s*(장|과)', ref)
    if not mt: print('  회중 성서 연구 참조 못 찾음'); return None
    abbr, num = mt[1], int(mt[2])
    code = pub_code(abbr)
    z = epub(code) if code else None
    if not z: return None
    for n in spine(z):
        p = doc(z, n)
        if re.match(rf'\s*{num}(\s|$)', p.title or '') or re.match(rf'\s*{num}\s*(장|과)', p.title or ''):
            doc = (re.search(r'(\d{7,})\.x?html$', n) or [None, ''])[1]
            cites = citations(z, n)
            print(f'  회중 성서 연구 {abbr} {num}장 (문서 {doc}) 참조 {len(cites)}개')
            return {'ref': (re.search(r'「[^」]+」[^(]*', ref) or [ref])[0].strip(), 'title': (p.title or '').strip(), 'text': '\n\n'.join(p.lines()), 'cites': cites, 'doc': doc}
    print('  회중 성서 연구 장을 못 찾음:', abbr, num); return None

def safe(s): return re.sub(r'[\\/:*?"<>|“”‘’]', '', s).strip()[:60]

# ---------- 요청한 출판물 면 가져오기 (연구 자료 찾아보기의 「파수대」 2008/6/15, 8-9면 · 「통찰」 제1권 785면 등) ----------
REQ_FILE, REF_FILE = 'jw-requests.json', 'jw-refs.json'
PERIODICAL = {'파수대': 'w', '파': 'w', '깨어라!': 'g', '깨': 'g', '깨어라': 'g'}

def resolve(ref):
    """참조 표기 → (출판물 기호, 호, [면들])"""
    r = ref.replace(' ', ' ')
    pages = []
    pm = re.search(r'(\d{1,4})(?:\s*-\s*(\d{1,4}))?\s*면', r)
    if pm:
        a = int(pm[1]); b = int(pm[2] or pm[1]); pages = list(range(a, min(b, a + 6) + 1))
    m = re.search(r'「([^」]+)」', r)
    if not m or not pages: return None, None, pages
    ab = m[1].strip(); rest = r[m.end():]
    # 「파수대」 2008/6/15 · 「깨어라!」 2010/5
    mm = re.match(r'(파수대|깨어라!?)$', ab)
    if mm:
        d = re.search(r'(\d{4})\s*/\s*(\d{1,2})(?:\s*/\s*(\d{1,2}))?', rest)
        if d: return PERIODICAL[mm[1]], f'{d[1]}{int(d[2]):02d}' + (f'{int(d[3]):02d}' if d[3] else ''), pages
    # 「파15」 8/1 · 「파17.10」 · 「깨10」 5/8
    mm = re.match(r'(파|깨)(\d{2})(?:\.(\d{1,2}))?$', ab)
    if mm:
        yy = int(mm[2]); year = 2000 + yy if yy < 50 else 1900 + yy
        if mm[3]: return PERIODICAL[mm[1]], f'{year}{int(mm[3]):02d}', pages
        d = re.match(r'\s*(\d{1,2})\s*/\s*(\d{1,2})', rest)
        if d: return PERIODICAL[mm[1]], f'{year}{int(d[1]):02d}{int(d[2]):02d}', pages
        d = re.match(r'\s*(\d{1,2})\s*월', rest)
        if d: return PERIODICAL[mm[1]], f'{year}{int(d[1]):02d}', pages
    # 「통찰」 제1권 / 제2권
    if ab.startswith('통찰'):
        v = re.search(r'제\s*(\d)\s*권', rest)
        return (f'it-{v[1]}' if v else 'it-1'), '', pages
    return pub_code(ab), '', pages

def pages_text(z, pages, limit=12000):
    """EPUB 안의 면 표시(pageNum)를 따라 해당 면의 글만 꺼낸다"""
    return html_pages(''.join(z.read(n).decode('utf-8', 'replace') for n in spine(z)), pages, limit)

WOL = 'https://wol.jw.org'
_wol = {}
def wol_get(path):
    if path not in _wol:
        _wol[path] = get(WOL + path, headers={'Accept-Language': 'ko', 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36'}).decode('utf-8', 'replace')
    return _wol[path]

def wol_ref(ref, ch, pages, doc=''):
    """연구용 성경 장 페이지(연구 자료 찾아보기) 또는 출판물 문서(doc)에서 그 참조의 링크를 찾아 열고, 해당 면 글을 꺼낸다"""
    page = wol_get(f'/ko/wol/d/r8/lp-ko/{doc}' if doc else f'/ko/wol/b/r8/lp-ko/nwtsty/{ch}')
    links = {}
    for m in re.finditer(r'<a [^>]*href="(/ko/wol/pc/[^"]+)"[^>]*>(.*?)</a>', page, re.S):
        t = re.sub(r'<[^>]+>', '', m[2]); links[m[1]] = (links.get(m[1], '') + ' ' + t).strip()
    key = lambda x: re.sub(r'[\s,]', '', x)
    href = next((h for h, t in links.items() if key(t) == key(ref)), None) or next((h for h, t in links.items() if key(ref) in key(t) or key(t) in key(ref)), None)
    if not href: return ''
    html = wol_get(href)
    body = html[html.find('<article'):] if '<article' in html else html
    return html_pages(body, pages) if pages else ''

def study_verse(key):
    """'24/51/6' → 연구용 성경의 연구 노트·각주·상호 참조·연구 자료 찾아보기(링크를 따라가 해당 면 글까지)"""
    from bs4 import BeautifulSoup
    b, c, v = key.split('/')
    soup = BeautifulSoup(wol_get(f'/ko/wol/b/r8/lp-ko/nwtsty/{b}/{c}'), 'html.parser')
    sec = soup.select_one(f'div.section[data-key="{b}-{c}-{v}"]')
    if not sec: return None
    txt = lambda el: re.sub(r'\s+', ' ', el.get_text(' ', strip=True)).strip()
    notes = [txt(li) for li in sec.select('.studyNoteGroup li.studyNote')]
    foot = [txt(li) for li in sec.select('.group.footnote li')]
    marg = [txt(li).lstrip('+') for li in sec.select('.group.marginal li')]
    rsg_links = {}
    for li in sec.select('.group.index li.ref-rsg'):
        for a in li.select('a[href*="/wol/pc/"]'):
            rsg_links[a['href']] = (rsg_links.get(a['href'], '') + ' ' + txt(a)).strip()
    dx = [txt(li).replace('출판물 색인', '').strip() for li in sec.select('.group.index li.ref-dx')]
    refs = []
    for href, label in list(rsg_links.items())[:6]:
        pm = re.search(r'(\d{1,4})(?:\s*-\s*(\d{1,4}))?\s*면', label)
        pages = list(range(int(pm[1]), min(int(pm[2] or pm[1]), int(pm[1]) + 5) + 1)) if pm else []
        try:
            html = wol_get(href); body = html[html.find('<article'):] if '<article' in html else html
            t = html_pages(body, pages) if pages else ''
            if not t:
                p = Text(); p.feed(body); t = '\n\n'.join(p.lines())[:4000]
        except Exception as e: t = ''
        refs.append({'ref': label, 'text': t, 'ok': bool(t)})
    lines = []
    if notes: lines.append('[연구 노트] ' + ' / '.join(notes))
    if foot: lines.append('[각주] ' + ' / '.join(foot))
    if rsg_links: lines.append('[연구 자료 찾아보기] ' + '; '.join(rsg_links.values()))
    if dx: lines.append('[출판물 색인] ' + '; '.join(dx))
    if marg: lines.append('[상호 참조] ' + ' / '.join(marg))
    return {'notes': '\n'.join(lines) or '(연구 노트 없음)', 'refs': refs}

def html_pages(html, pages, limit=12000):
    segs = re.split(r'<span[^>]*class="pageNum"[^>]*data-no="(\d+)"[^>]*>', html)
    want = set(pages); got = []
    for k in range(1, len(segs) - 1, 2):
        if int(segs[k]) in want: got.append(segs[k + 1])
    # 글이 첫 면 표시 앞에서 시작하면(면 중간에서 시작한 기사) 그 앞부분은 첫 표시 바로 앞 면의 글이다
    if len(segs) > 1 and (int(segs[1]) - 1) in want and re.sub(r'<[^>]+>|\s', '', segs[0]): got.insert(0, segs[0])
    if not got: return ''
    p = Text(); p.feed('<div><p>' + ''.join(got))
    return '\n\n'.join(l for l in p.lines() if l not in ('답을 적는 칸',))[:limit]

def handle_requests(gh, gid, gist):
    files = gist.get('files', {})
    def read(name):
        f = files.get(name)
        if not f: return None
        c = f.get('content') if not f.get('truncated') else get(f['raw_url']).decode()
        try: return json.loads(c)
        except Exception: return None
    reqs = read(REQ_FILE) or []
    have = read(REF_FILE) or {}
    norm = [r if isinstance(r, dict) else {'ref': r} for r in reqs]
    studies = [r['study'] for r in norm if r.get('study') and 'study:' + r['study'] not in have]
    for k in studies[:40]:
        try:
            st = study_verse(k)
            have['study:' + k] = dict(st or {'notes': '', 'refs': []}, ok=bool(st), at=dt.datetime.now(KST).isoformat(timespec='seconds'))
            print(f"  {'✓' if st else '✗'} 연구 노트 {k} · 연구 자료 {len(st['refs']) if st else 0}개")
        except Exception as e:
            have['study:' + k] = {'ok': False, 'err': e.__class__.__name__, 'notes': '', 'refs': []}
            print(f'  ✗ 연구 노트 {k} ({e.__class__.__name__} {getattr(e, "code", "")})')
    todo = [r for r in norm if r.get('ref') and (r['ref'] not in have or (not have[r['ref']].get('ok') and (r.get('ch') or r.get('doc')) and not have[r['ref']].get('wol')))]
    print(f'출판물 면 요청 {len(reqs)}개 (새로 {len(todo)}개)')
    for rq in todo[:30]:
        ref, ch = rq['ref'], rq.get('ch', '')
        try:
            code, issue, pages = resolve(ref)
            z = epub(code, issue) if code else None
            t = pages_text(z, pages) if z else ''
            via = 'epub'
            if not t and (ch or rq.get('doc')):
                try: t = wol_ref(ref, ch, pages, rq.get('doc', '')); via = 'wol'
                except Exception as e: print(f'  wol 실패: {e.__class__.__name__} {getattr(e, "code", "")}')
            have[ref] = {'text': t, 'ok': bool(t), 'pub': code or '', 'issue': issue or '', 'via': via, 'wol': bool(ch or rq.get('doc')), 'at': dt.datetime.now(KST).isoformat(timespec='seconds')}
            print(f"  {'✓' if t else '✗'} {ref[:40]} → {code} {issue} {pages[:3]} {via} {len(t):,}자")
        except Exception as e:
            have[ref] = {'text': '', 'ok': False, 'err': e.__class__.__name__}
            print(f'  ✗ {ref[:40]} ({e.__class__.__name__})')
    if todo or studies:
        gh('/gists/' + gid, {'files': {REF_FILE: {'content': json.dumps(have, ensure_ascii=False)}}}, 'PATCH')
        print('요청한 면을 Gist에 저장했습니다.')

def main():
    token = os.environ.get('JW_GIST_TOKEN', '').strip()
    if not token: sys.exit('JW_GIST_TOKEN 비밀값이 없습니다.')
    mode = os.environ.get('MODE', 'all')
    gh = lambda path, body=None, method=None: json.loads(get('https://api.github.com' + path,
        data=json.dumps(body).encode() if body is not None else None, method=method,
        headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json'}) or b'{}')
    gid = os.environ.get('JW_GIST_ID', '').strip()
    if not gid:
        gists = gh('/gists?per_page=100')
        g = next((g for g in gists if g.get('description') == GIST_DESC), None)
        if not g: sys.exit('동기화 Gist(jiphoe-hub-sync)를 찾지 못했습니다. 앱에서 Gist 동기화를 먼저 연결하세요.')
        gid = g['id']
    gist = gh('/gists/' + gid)
    handle_requests(gh, gid, gist)
    if mode == 'requests': return
    weekly(gh, gid)

def weekly(gh, gid):
    weeks = int(os.environ.get('WEEKS', '4'))
    today = dt.datetime.now(KST).date()
    mon0 = today - dt.timedelta(days=today.weekday())
    files = []
    for i in range(weeks):
        mon = mon0 + dt.timedelta(weeks=i); wid = mon.isoformat()
        print(f'{wid} 주')
        wb, rng, cites = find_workbook(mon)
        if wb:
            label = wb[0].split('(')[0].strip()
            # 앱이 읽기 좋은 모양으로: 첫 줄 주 표시, 둘째 줄 성경 읽기 범위, 그다음 '노래…'부터 본문
            i = next((k for k, l in enumerate(wb) if l.startswith('노래')), 1)
            body = [label] + ([rng] if rng else []) + wb[i:]
            files.append({'name': f'{wid}_집회교재_{safe(label)}.txt', 'text': '\n\n'.join(body)})
            cbs = find_cbs(wb)
            if cbs:
                files.append({'name': f"{wid}_회중성서연구_{safe(cbs['ref'])}_{cbs.get('doc','')}.txt", 'text': f"{cbs['ref']}\n{cbs['title']}\n\n{cbs['text']}"})
                cites = cites + [dict(c, where='cbs') for c in cbs.get('cites', [])]
            if cites:
                files.append({'name': f'{wid}_참조출판물.json', 'text': json.dumps(cites, ensure_ascii=False)})
            bt = bible_text(rng) if rng else None
            if bt: files.append({'name': f'{wid}_성경범위_{safe(rng)}.txt', 'text': bt})
            else: print(f'  성경 범위 못 찾음: {rng!r}')
        else: print('  집회 교재 없음')
        wt = find_wt(mon)
        if wt:
            title = next((l for l in wt[1:6] if not re.match(r'(노래|\d{4}년)', l)), '파수대 연구 기사')
            files.append({'name': f'{wid}_{safe(title)}.txt', 'text': '\n\n'.join(wt)})
        else: print('  파수대 연구 기사 없음')
    for f in files: print(f"  → {f['name'][:40]}… {len(f['text']):,}자")
    payload = json.dumps({'v': 1, 'generated': dt.datetime.now(KST).isoformat(timespec='seconds'), 'files': files}, ensure_ascii=False)

    gh('/gists/' + gid, {'files': {GIST_FILE: {'content': payload}}}, 'PATCH')
    print(f'Gist에 저장했습니다: 파일 {len(files)}개')

if __name__ == '__main__':
    main()
