"""jw.org 공식 다운로드(EPUB)에서 이번 주와 다음 몇 주의
집회 교재·파수대 연구 기사·성경 읽기 범위를 글로 바꿔, 나만 보는 비공개 Gist에 넣는다.
앱(집회 준비)은 열릴 때 이 Gist 파일(jw-weekly.json)을 읽어 자동으로 채운다.

환경 변수: JW_GIST_TOKEN (gist 권한 토큰), WEEKS (몇 주 받을지, 기본 4)
공개 저장소에는 아무 내용도 남기지 않는다(로그에는 파일 이름과 글자 수만 찍는다).
"""
import io, json, os, re, sys, zipfile, datetime as dt
from html.parser import HTMLParser
import urllib.request

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
                return ls, rng
    return None, ''

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

def safe(s): return re.sub(r'[\\/:*?"<>|“”‘’]', '', s).strip()[:60]

def main():
    token = os.environ.get('JW_GIST_TOKEN', '').strip()
    if not token: sys.exit('JW_GIST_TOKEN 비밀값이 없습니다.')
    weeks = int(os.environ.get('WEEKS', '4'))
    today = dt.datetime.now(KST).date()
    mon0 = today - dt.timedelta(days=today.weekday())
    files = []
    for i in range(weeks):
        mon = mon0 + dt.timedelta(weeks=i); wid = mon.isoformat()
        print(f'{wid} 주')
        wb, rng = find_workbook(mon)
        if wb:
            label = wb[0].split('(')[0].strip()
            files.append({'name': f'{wid}_집회교재_{safe(label)}.txt', 'text': '\n\n'.join(wb)})
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

    gh = lambda path, body=None, method=None: json.loads(get('https://api.github.com' + path,
        data=json.dumps(body).encode() if body is not None else None, method=method,
        headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json'}) or b'{}')
    gid = os.environ.get('JW_GIST_ID', '').strip()
    if not gid:
        gists = gh('/gists?per_page=100')
        g = next((g for g in gists if g.get('description') == GIST_DESC), None)
        if not g: sys.exit('동기화 Gist(jiphoe-hub-sync)를 찾지 못했습니다. 앱에서 Gist 동기화를 먼저 연결하세요.')
        gid = g['id']
    gh('/gists/' + gid, {'files': {GIST_FILE: {'content': payload}}}, 'PATCH')
    print(f'Gist에 저장했습니다: 파일 {len(files)}개')

if __name__ == '__main__':
    main()
