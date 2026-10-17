#!/usr/bin/env python3
# QUAL-12 슬라이스 D — 발문(question_text)만 파싱해 정답을 독립 재계산하고 저장 answer 와 대조한다.
# 생성기(src/backend/.../*_skeleton_generator.py, harness/*_batch.py)는 import/호출하지 않는다.
# 사용: python3 audit_D_script.py [--json out.json] [--verbose]
# 판정: MATCH / MISMATCH / AMBIG(발문이 두 해석을 허용하고 저장값이 대안 해석과 일치) / UNVERIFIED(파싱·계산 불가)
# 종료코드: 스캔 0건(대조 0건) 코퍼스가 있으면 1.
import json, re, sys, itertools, collections
from fractions import Fraction
from math import comb, factorial, isqrt

ROOT = str(__import__('pathlib').Path(__file__).resolve().parents[3] / 'data' / 'corpus')
CORPORA = [
    'problem_bank_binomial_distribution_v0',
    'problem_bank_combination_binomial_v0',
    'problem_bank_permutation_combination_v0',
    'problem_bank_probability_finite_v0',
    'problem_bank_probability_law_v0',
    'problem_bank_sample_mean_distribution_v0',
    'problem_bank_discrete_ev_v0',
    'problem_bank_coordinate_geometry_v0',
    'problem_bank_conic_section_focus_v0',
    'problem_bank_vector_operations_v0',
]

FRAC = r'-?\d+(?:/\d+)?'
PF = r'(\d+/\d+|\d+)'


def F(s):
    return Fraction(s.strip())


def norm_template(q):
    """숫자(분수·음수 포함) -> # 정규화 (과업 방법 1)."""
    return re.sub(FRAC, '#', q)


def family_template(q):
    """벡터 계수식 변형을 한 군으로 묶는 보조 정규화."""
    t = norm_template(q)
    t = re.sub(r'(?<=때, )[-#ab +]+(?=의 )', 'EXPR', t)
    t = re.sub(r'(?<=대해 )[-#ab +]+(?=의 )', 'EXPR', t)
    return t


VOCAB = [
    '적어도', '많아야', '정확히', '이상', '이하', '초과', '미만', '순열', '조합', '서로 다른', '이웃',
    '복원', '조건부확률', '독립', '배반', '표본평균', '모평균', '표준편차', '분산', '평균', '초점', '장축', '단축',
    '준선', '내분', '외분', '내적', '외적', '크기', '거리', '중점', '중복', '이항정리', '계수', '또는', '동시에',
    '연이어', '일렬', '순서', '구별', '여사건', '일어나지 않을', '기약분수', '성분의 합', '성분', '실수배', 'E(X)',
    '위치벡터', '향하는', '직선', '쌍곡선', '타원', '포물선', '꺼낼', '모두', '합이',
]


def vocab_in(q):
    return [v for v in VOCAB if v in q]


def ans_frac(a):
    try:
        return Fraction(a.strip())
    except Exception:
        return None


# ---------------------------------------------------------------- 독립 계산 규칙
# 각 함수: q -> None(파싱 실패) | dict(kind, expected(없으면 None), alts{이름:값}, issues[list], ...)

def c_binomial(q):
    m = re.search(r'B\((\d+), ' + PF + r'\)', q)
    if not m:
        return None
    n = int(m.group(1)); p = F(m.group(2))
    issues = [] if 0 < p < 1 else ['p가 (0,1) 밖']
    if '분산' in q:
        return dict(kind='var', expected=n * p * (1 - p), alts={'np(분산=평균 오독)': n * p}, issues=issues)
    if '평균' in q:
        return dict(kind='mean', expected=n * p, alts={'np(1-p)': n * p * (1 - p)}, issues=issues)
    return None


def c_sample_mean(q):
    m = re.search(r'모평균이 (-?\d+)(?:,|이고) 모분산이 (\d+)인 모집단에서 크기 (\d+)인', q)
    if not m:
        return None
    mu, var, n = F(m.group(1)), F(m.group(2)), int(m.group(3))
    issues = [] if (n > 0 and var >= 0) else ['비정상 모수']
    if re.search(r'표본평균(?: X바)?의 평균', q):
        return dict(kind='xbar_mean', expected=mu, alts={}, issues=issues)
    if re.search(r'표본평균(?: X바)?의 분산', q):
        return dict(kind='xbar_var', expected=var / n, alts={'모분산 그대로(오독)': var}, issues=issues)
    return None


def c_discrete_ev(q):
    pairs = re.findall(r'P\(X=(-?\d+)\)=' + PF, q)
    if not pairs or 'E(X)' not in q:
        return None
    xs = [int(a) for a, _ in pairs]; ps = [F(b) for _, b in pairs]
    issues = []
    if sum(ps) != 1:
        issues.append(f'확률합={sum(ps)}≠1')
    if len(set(xs)) != len(xs):
        issues.append('X값 중복')
    return dict(kind='ev', expected=sum(x * p for x, p in zip(xs, ps)), alts={}, issues=issues)


def c_prob_law(q):
    issues = []
    m = re.search(r'P\(A\) = ' + PF + r', P\(B\) = ' + PF + r'이고 (?:두 사건이 |A와 B가 )동시에 일어날 확률이 ' + PF + r'일 때', q)
    if m and '또는' in q:
        a, b, c = F(m.group(1)), F(m.group(2)), F(m.group(3))
        if not (max(0, a + b - 1) <= c <= min(a, b)):
            issues.append('P(A∩B) 비실현(프레셰 경계 위반)')
        return dict(kind='union', expected=a + b - c, alts={'a+b(배반 가정 오독)': a + b}, issues=issues)
    m = re.search(r'사건 A가 일어날 확률이 ' + PF + r'이고 A가 일어났을 때 B가 일어날 조건부확률이 ' + PF + r'일 때, A와 B가 동시에', q)
    if m:
        a, b = F(m.group(1)), F(m.group(2))
        return dict(kind='mult', expected=a * b, alts={'P(A)/P(B|A)': (a / b) if b else None}, issues=issues)
    m = re.search(r'P\(A\) = ' + PF + r'이고, 조건부확률 P\(B\|A\) = ' + PF + r'일 때, 확률의 곱셈정리를 이용하여 A와 B가 동시에', q)
    if m:
        a, b = F(m.group(1)), F(m.group(2))
        return dict(kind='mult', expected=a * b, alts={}, issues=issues)
    m = re.search(r'사건 A가 일어날 확률이 ' + PF + r'일 때, A가 일어나지 않을 확률', q) or \
        re.search(r'사건 A에 대하여 P\(A\) = ' + PF + r'일 때, 사건 A의 여사건이 일어날 확률', q)
    if m:
        a = F(m.group(1))
        return dict(kind='compl', expected=1 - a, alts={'P(A) 그대로': a}, issues=issues)
    return None


def c_combination_binomial(q):
    m = re.search(r'(\d+)가지(?: 종류의 음료)? 중에서 중복을 허락하여 (\d+)(?:병|개)[을를] (?:고르는|택하는) 경우의 수', q)
    if m:
        n, r = int(m.group(1)), int(m.group(2))
        return dict(kind='H', expected=Fraction(comb(n + r - 1, r)),
                    alts={'중복순열 n^r': Fraction(n ** r), '조합 nCr': Fraction(comb(n, r))},
                    issues=[], ambiguous_phrase=True)
    m = re.search(r'\(x\+y\)\^(\d+)의 전개식에서 x(?:\^(\d+))?y(?:\^(\d+))?의 계수', q)
    if m:
        n = int(m.group(1))
        a = int(m.group(2)) if m.group(2) else 1
        b = int(m.group(3)) if m.group(3) else 1
        if a + b != n:
            return dict(kind='binom', expected=Fraction(0), alts={}, issues=[f'a+b={a+b}≠n={n} (해당 항 없음, 계수 0)'])
        return dict(kind='binom', expected=Fraction(comb(n, a)), alts={}, issues=[])
    return None


def c_perm_comb(q):
    m = re.search(r'A를 택하는 경우의 수는 (\d+)가지, B를 택하는 경우의 수는 (\d+)가지이다\. A, B가 동시에 일어날 수 없을 때, A 또는 B를 택하는 경우의 수', q)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return dict(kind='sum', expected=Fraction(a + b), alts={'곱(오독)': Fraction(a * b)}, issues=[])
    m = re.search(r'사건 A가 일어나는 경우의 수는 (\d+)가지이고, 그와 상관없이 사건 B가 일어나는 경우의 수는 (\d+)가지이다\. A, B가 연이어 일어나는 경우의 수', q)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return dict(kind='prod', expected=Fraction(a * b), alts={'합(오독)': Fraction(a + b)}, issues=[])
    m = re.search(r'서로 다른 (\d+)(?:명|개)(?: 중에서|에서) (\d+)(?:명|개)[을를] (?:뽑아 순서를 정해 세우는|택하여 일렬로 나열하는)', q)
    if m:
        n, r = int(m.group(1)), int(m.group(2))
        if r > n:
            return dict(kind='perm', expected=Fraction(0), alts={}, issues=['r>n'])
        return dict(kind='perm', expected=Fraction(factorial(n) // factorial(n - r)),
                    alts={'조합 nCr(순서 무시 오독)': Fraction(comb(n, r))}, issues=[])
    return None


def _dice_count(pred):
    tot = ok = 0
    for a, b in itertools.product(range(1, 7), repeat=2):
        tot += 1; ok += bool(pred(a + b))
    return tot, ok


def c_finite_probability(q):
    m = re.search(r'두 눈의 수의 합이 (\d+)일 확률을 기약분수로', q)
    if m:
        s = int(m.group(1)); t, k = _dice_count(lambda x: x == s)
        t2, k2 = _dice_count(lambda x: x >= s)
        return dict(kind='prob', expected=Fraction(k, t), enum=(t, k), alts={'합이 s 이상 오독': Fraction(k2, t2)}, issues=[], need_reduced=True)
    m = re.search(r'한 개의 동전을 (\d+)번 던진다\. .*앞면이 정확히 (\d+)번 나올 확률을 기약분수로', q)
    if m:
        n, k = int(m.group(1)), int(m.group(2))
        seqs = list(itertools.product('HT', repeat=n))
        ok = sum(1 for s in seqs if s.count('H') == k)
        ge = sum(1 for s in seqs if s.count('H') >= k)
        return dict(kind='prob', expected=Fraction(ok, len(seqs)), enum=(len(seqs), ok), alts={'적어도 k번 오독': Fraction(ge, len(seqs))}, issues=[], need_reduced=True)
    m = re.search(r'합이 (\d+) 이상이 되는 경우의 수를 구하시오\. \(두 주사위는 서로 구별하며', q)
    if m:
        s = int(m.group(1)); t, k = _dice_count(lambda x: x >= s)
        t2, k2 = _dice_count(lambda x: x > s)
        unord = sum(1 for a in range(1, 7) for b in range(a, 7) if a + b >= s)
        return dict(kind='count', expected=Fraction(k), enum=(t, k), alts={'초과(>) 오독': Fraction(k2), '주사위 비구별(순서 무시)': Fraction(unord)}, issues=[], need_reduced=False)
    m = re.search(r'빨간 공 (\d+)개와 파란 공 (\d+)개가 들어 있다\. 이 주머니에서 임의로 (\d+)개의 공을 동시에 꺼낼 때, 꺼낸 공이 모두 빨간 공일 확률을 기약분수로', q)
    if m:
        r, b, k = map(int, m.groups())
        balls = ['R'] * r + ['B'] * b
        if k > len(balls):
            return dict(kind='prob', expected=None, alts={}, issues=['k>공 수'])
        combos = list(itertools.combinations(range(len(balls)), k))
        ok = sum(1 for c in combos if all(balls[i] == 'R' for i in c))
        ordered = sum(1 for seq in itertools.product(range(len(balls)), repeat=k) if all(balls[i] == 'R' for i in seq))
        return dict(kind='prob', expected=Fraction(ok, len(combos)), enum=(len(combos), ok), alts={'복원추출 오독': Fraction(ordered, len(balls) ** k)}, issues=[], need_reduced=True)
    return None


def c_coordinate(q):
    m = re.search(r'\((-?\d+), (-?\d+)\)과 \((-?\d+), (-?\d+)\) 사이의 거리|A\((-?\d+), (-?\d+)\), B\((-?\d+), (-?\d+)\) 사이의 거리', q)
    if m:
        x1, y1, x2, y2 = [int(x) for x in m.groups() if x is not None]
        d2 = (x2 - x1) ** 2 + (y2 - y1) ** 2
        r = isqrt(d2)
        if r * r != d2:
            return dict(kind='dist', expected=None, alts={}, issues=[f'거리^2={d2} 비완전제곱'])
        return dict(kind='dist', expected=Fraction(r), alts={'거리제곱(오독)': Fraction(d2)}, issues=[])
    m = re.search(r'\((-?\d+), (-?\d+)\), \((-?\d+), (-?\d+)\)(?:를 지나는 직선을 y=ax\+b로 나타낼 때, a와 b의 합|[을를] 지나는 직선의 방정식이 y=ax\+b 꼴일 때, a\+b의 값)', q)
    if m:
        x1, y1, x2, y2 = map(int, m.groups())
        if x1 == x2:
            return dict(kind='line', expected=None, alts={}, issues=['x1=x2 수직선(y=ax+b 불가)'])
        a = Fraction(y2 - y1, x2 - x1); b = y1 - a * x1
        issues = [] if (a.denominator == 1 and b.denominator == 1) else ['a 또는 b 비정수']
        return dict(kind='line', expected=a + b, alts={'a-b': a - b}, issues=issues)
    return None


def c_conic(q):
    m = re.search(r'포물선 y\^2=(-?\d+)x의 초점의 x좌표', q)
    if m:
        k = int(m.group(1))
        return dict(kind='parab', expected=Fraction(k, 4), alts={'k/2': Fraction(k, 2)}, issues=[] if k > 0 else ['계수<=0'])
    m = re.search(r'타원 x\^2/(\d+)\+y\^2/(\d+)=1의 초점의 x좌표\(양수\)', q)
    if m:
        a2, b2 = int(m.group(1)), int(m.group(2))
        if a2 <= b2:
            return dict(kind='ellipse', expected=Fraction(0), alts={'sqrt|a2-b2|': Fraction(isqrt(abs(a2 - b2)))},
                        issues=[f'a^2={a2}<=b^2={b2}: 초점이 y축 위(x좌표 0) 또는 원'])
        c2 = a2 - b2; c = isqrt(c2)
        return dict(kind='ellipse', expected=Fraction(c) if c * c == c2 else None, alts={}, issues=[] if c * c == c2 else ['c 비정수'])
    m = re.search(r'쌍곡선 x\^2/(\d+)-y\^2/(\d+)=1의 초점의 x좌표\(양수\)', q)
    if m:
        a2, b2 = int(m.group(1)), int(m.group(2))
        c2 = a2 + b2; c = isqrt(c2)
        return dict(kind='hyper', expected=Fraction(c) if c * c == c2 else None, alts={'sqrt|a2-b2|': Fraction(isqrt(abs(a2 - b2)))},
                    issues=[] if c * c == c2 else ['c 비정수'])
    return None


def c_vector(q):
    m = re.search(r'A\((-?\d+), (-?\d+)\), B\((-?\d+), (-?\d+)\)에 대응하는 위치벡터를 각각 OA, OB라 할 때, 벡터 AB\(=OB−OA\)의 성분의 합', q)
    if not m:
        m = re.search(r'점 A\((-?\d+), (-?\d+)\)에서 점 B\((-?\d+), (-?\d+)\)[으]?로 향하는 벡터 AB의 x성분과 y성분의 합', q)
    if m:
        ax, ay, bx, by = map(int, m.groups())
        return dict(kind='AB', expected=Fraction((bx - ax) + (by - ay)), alts={'A-B 방향(오독)': Fraction((ax - bx) + (ay - by))}, issues=[])
    m = re.search(r'a=\((-?\d+), (-?\d+)\)(?:와|,) b=\((-?\d+), (-?\d+)\)(?:가 있을 때|에 대해),? (.+?)의 (?:x성분과 y성분|성분)의 합', q)
    if m:
        a1, a2, b1, b2 = map(int, m.groups()[:4])
        expr = m.group(5).replace(' ', '')
        toks = re.findall(r'([+-]?)(\d*)([ab])', expr)
        recon = ''.join(f'{s}{n}{v}' for s, n, v in toks)
        if not toks or recon.lstrip('+') != expr.lstrip('+'):
            return None
        ca = cb = 0
        for s, n, v in toks:
            c = (int(n) if n else 1) * (-1 if s == '-' else 1)
            if v == 'a': ca += c
            else: cb += c
        vx = ca * a1 + cb * b1; vy = ca * a2 + cb * b2
        return dict(kind='lincomb', expected=Fraction(vx + vy),
                    alts={'x성분만': Fraction(vx), '계수 부호 무시': Fraction(abs(ca) * (a1 + a2) + abs(cb) * (b1 + b2))}, issues=[])
    return None


CALC = {
    'problem_bank_binomial_distribution_v0': c_binomial,
    'problem_bank_combination_binomial_v0': c_combination_binomial,
    'problem_bank_permutation_combination_v0': c_perm_comb,
    'problem_bank_probability_finite_v0': c_finite_probability,
    'problem_bank_probability_law_v0': c_prob_law,
    'problem_bank_sample_mean_distribution_v0': c_sample_mean,
    'problem_bank_discrete_ev_v0': c_discrete_ev,
    'problem_bank_coordinate_geometry_v0': c_coordinate,
    'problem_bank_conic_section_focus_v0': c_conic,
    'problem_bank_vector_operations_v0': c_vector,
}

# ---------------------------------------------------------------- 해설(answer_explanation) 대조 규칙
# kind -> (해설에 반드시 있어야 하는 어구, 있으면 발문 유형과 상충하는 어구)
EXPL_REQ = {
    'mean': (['평균은 np'], ['분산은']),
    'var': (['분산은 np(1-p)'], ['평균은 np']),
    'xbar_mean': (['모평균과 같'], ['나눈']),
    'xbar_var': (['표본크기로 나눈'], ['모평균과 같']),
    'ev': (['값과 확률의 곱의 합'], []),
    'union': (['덧셈정리'], ['곱셈정리', '여사건']),
    'mult': (['곱셈정리'], ['덧셈정리', '여사건']),
    'compl': (['여사건'], ['덧셈정리', '곱셈정리']),
    'H': (['중복조합'], ['중복순열']),
    'binom': (['이항정리'], []),
    'sum': (['합의 법칙'], ['곱의 법칙']),
    'prod': (['곱의 법칙'], ['합의 법칙']),
    'perm': (['순열'], []),
    'dist': (['빗변'], []),
    'line': (['기울기', '절편'], []),
    'parab': (['4p', '4로 나'], []),
    'ellipse': (['뺀'], ['더한']),
    'hyper': (['더한'], ['뺀']),
    'AB': (['도착점 B의 좌표에서 출발점 A의 좌표를 빼'], ['도착점 A', '출발점 B']),
    'lincomb': (['성분별'], []),
}


def expl_check(kind, r, calc):
    ex = r.get('answer_explanation') or ''
    out = []
    req, forb = EXPL_REQ.get(kind, ([], []))
    for k in req:
        if k not in ex:
            out.append(f'해설에 "{k}" 없음')
    for k in forb:
        if k in ex:
            out.append(f'해설에 "{k}" 존재(발문 유형과 상충)')
    a = (r.get('answer') or '').strip()
    if a and not re.search(r'(?<![\d/])' + re.escape(a) + r'(?![\d/])', ex):
        out.append(f'해설에 저장 answer({a}) 부재')
    if 'enum' in calc:
        m = re.search(r'전체 경우의 수는 (\d+)가지이고(?:, 그중 .*?인 경우는| 조건을 만족하는 경우는) (\d+)가지', ex)
        if not m:
            out.append('해설에서 N/K 파싱 실패')
        else:
            nk = (int(m.group(1)), int(m.group(2)))
            if nk != tuple(calc['enum']):
                out.append(f'해설 (N,K)={nk} ≠ 독립 열거 {tuple(calc["enum"])}')
    return out


def load(d):
    with open(f'{ROOT}/{d}/problems.jsonl', encoding='utf-8') as f:
        return [json.loads(l) for l in f if l.strip()]


def audit(d):
    rows = load(d)
    calc_fn = CALC[d]
    res = dict(corpus=d, rows=len(rows),
               published=sum(1 for r in rows if r.get('is_published') is True),
               not_published=sum(1 for r in rows if r.get('is_published') is not True))
    templ = collections.Counter(); fam = collections.Counter(); tv = {}
    cnt = collections.Counter(); by_kind = collections.defaultdict(collections.Counter)
    examples = collections.defaultdict(list)
    expl_rows = []; sem_rows = []; fmt_rows = []
    for r in rows:
        q = r['question_text']
        t = norm_template(q)
        templ[t] += 1; fam[family_template(q)] += 1; tv[t] = vocab_in(t)
        c = calc_fn(q)
        if c is None:
            cnt['UNVERIFIED_parse'] += 1
            examples['UNVERIFIED'].append((q, r.get('answer'), None, '발문 파싱 실패')); continue
        kind = c['kind']; exp = c['expected']
        if c['issues']:
            sem_rows.append((q, r.get('answer'), None if exp is None else str(exp), '; '.join(c['issues'])))
        if exp is None:
            cnt['UNVERIFIED_nocompute'] += 1
            examples['UNVERIFIED'].append((q, r.get('answer'), None, '; '.join(c['issues']) or '독립 계산 불가')); continue
        sa = ans_frac(r.get('answer', ''))
        if sa is None:
            cnt['UNVERIFIED_answer_unparsable'] += 1
            examples['UNVERIFIED'].append((q, r.get('answer'), str(exp), 'answer 파싱 불가')); continue
        if sa == exp:
            status = 'MATCH'
        else:
            hit = [k for k, v in c['alts'].items() if v is not None and v == sa]
            status = 'AMBIG' if (hit and c.get('ambiguous_phrase')) else 'MISMATCH'
            examples[status].append((q, r['answer'], str(exp), f'kind={kind}; 일치하는 대안해석={hit}'))
        cnt[status] += 1; by_kind[kind][status] += 1
        if c.get('ambiguous_phrase'):
            for k, v in c['alts'].items():
                if v is not None and v != exp:
                    cnt['distinguishable:' + k] += 1
                    if v == sa:
                        cnt['stored_matches_alt:' + k] += 1
        if c.get('need_reduced') and str(sa) != r['answer'].strip():
            fmt_rows.append((q, r['answer'], str(sa), '기약분수 요구인데 비기약/형식 불일치'))
        af = r.get('answer_format'); ans = r['answer'].strip()
        isint = re.fullmatch(r'-?\d+', ans) is not None
        if (af == '자연수' and not (isint and int(ans) > 0)) or (af == '분수' and '/' not in ans and not isint) :
            cnt['answer_format_oddity'] += 1
        if af == '분수' and isint:
            cnt['answer_format=분수 but 정수 answer'] += 1
        if af == '실수' and isint:
            cnt['answer_format=실수 but 정수 answer'] += 1
        if af == '자연수' and not (isint and int(ans) > 0):
            cnt['answer_format=자연수 but 비자연수 answer'] += 1
        ei = expl_check(kind, r, c)
        if ei:
            expl_rows.append((q, r['answer'], str(exp), '; '.join(ei)))
    res['templates'] = len(templ); res['families'] = len(fam)
    res['template_list'] = [(t, n, tv[t]) for t, n in templ.most_common()]
    res['compared'] = cnt['MATCH'] + cnt['MISMATCH'] + cnt['AMBIG']
    res['MATCH'] = cnt['MATCH']; res['MISMATCH'] = cnt['MISMATCH']; res['AMBIG'] = cnt['AMBIG']
    res['UNVERIFIED'] = sum(v for k, v in cnt.items() if k.startswith('UNVERIFIED'))
    res['counters'] = dict(cnt); res['by_kind'] = {k: dict(v) for k, v in by_kind.items()}
    res['sem_issue_n'] = len(sem_rows); res['expl_issue_n'] = len(expl_rows); res['fmt_issue_n'] = len(fmt_rows)
    res['examples'] = {k: v[:5] for k, v in examples.items()}
    res['sem_examples'] = sem_rows[:5]; res['expl_examples'] = expl_rows[:5]; res['fmt_examples'] = fmt_rows[:5]
    res['zero_scan_fail'] = res['rows'] == 0 or res['compared'] == 0
    return res


def selftest():
    """검사기 변별력 확인: 저장 answer 를 +1 로 오염시키면 전건 MISMATCH(또는 AMBIG)여야 하고, 해설을 다른 행의 것으로 바꾸면 해설불일치가 90% 이상 잡혀야 한다."""
    global load
    orig_load = load
    ok = True
    for mode in ('answer+1', 'expl-shuffle'):
        def patched(d, _m=mode):
            rows = orig_load(d)
            for r in rows:
                if _m == 'answer+1':
                    a = ans_frac(r['answer'])
                    r['answer'] = str(a + 1) if a is not None else r['answer']
            if _m == 'expl-shuffle':
                ex = [r['answer_explanation'] for r in rows][::-1]
                for r, e in zip(rows, ex):
                    r['_orig_expl'] = r['answer_explanation']; r['answer_explanation'] = e
            return rows
        load = patched
        for d in CORPORA:
            res = audit(d)
            if mode == 'answer+1':
                good = res['MISMATCH'] + res['AMBIG'] == res['compared'] and res['compared'] > 0
            else:
                n_diff = sum(1 for a_, b_ in zip(orig_load(d), orig_load(d)[::-1]) if a_['answer_explanation'] != b_['answer_explanation'])
                good = n_diff > 0 and res['expl_issue_n'] >= 0.9 * n_diff
                print(f"    (해설을 다른 행 것으로 교체: 실제로 달라진 행 {n_diff}, 검출 {res['expl_issue_n']})")
            print(f"[selftest:{mode}] {d}: compared={res['compared']} MISMATCH={res['MISMATCH']} AMBIG={res['AMBIG']} expl_issue={res['expl_issue_n']} -> {'검출 OK' if good else '검출 실패(검사기 무력)'}")
            ok &= good
    load = orig_load
    return ok


def main():
    if '--selftest' in sys.argv:
        sys.exit(0 if selftest() else 1)
    out = {}
    for d in CORPORA:
        res = audit(d); out[d] = res
        print(f"{d}: 행 {res['rows']} 템플릿 {res['templates']}(군 {res['families']}) 대조 {res['compared']} "
              f"MATCH {res['MATCH']} MISMATCH {res['MISMATCH']} AMBIG {res['AMBIG']} UNVERIFIED {res['UNVERIFIED']} "
              f"조건이상 {res['sem_issue_n']} 해설불일치 {res['expl_issue_n']} 형식 {res['fmt_issue_n']} "
              f"published {res['published']}" + ('  [스캔 0건=실패]' if res['zero_scan_fail'] else ''))
        if '--verbose' in sys.argv:
            print('  by_kind', res['by_kind']); print('  counters', res['counters'])
    if '--json' in sys.argv:
        with open(sys.argv[sys.argv.index('--json') + 1], 'w', encoding='utf-8') as f:
            json.dump(out, f, ensure_ascii=False, indent=1, default=str)
    sys.exit(1 if any(o['zero_scan_fail'] for o in out.values()) else 0)


if __name__ == '__main__':
    main()
