"""jw.org 공식 다운로드(EPUB)에서 이번 주와 다음 몇 주의
집회 교재·파수대 연구 기사·성경 읽기 범위를 글로 바꿔, 나만 보는 비공개 Gist에 넣는다.
앱(집회 준비)은 열릴 때 이 Gist 파일(jw-weekly.json)을 읽어 자동으로 채운다.

환경 변수: JW_GIST_TOKEN (gist 권한 토큰), WEEKS (몇 주 받을지, 기본 4)
공개 저장소에는 아무 내용도 남기지 않는다(로그에는 파일 이름과 글자 수만 찍는다).

자료를 찾는 순서 (GitHub에서 돌려도, 내 컴퓨터에서 돌려도 같다)
  1. 내 자료 폴더(D:/JW 또는 JW_LOCAL)의 EPUB 파일 — 내 컴퓨터에서 돌릴 때만 있다
  2. 워치타워 온라인 라이브러리(wol.jw.org) — 연구용 성경의 연구 노트·연구 자료 찾아보기와 그 원문
  3. jw.org 공식 다운로드(EPUB)
내 컴퓨터에서 돌리기: 자료받기.bat 를 두 번 누른다 (토큰은 처음 한 번만 묻는다).
"""
import io, json, os, re, sys, time, zipfile, datetime as dt
from html import unescape
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

# ---------- 내 자료 폴더 (D:\JW) ----------
def local_dirs():
    ds = [d for d in os.environ.get('JW_LOCAL', '').split(os.pathsep) if d] + [r'D:\JW']
    return [d for i, d in enumerate(ds) if os.path.isdir(d) and d not in ds[:i]]

_local = None
def local_epubs():
    """내 자료 폴더의 EPUB: {(출판물 기호, 호): 경로}. jw.org 파일 이름 그대로(w_KO_20070601.epub, it-1_KO.epub, wcg_KO.epub)."""
    global _local
    if _local is None:
        _local = {}
        for d in local_dirs():
            for root, dirs, files in os.walk(d):
                dirs[:] = [x for x in dirs if x.lower() != 'claude outputs']
                for f in files:
                    if not f.lower().endswith('.epub'): continue
                    m = re.match(r'([A-Za-z0-9-]+?)_KO(?:_(\d{6,8}))?\.epub$', f, re.I)
                    if m: _local.setdefault((m[1].lower(), m[2] or ''), os.path.join(root, f))
                    elif f.startswith('성경'): _local.setdefault(('nwt', ''), os.path.join(root, f))
        if _local: print(f'내 자료 폴더 EPUB {len(_local)}개: ' + ', '.join(sorted(os.path.basename(v) for v in _local.values()))[:300])
    return _local

def local_epub(pub, issue=''):
    """내 자료 폴더에 있을 때만 연다 (내려받지 않는다)"""
    path = local_epubs().get(((pub or '').lower(), issue or ''))
    if not path: return None
    key = ('local', pub, issue)
    if key not in _cache:
        try: _cache[key] = zipfile.ZipFile(path)
        except Exception as e: print(f'  내 자료 파일을 못 엶: {os.path.basename(path)} ({e.__class__.__name__})'); _cache[key] = None
    return _cache[key]

_cache = {}
_src = {}
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
    z = local_epub(pub, issue)                      # 1순위: 내 자료 폴더
    if z:
        if pub != 'nwt' or any(re.search(r'\d{7,}\.xhtml$', n) for n in z.namelist()):
            print(f'  내 자료: {pub} {issue}'.rstrip()); _cache[key] = z; _src[key] = 'local'; return z
    try:
        j = json.loads(get(API.format(pub=pub, issue=f'&issue={issue}' if issue else '')))
        url = j['files']['KO']['EPUB'][0]['file']['url']
        z = zipfile.ZipFile(io.BytesIO(get(url)))
        print(f'  받음: {pub} {issue}'.rstrip()); _src[key] = 'jw.org'
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
        # 각주 표시(*)만 뺀다 — 성구 링크도 noteref 이므로 글은 살린다
        if tag == 'a' and 'noteref' in (a.get('epub:type') or '') and 'footnote' in (a.get('href') or ''): self.skip = 1; return
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
            docid = (re.search(r'(\d{7,})\.x?html$', n) or [None, ''])[1]
            cites = citations(z, n)
            print(f'  회중 성서 연구 {abbr} {num}장 (문서 {docid}) 참조 {len(cites)}개')
            return {'ref': (re.search(r'「[^」]+」[^(]*', ref) or [ref])[0].strip(), 'title': (p.title or '').strip(), 'text': '\n\n'.join(p.lines()), 'cites': cites, 'doc': docid}
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
WOL_UA = {'Accept-Language': 'ko', 'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36'}
def wol_open(path):
    """온라인 라이브러리 면을 연다 → (마지막 주소, 글). 연구 자료 찾아보기 링크(/wol/pc/…)는
       '…/d/r8/lp-ko/1988646#h=6:0-7:0' 처럼 문서 번호와 '그 성구를 다룬 항'(h=)이 붙은 주소로 넘어간다."""
    if path not in _wol:
        if _wol: time.sleep(0.35)                      # 온라인 라이브러리에 부담을 주지 않게 천천히
        req = urllib.request.Request(WOL + path, headers={**UA, **WOL_UA})
        with urllib.request.urlopen(req, timeout=120) as r:
            _wol[path] = (r.geturl(), r.read().decode('utf-8', 'replace'))
    return _wol[path]

def wol_get(path): return wol_open(path)[1]

# ---------- 글 다듬기 ----------
def plain(h):
    h = re.sub(r'<a[^>]*class="fn"[^>]*>.*?</a>', '', h, flags=re.S)                                  # 각주 표시(*)
    h = re.sub(r'<a[^>]*epub:type="noteref"[^>]*href="[^"]*footnote[^"]*"[^>]*>.*?</a>', '', h, flags=re.S)
    h = re.sub(r'</?(?:a|strong|em|span|b|i|u|sup|sub|ruby|rb)\b[^>]*>', '', h)                           # 글자 꾸밈 표시는 띄어쓰기 없이 뺀다
    return re.sub(r'\s+', ' ', unescape(re.sub(r'<[^>]+>', ' ', h)).replace('\xa0', ' ')).strip()

TOK = re.compile(r'<span[^>]*class="pageNum"[^>]*data-no="(\d+)"[^>]*>|<(?:p|h[1-6]|li|div|td|th|figcaption|blockquote)\b[^>]*\bdata-pid="(\d+)"[^>]*>')
def paragraphs(html):
    """글을 항(data-pid) 단위로 나눈다 → [[항 번호, 면, 글], …]. 면 표시(pageNum)를 따라 각 항이 몇 면인지도 적는다."""
    out, idx, page, pid, pos, first = [], {}, None, None, 0, None
    def add(seg):
        t = plain(seg)
        if not t or pid is None: return
        if pid in idx: out[idx[pid]][2] += ' ' + t
        else: idx[pid] = len(out); out.append([pid, page, t])
    for m in TOK.finditer(html):
        add(html[pos:m.start()]); pos = m.end()
        if m[1]:
            page = int(m[1]); first = first or page
        else: pid = int(m[2])
    add(html[pos:])
    for x in out:                                      # 첫 면 표시 앞의 글은 그 앞 면이다
        if x[1] is None: x[1] = (first - 1) if first else 0
    return [x for x in out if x[2] not in ('답을 적는 칸', '^')]

def parse_h(url):
    """'…#h=6:0-7:0' → (6, 6) · '…#h=8:0-9:120' → (8, 9) : 그 성구를 다룬 항의 범위"""
    m = re.search(r'[#&]h=(\d+)(?::(\d+))?(?:-(\d+)(?::(\d+))?)?', url or '')
    if not m: return None
    a = int(m[1]); b = int(m[3]) if m[3] else a
    if m[3] and m[4] is not None and int(m[4]) == 0 and b > a: b -= 1
    return (a, b)

def verse_pids(paras, c, v):
    """항(h=) 표시가 없을 때: 'c:v'(범위 1:12-22, 나열 1:12, 22 포함)를 언급한 항을 찾는다"""
    hit = []
    for pid, _, t in paras:
        for m in re.finditer(rf'(?<![\d:]){c}:(\d+(?:\s*[-–]\s*\d+)?(?:,\s*\d+(?:\s*[-–]\s*\d+)?(?!\s*:))*)', t):
            for part in re.split(r',\s*', m[1]):
                ab = [int(x) for x in re.split(r'\s*[-–]\s*', part) if x.isdigit()]
                if ab and ab[0] <= int(v) <= ab[-1]: hit.append(pid)
    return hit

def label_pages(label, span=6):
    pm = re.search(r'(\d{1,4})(?:\s*-\s*(\d{1,4}))?\s*면', label)
    return list(range(int(pm[1]), min(int(pm[2] or pm[1]), int(pm[1]) + span) + 1)) if pm else []

def epub_doc(z, pages):
    """EPUB에서 그 면이 들어 있는 문서를 찾아 항 단위로 꺼낸다"""
    want = set(pages)
    for n in spine(z):
        raw = z.read(n).decode('utf-8', 'replace')
        nums = {int(x) for x in re.findall(r'class="pageNum"[^>]*data-no="(\d+)"', raw)}
        if nums and (nums & want or (min(nums) - 1) in want):
            ps = paragraphs(raw)
            if ps:
                t = re.search(r'<title>(.*?)</title>', raw, re.S)
                return {'id': (re.search(r'(\d{7,})\.x?html$', n) or [0, n])[1], 'title': plain(t[1]) if t else '', 'paras': ps}
    return None

def wol_doc(url, html):
    body = html[html.find('<article'):] if '<article' in html else html
    end = body.find('</article>')
    ps = paragraphs(body[:end] if end > 0 else body)
    t = re.search(r'<title>(.*?)</title>', html, re.S)
    did = re.search(r'/d/[^/]+/[^/]+/(\d+)', url or '')
    return {'id': did[1] if did else url, 'title': re.sub(r'\s*[—-]\s*워치타워 온라인 라이브러리\s*$', '', plain(t[1])) if t else '', 'paras': ps} if ps else None

DOC_MAX = 60000
def trim_doc(doc, pages, pids):
    """아주 긴 문서(「통찰」 항목 등)는 가리킨 면과 그 성구를 다룬 항 주변만 남긴다"""
    if sum(len(p[2]) for p in doc['paras']) <= DOC_MAX: return doc
    want, keep = set(pages), set()
    for i, p in enumerate(doc['paras']):
        if p[1] in want or (pids and pids[0] - 4 <= p[0] <= pids[1] + 4): keep.add(i)
    ps, n = [], 0
    for i in sorted(keep):
        n += len(doc['paras'][i][2])
        if n > DOC_MAX: break
        ps.append(doc['paras'][i])
    return dict(doc, paras=ps or doc['paras'][:40], part=True)

def fetch_ref(label, href, c=None, v=None):
    """연구 자료 찾아보기 한 항목의 원문을 가져온다.
       순서: ① 내 자료 폴더(D:\\JW)의 EPUB → ② 온라인 라이브러리(그 성구를 다룬 항까지 알려 준다) → ③ jw.org 공식 EPUB.
       반환: (문서 {id,title,paras}, 항 범위 (a,b) 또는 None, 어디서 왔는지) — 못 찾으면 (None, None, '')"""
    pages = label_pages(label)
    doc = h = None; via = ''
    code = issue = None
    if local_epubs() and pages:
        try:
            code, issue, _ = resolve(label)
            z = local_epub(code, issue) if code else None
            doc = epub_doc(z, pages) if z else None
            if doc: via = 'local'
        except Exception as e: print(f'  내 자료 확인 실패: {label[:30]} ({e.__class__.__name__})')
    if not doc and href:
        try:
            url, html = wol_open(href); doc = wol_doc(url, html); h = parse_h(url)
            if doc: via = 'wol'
        except Exception as e: print(f'  온라인 라이브러리 실패: {label[:30]} ({e.__class__.__name__} {getattr(e, "code", "")})')
    if not doc and pages:
        try:
            if code is None: code, issue, _ = resolve(label)
            z = epub(code, issue) if code else None
            doc = epub_doc(z, pages) if z else None
            if doc: via = _src.get((code, issue), 'jw.org')
        except Exception as e: print(f'  공식 파일 실패: {label[:30]} ({e.__class__.__name__})')
    if not doc: return None, None, ''
    if h:                                               # 가리킨 항이 실제로 그 문서에 있을 때만 쓴다
        ids = {p[0] for p in doc['paras']}
        if not any(h[0] <= i <= h[1] for i in ids): h = None
    if not h and c and v:
        on = [p for p in doc['paras'] if p[1] in set(pages)] or doc['paras']
        hit = verse_pids(on, c, v)
        if hit: h = (min(hit), max(hit))
    return trim_doc(doc, pages, h), h, via

def focus_text(doc, h, pages, limit=6000):
    """그 성구를 다룬 항(앞뒤 한 항씩 포함). 항을 모르면 가리킨 면의 글."""
    ps = doc['paras']
    if h: sel = [p for p in ps if h[0] - 1 <= p[0] <= h[1] + 1]
    else: sel = [p for p in ps if p[1] in set(pages)] or ps
    return '\n\n'.join(p[2] for p in sel)[:limit]

def study_sections(b, c):
    """연구용 성경 한 장 → {절: {notes[], foot[], marg[], rsg[(표기, 링크)], dx[]}}"""
    html = wol_get(f'/ko/wol/b/r8/lp-ko/nwtsty/{b}/{c}')
    parts = re.split(r'<div class="section"[^>]*data-key="(\d+)-(\d+)-(\d+)"[^>]*>', html)
    out = {}
    for k in range(1, len(parts) - 3, 4):
        v, body = parts[k + 2], parts[k + 3]
        lis = lambda block: [plain(x) for x in re.findall(r'<li\b[^>]*>(.*?)</li>', block, re.S)]
        grp = lambda name: (re.search(rf'<div class="group {name}\b[^"]*">(.*?)</ul>', body, re.S) or [0, ''])[1]
        notes = [plain(x) for x in re.findall(r'<li class="item studyNote"[^>]*>(.*?)</li>', body, re.S)]
        foot = [x for x in lis(grp('footnote')) if x]
        marg = [plain(x) for x in re.findall(r'<span class="marginal title">(.*?)</span>\s*</span>', grp('marginal'), re.S)]
        rsg, pub, pubs = [], '', {}
        TITLE = r'「[^」]+」(?:\s*\([^)]*\))?'                         # 「파수대」 · 「파수대」 (연구용)
        for blk in re.findall(r'<li class="item ref-rsg"[^>]*>(.*?)</li>', body, re.S):
            for pm in re.finditer(r'<p\b([^>]*)>(.*?)</p>', blk, re.S):
                links = [(h, plain(t).rstrip(',').strip()) for h, t in re.findall(r'<a [^>]*href="(/[a-z-]+/wol/pc/[^"]+)"[^>]*>(.*?)</a>', pm[2], re.S)]
                links = [(h, t) for h, t in links if t]
                if not links:
                    t = plain(pm[2])
                    if re.fullmatch(TITLE, t): pub = t
                    continue
                if re.search(r'class="[^"]*\bsu\b', pm[1]) or all(re.fullmatch(TITLE, t) for _, t in links):   # 출판물 이름 줄
                    pub = links[0][1]; pubs.setdefault(pub, links[0][0]); continue
                # 한 줄에 면이 여러 개: '2006/4, 3,' + '4-5면' → '2006/4, 3면' · '2006/4, 4-5면'
                m0 = re.match(r'^(.*?)(\d+(?:\s*-\s*\d+)?)\s*면?$', links[0][1])
                prefix = m0[1] if m0 else ''
                myeon = any(t.endswith('면') for _, t in links)
                for i, (href, t) in enumerate(links):
                    if i and re.fullmatch(r'\d+(?:\s*-\s*\d+)?\s*면?', t): t = prefix + t
                    if myeon and re.search(r'\d$', t): t += '면'
                    m = re.match(TITLE, t)
                    if m: pub = m[0]
                    lab = t if m else f'{pub} {t}'.strip()
                    if not any(x[1] == href for x in rsg): rsg.append((lab, href))
            for name, href in pubs.items():                    # 면 표기 없이 출판물 이름만 있는 참조
                if not any(l.startswith(name) for l, _ in rsg): rsg.append((name, href))
        dx = [plain(x).replace('출판물 색인', '').strip() for x in re.findall(r'<li class="item ref-dx"[^>]*>(.*?)</li>', body, re.S)]
        out[v] = {'notes': notes, 'foot': foot, 'marg': [x.lstrip('+ ') for x in marg], 'rsg': rsg, 'dx': [x for x in dx if x]}
    return out

SRC_NAME = {'local': '내 자료(D:\\JW)', 'wol': '온라인 라이브러리', 'jw.org': 'jw.org 공식 파일'}
def study_verse(key):
    """'24/51/6' → 연구용 성경의 연구 노트·각주·상호 참조·연구 자료 찾아보기(링크를 따라가 원문까지)"""
    b, c, v = key.split('/')
    sec = study_sections(b, c).get(v)
    if not sec: return None
    refs = []
    for label, href in sec['rsg'][:20]:
        doc, h, via = fetch_ref(label, href, c, v)
        pages = label_pages(label)
        t = ''
        if doc:
            foc = focus_text(doc, h, pages, 4000) if h else ''
            full = '\n\n'.join(p[2] for p in doc['paras'] if not pages or p[1] in set(pages)) or '\n\n'.join(p[2] for p in doc['paras'])
            t = (f'[이 성구를 다룬 부분]\n{foc}\n\n[가리킨 면 전체]\n' if foc and foc != full[:len(foc)] else '') + full[:12000]
        refs.append({'ref': label, 'text': t, 'ok': bool(t), 'via': via, 'doc': doc['id'] if doc else ''})
    lines = []
    if sec['notes']: lines.append('[연구 노트] ' + ' / '.join(sec['notes']))
    if sec['foot']: lines.append('[각주] ' + ' / '.join(sec['foot']))
    if sec['rsg']: lines.append('[연구 자료 찾아보기] ' + '; '.join(l for l, _ in sec['rsg']))
    if sec['dx']: lines.append('[출판물 색인] ' + '; '.join(sec['dx']))
    if sec['marg']: lines.append('[상호 참조] ' + ' / '.join(sec['marg']))
    return {'notes': '\n'.join(lines) or '(연구 노트 없음)', 'refs': refs}

CH_VER = 2
def study_chapter(key, max_refs=200):
    """'24/51' → 그 장 모든 절의 연구 노트 + 연구 자료 찾아보기 '전부'의 원문.
       같은 기사를 여러 절이 가리키면 기사 글(docs)은 한 번만 담고, 절마다 '그 성구를 다룬 항'(h)만 따로 적는다.
       반환: {v:2, verses:{절:{notes, rsg[표기], refs[{ref, doc, h, pages, via, text}]}}, docs:{문서 번호:{title, paras}}, refs:[옛 앱용 {v, ref, text}]}"""
    b, c = key.split('/')
    secs = study_sections(b, c)
    verses, docs, flat, n, src = {}, {}, [], 0, {}
    for v in sorted(secs, key=int):
        sec = secs[v]
        if v == '0' or not (sec['notes'] or sec['rsg']): continue
        refs = []
        for label, href in sec['rsg']:
            if n >= max_refs: break
            n += 1
            doc, h, via = fetch_ref(label, href, c, v)
            if not doc: refs.append({'ref': label, 'ok': False}); continue
            did = str(doc['id'])
            old = docs.get(did)
            if not old or len(doc['paras']) > len(old['paras']): docs[did] = {'title': doc['title'], 'paras': doc['paras'], **({'part': True} if doc.get('part') else {})}
            pages = label_pages(label)
            text = focus_text(doc, h, pages)
            refs.append({'ref': label, 'ok': True, 'doc': did, 'h': list(h) if h else None, 'pages': pages, 'via': via, 'text': text})
            flat.append({'v': v, 'ref': label, 'text': text[:3500]})
            src[via] = src.get(via, 0) + 1
        verses[v] = {'notes': ' / '.join(sec['notes']), 'rsg': [l for l, _ in sec['rsg']], 'refs': refs}
    return {'v': CH_VER, 'verses': verses, 'docs': docs, 'refs': flat, 'src': src}


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

BOOKS = ('창세기 출애굽기 레위기 민수기 신명기 여호수아 사사기 룻기 사무엘상 사무엘하 열왕기상 열왕기하 역대기상 역대기하 에스라 느헤미야 에스더 욥기 시편 잠언 전도서 아가 이사야 예레미야 예레미야애가 에스겔 다니엘 호세아 요엘 아모스 오바댜 요나 미가 나훔 하박국 스바냐 학개 스가랴 말라기 '
         '마태복음 마가복음 누가복음 요한복음 사도행전 로마서 고린도전서 고린도후서 갈라디아서 에베소서 빌립보서 골로새서 데살로니가전서 데살로니가후서 디모데전서 디모데후서 디도서 빌레몬서 히브리서 야고보서 베드로전서 베드로후서 요한1서 요한2서 요한3서 유다서 요한계시록').split()
def chapter_keys(rng):
    """'예레미야 애가 1-2장' → ['25/1', '25/2']"""
    m = re.match(r'\s*(.+?)\s*(\d{1,3})(?:\s*[-–]\s*(\d{1,3}))?\s*장', rng or '')
    if not m: return []
    name = re.sub(r'\s', '', m[1])
    name = {'탈출기': '출애굽기', '재판관기': '사사기', '솔로몬의노래': '아가', '계시록': '요한계시록'}.get(name, name)
    if name not in BOOKS: return []
    return [f'{BOOKS.index(name) + 1}/{c}' for c in range(int(m[2]), int(m[3] or m[2]) + 1)]

def auto_chapters(weekly):
    """이번 주와 다음 두 주의 성경 읽기 범위 — 앱을 열지 않아도 미리 받아 둔다"""
    out = []
    today = dt.datetime.now(KST).date(); mon = (today - dt.timedelta(days=today.weekday())).isoformat()
    for f in (weekly or {}).get('files', []):
        m = re.match(r'(\d{4}-\d{2}-\d{2})_성경범위_(.+)\.txt$', f.get('name', ''))
        if m and mon <= m[1] <= (dt.date.fromisoformat(mon) + dt.timedelta(days=14)).isoformat(): out += chapter_keys(m[2])
    return out

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
    # 장 단위: 아직 없거나 옛 형식(원문 일부만 받던 것)이면 새로 받는다. 원문 전체는 장마다 따로 파일(jw-ch-책-장.json)에 둔다.
    old = lambda k: have.get('studych:' + k)
    chapters = [r['studych'] for r in norm if r.get('studych') and (not old(r['studych']) or (old(r['studych']).get('ok') and old(r['studych']).get('v', 1) < CH_VER))]
    try: chapters += [k for k in auto_chapters(read(GIST_FILE)) if not old(k) or (old(k).get('ok') and old(k).get('v', 1) < CH_VER)]
    except Exception as e: print('  읽기 범위 미리 받기 건너뜀:', e.__class__.__name__)
    chapters = [k for i, k in enumerate(chapters) if k not in chapters[:i]]
    extra = {}; t0 = time.time()
    for k in chapters[:6]:
        if time.time() - t0 > 600: print('  시간이 다 되어 남은 장은 다음 실행 때 받습니다.'); break
        try:
            st = study_chapter(k)
            fname = 'jw-ch-' + k.replace('/', '-') + '.json'
            nref = sum(1 for x in st['verses'].values() for r in x['refs'] if r.get('ok'))
            miss = sum(1 for x in st['verses'].values() for r in x['refs'] if not r.get('ok'))
            extra[fname] = json.dumps(st, ensure_ascii=False)
            have['studych:' + k] = {'ok': bool(st['verses']), 'v': CH_VER, 'file': fname, 'at': dt.datetime.now(KST).isoformat(timespec='seconds'),
                'n': {'verses': len(st['verses']), 'refs': nref, 'miss': miss, 'docs': len(st['docs'])}, 'src': st['src'],
                # 옛 앱도 읽을 수 있게 가벼운 요약을 함께 둔다
                'verses': {v: {'notes': x['notes'], 'rsg': x['rsg']} for v, x in st['verses'].items()},
                'refs': [dict(r, text=r['text'][:1200]) for r in st['refs'][:40]]}
            print(f"  ✓ 장 연구 노트 {k} · 절 {len(st['verses'])}개 · 연구 자료 원문 {nref}건(못 찾음 {miss}) · 기사 {len(st['docs'])}개 · 출처 {st['src']} · {len(extra[fname]):,}자")
        except Exception as e:
            if not old(k): have['studych:' + k] = {'ok': False, 'err': e.__class__.__name__, 'verses': {}, 'refs': []}
            print(f'  ✗ 장 연구 노트 {k} ({e.__class__.__name__} {getattr(e, "code", "")})')
    # 6주 지난 장 파일은 지운다 (Gist가 무거워지지 않게)
    cut = (dt.datetime.now(KST) - dt.timedelta(days=42)).isoformat(timespec='seconds')
    for hk in [x for x in have if x.startswith('studych:') and have[x].get('file') and have[x].get('at', '9') < cut]:
        extra[have[hk]['file']] = None; del have[hk]
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
    if todo or studies or chapters or extra:
        out = {REF_FILE: {'content': json.dumps(have, ensure_ascii=False)}}
        for name, content in extra.items():
            if content is not None: out[name] = {'content': content}
            elif name in files: out[name] = None
        gh('/gists/' + gid, {'files': out}, 'PATCH')
        print('요청한 면을 Gist에 저장했습니다.')

TOKEN_FILE = os.path.join(os.path.expanduser('~'), '.jiphoe_token')
def read_token():
    """GitHub에서는 비밀값(JW_GIST_TOKEN). 내 컴퓨터에서는 처음 한 번 물어서 내 사용자 폴더에만 저장해 둔다."""
    t = os.environ.get('JW_GIST_TOKEN', '').strip()
    if t: return t
    if os.path.exists(TOKEN_FILE):
        t = open(TOKEN_FILE, encoding='utf-8').read().strip()
        if t: return t
    if sys.stdin and sys.stdin.isatty():
        print('앱 설정의 동기화에 넣은 것과 같은 GitHub 토큰(gist 권한)을 붙여넣고 Enter를 누르세요.')
        print(f'(이 컴퓨터의 {TOKEN_FILE} 에만 저장됩니다. 지우면 다시 묻습니다.)')
        t = input('GitHub 토큰: ').strip()
        if t:
            with open(TOKEN_FILE, 'w', encoding='utf-8') as f: f.write(t)
    return t

def main():
    for st in (sys.stdout, sys.stderr):
        try: st.reconfigure(encoding='utf-8', errors='replace')
        except Exception: pass
    token = read_token()
    if not token: sys.exit('GitHub 토큰이 없습니다 (JW_GIST_TOKEN).')
    local_epubs()
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
