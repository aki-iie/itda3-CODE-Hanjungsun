"""
날짜 형식 판별기 v4 — ITDA / [CODE]_한정선체고

v3까지는 YMD/DMY/MDY 세 해석을 모두 나열해 점수로 골랐다.
v4는 팀 합의로 **형식 판별을 결정론(deterministic)으로** 바꿨다.
숫자 묶음 하나가 주어지면 해석은 언제나 하나로 정해진다.

  ① 앞이 4자리          → YYYY.MM.DD 순서대로            (한국 관행)
  ② 뒤가 4자리          → DD/MM/YYYY                     (글로벌 표준)
       └ 둘째 칸이 13 이상이면 MM/DD/YYYY
  ③ 전부 2자리          → 앞칸이 연도 해석창 [19, 올해+1] 안이면 무조건 앞이 연도
                          아니면 뒷칸이 연도
  ④ 가운데 칸이 13 이상 → 가운데는 일. YYYY.DD.MM / YY.DD.MM
  ⑤ 월 이름이 보이면    → 이름이 월을 확정. 앞의 수=일, 뒤의 수=(일→연)

그 결과 '점수'는 형식을 고르는 데 쓰이지 않는다.
**한 이미지에 날짜가 여러 개일 때 어느 것이 소비기한인가**를 고르는 데만 쓴다.

부분점수(컬럼별)가 있으므로 **칸 단위로 살린다**.
연도가 범위 밖이면 연도만 버리고 월·일은 제출한다. 2월 30일이면 일만 버린다.
"""
import os
import re
import unicodedata
from datetime import date

# ── A1. 월 이름 사전 ────────────────────────────────────────────────
# 오인식 변형을 손으로 나열하면 끝이 없다. '글자 하나가 비슷한 글자로
# 바뀐다'는 규칙으로 자동 생성한다. (JAN→IAN 은 J→I 치환 1회로 나옴)
_MONTH_BASE = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
               "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
_LONG = {"SEPT": 9, "JANUARY": 1, "FEBRUARY": 2, "MARCH": 3, "APRIL": 4,
         "JUNE": 6, "JULY": 7, "AUGUST": 8, "SEPTEMBER": 9,
         "OCTOBER": 10, "NOVEMBER": 11, "DECEMBER": 12}

CONFUSE = {
    "A": "4R", "B": "8R6", "C": "G0OQ", "D": "O0P", "E": "FB8",
    "F": "EPT", "G": "6C0O", "I": "1LT", "J": "IL1T", "L": "I1",
    "M": "HNW", "N": "MHW", "O": "0QDC", "P": "RF", "R": "PBK",
    "S": "5", "T": "I7", "U": "VY0", "V": "UY", "Y": "V7",
}
# 한 글자 치환으로 만들어지지만 실제 영어 단어라 오탐 위험이 큰 것 → 제외
_BANNED = {"WAR", "WAY", "JAM", "TAN", "MAN", "MAP", "CAR", "CAP", "BAR",
           "BAN", "PAN", "FAR", "FAT", "SET", "NET", "OUT", "OIL", "MAX"}


def _gen_variants(w):
    out = {w}
    for i, ch in enumerate(w):
        for alt in CONFUSE.get(ch, ""):
            out.add(w[:i] + alt + w[i + 1:])
    return out


MONTHS = dict(_LONG)
for _w, _n in _MONTH_BASE.items():
    for _v in _gen_variants(_w):
        if _v not in _BANNED:
            MONTHS.setdefault(_v, _n)
# 두 글자가 동시에 깨진 실측 사례 (생성 규칙으로는 안 나옴)
MONTHS.update({"MIAY": 5, "MAV": 5, "JUI": 7, "AU6": 8, "DFC": 12,
               "NOU": 11, "DEG": 12, "APB": 4, "SEPI": 9, "0EC": 12})

# ── A3. 구분자 이형 정규화 ──────────────────────────────────────────
_SEP = str.maketrans({",": ".", ";": ".", ":": ".", "·": ".", "•": ".",
                      "'": ".", "`": ".", "’": ".", "*": ".", '"': ".",
                      "_": "-", "—": "-", "–": "-", "~": "-",
                      "\\": "/", "|": "/"})

NOISE = [
    (re.compile(r"(?<![:\d])(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?(?![:\d])"), "시각"),
    (re.compile(r"0\d{1,2}-\d{3,4}-\d{4}"), "전화번호"),
    (re.compile(r"(?<!\d)\d{13}(?!\d)"), "바코드"),
    (re.compile(r"\d{1,3}(,\d{3})+"), "가격/수량"),
    (re.compile(r"\b\d+\s?(KCAL|MG|ML|KG)\b"), "영양성분"),
]

EXPIRY_KW = ["소비기한", "유통기한", "까지", "BEST BEFORE", "BEST IF USED BY",
             "USE BY", "USED BY", "EXP", "BBE"]
MFG_KW = ["제조일자", "제조일", "생산일", "MFG", "MFD", "PACKED"]

THIS_YEAR = date.today().year                 # 시스템 시계. 네트워크 불필요.

# ── 개념 1: 연도 '유효' 범위 ─────────────────────────────────────────
#    4자리로 또렷이 찍힌 연도를 받아들일 폭. 넓게 유지한다.
#    좁히면 2028년 통조림의 연도 칸을 통째로 버린다.
YEAR_MIN, YEAR_MAX = 2015, THIS_YEAR + 8      # 2015~2034

# ── 개념 2: 2자리 숫자를 '연도로 해석'할 창 ─────────────────────────
#    형식 판별(앞이 연도인가, 뒤가 연도인가)에만 쓴다.
#    실측 근거: docs/아키텍처-요약서.md §6.7, notebooks/yy_window_experiment.py
#
#    상한 = 올해 + 1  (시스템 시계에서 유도)
#      · 650장 실측에서 2자리로 표기된 연도의 관측 최대 = 올해+1
#      · 장기 보존 상품(소비기한 2년+)은 제조사가 4자리로 찍는다
#        (데이터셋의 2028년 상품 4건 전부 4자리)
#      · +2, +3, +5, +8 모두 측정했고 +1이 단조롭게 최적
#
#    하한 = 올해 − 7  (시스템 시계에서 유도)
#      · 하한의 역할은 '일자(1~31)를 연도로 오독하지 않기'. 창이 넓을수록
#        일자와 연도의 구분력이 떨어지므로 하한도 실행 시점을 따라 이동해야 한다.
#        (상수 19로 고정하면 2030년에는 [19, 31]이 되어 19 이상의 모든 일자가
#         연도 후보가 되고, 이미 지난 연도도 계속 허용된다)
#      · 폭 7년은 650장 실측의 2자리 연도 관측 최소(2019 = 2026−7)에서 유도.
#        배치 자가보정(4자리 연도 분포 P1~P99)이 유도한 값이 18(=올해−8).
#        오탐 1건을 제거하는 19를 택했다. 두 값의 차이는 650장 중 1건.
#      · 2026년 실행 시 [19, 27]로 평가되어 상수 19였을 때와 결과가 동일하다.
#
#    운영 파라미터: 업장의 입고 상품 연도 분포에 맞춰 환경변수로 조정한다.
#      ITDA_YY_BACK  최대 경과 연수 (기본 7)
#      ITDA_YY_FWD   최대 잔여 연수 (기본 1)
#    창을 넓히면 정확도 비용이 있으므로(+3 상한: 750장 659 → 658) 업장 데이터로
#    재측정한 뒤 정한다. 바코드(GTIN) 품목 정보가 있으면 품목별 설정도 가능하다.
YY_BACK = int(os.environ.get("ITDA_YY_BACK", 7))
YY_FWD = int(os.environ.get("ITDA_YY_FWD", 1))
YY_LO, YY_HI = (THIS_YEAR - YY_BACK) % 100, (THIS_YEAR + YY_FWD) % 100   # 2026년 기준 [19, 27]


def _norm(s):
    s = unicodedata.normalize("NFKC", s).upper()
    # 3단 콜론 구분자(예: 26:09:16, 2026:12:31)는 시각이 아닌 날짜이므로 점(.)으로 선변환
    s = re.sub(r"(?<!\d)(\d{2,4}):(\d{1,2}):(\d{1,4})(?!\d)", r"\1.\2.\3", s)
    return s


def _strip_noise(text):
    dropped = []
    for pat, name in NOISE:
        for m in pat.finditer(text):
            dropped.append((m.group(), name))
        text = pat.sub(" ", text)
    return text, dropped


def _year4(v, four):
    """연도 후보를 4자리로. 범위 밖이면 None → 연도 칸만 버린다(규칙 8)."""
    y = v if four else 2000 + v
    return y if YEAR_MIN <= y <= YEAR_MAX else None


def _split3(a, b, c):
    """숫자 세 칸 → (연, 월, 일, 근거). 해석은 언제나 하나로 정해진다."""
    if a == 0:
        return None, b, c, "MM.DD (연도 미검출)"
    if a >= 1000:                                   # ① 앞이 4자리
        y = _year4(a, True)
        if b >= 13:
            return y, c, b, "YYYY.DD.MM (가운데 13↑ → 일)"
        return y, b, c, "YYYY.MM.DD (연도 선치 → 순서대로)"
    if c >= 1000:                                   # ② 뒤가 4자리
        y = _year4(c, True)
        if b >= 13:
            return y, a, b, "MM/DD/YYYY (둘째칸 13↑)"
        return y, b, a, "DD/MM/YYYY (연도 후치 → 글로벌 표준)"
    if YY_LO <= a <= YY_HI:                         # ③ 전부 2자리, 앞이 연도
        y = _year4(a, False)
        if b >= 13:
            return y, c, b, "YY.DD.MM (가운데 13↑ → 일)"
        return y, b, c, "YY.MM.DD (앞이 연도 → 한국 관행)"
    if YY_LO <= c <= YY_HI:                         #    뒤만 연도 가능
        y = _year4(c, False)
        if b >= 13:
            return y, a, b, "MM.DD.YY (둘째칸 13↑)"
        return y, b, a, "DD.MM.YY (뒤가 연도)"
    return None, None, None, None                   #    연도 후보 없음 → 날짜 아님


def _sanitize(y, m, d):
    """규칙 6·8 — 유효하지 않은 '칸만' 버린다. 통째로 버리지 않는다."""
    if m is not None and not (1 <= m <= 12):
        m = None
    if d is not None and not (1 <= d <= 31):
        d = None
    if y and m and d:
        try:
            date(y, m, d)
        except ValueError:                          # 2026-02-30 → 일만 버림
            d = None
    return y, m, d


def _trim(sa, sb, sc):
    """A4 — '까지'가 0으로 붙는 등 꼬리/머리 잡음. (a, b, c, 절단여부)"""
    out = [(int(sa), int(sb), int(sc), False)]
    # ⚠️ 실측: 3자리 끝필드를 '잘린 연도'로 보고 4자리로 복원해봤으나
    #    (30/08/202 → 2020) 전체 점수가 −1 되어 되돌렸다. 절단만 유지한다.
    if len(sc) == 3 or (len(sc) == 4 and sc[0] not in "12"):
        out.append((int(sa), int(sb), int(sc[:2]), True))
    if len(sc) >= 5:                      # '22.01.1122119' 처럼 뒤에 잡음이 길게 붙은 경우
        out.append((int(sa), int(sb), int(sc[:4]), True))
        out.append((int(sa), int(sb), int(sc[:2]), True))
    if len(sa) in (3, 5):
        out.append((int(sa[1:]), int(sb), int(sc), True))
    return out


_CANON = set(_MONTH_BASE) | set(_LONG)
_MN_RE = re.compile("(?<![A-Z])(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + ")(?![A-Z])")

_RE3 = re.compile(r"(?<!\d)(\d{1,5})\s*[./\-]\s*(\d{1,2})\s*[./\-]\s*(\d{1,7})(?!\d)")
_RE8 = re.compile(r"(?<!\d)(\d{8,9})(?!\d)")
_RE6 = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_RE_YM = re.compile(r"(?<!\d)(\d{4})\s*[./\-]\s*(\d{1,2})(?!\d)")
# 첫 구분자만 사라진 꼴: '202110.20' = 2021.10.20  (실측 2건)
_RE_Y6D = re.compile(r"(?<!\d)(\d{4})(\d{2})\s*[./\-]\s*(\d{1,2})(?!\d)")
_RE_MD = re.compile(r"(?<!\d)(0[1-9]|1[0-2])\s*[./\-]\s*([0-2]\d|3[01])(?!\d)")


def _yr(ns):
    for n in ns:
        if YEAR_MIN <= n <= YEAR_MAX:
            return n
    for n in ns:
        if YY_LO <= n <= YY_HI:
            return 2000 + n
    return None


def _mn_pairs(span, st, en):
    """월 이름 좌우의 숫자 → (일, 연) 후보. 앞의 수 = 일, 뒤의 수 = (일→연)"""
    left = [int(x) for x in re.findall(r"\d{1,4}", span[:st])]
    right = [int(x) for x in re.findall(r"\d{1,4}", span[en:])]
    out = []
    if left and 1 <= left[-1] <= 31:                  # DD MMM YY(YY)
        out.append((left[-1], _yr(right) or _yr(left[:-1])))
    if len(right) >= 2 and 1 <= right[0] <= 31:       # MMM DD YY(YY)
        out.append((right[0], _yr(right[1:])))
    return out


def _cells(y, m, d):
    return sum(v is not None for v in (y, m, d))



# ── R4: OCR 원문 형태 정규화 (실측 오답 유형에서 유도, 이미지 ID·브랜드 무관) ──
_R4_RULES = [
    # 202807.257 / 202112.150 : YYYYMM.DDx (첫 구분자 탈락 + 꼬리 숫자)
    (re.compile(r"(?<!\d)(20\d{2})(0[1-9]|1[0-2])[.](0[1-9]|[12]\d|3[01])\d?(?!\d)"), r"\1.\2.\3"),
    # EXP:26/062026 : DD/MMYYYY (둘째 구분자 탈락)
    (re.compile(r"(?<!\d)(0[1-9]|[12]\d|3[01])[./\-](0[1-9]|1[0-2])(20\d{2})(?!\d)"), r"\1/\2/\3"),
    # 2021.09.030A5 : 일 자리 3자리 → 앞 두 자리 (뒤 한 자리는 로트/잡음)
    (re.compile(r"(?<!\d)(20\d{2})[.\-/](0[1-9]|1[0-2])[.\-/](0[1-9]|[12]\d|3[01])\d(?=[A-Za-z]|$|\s)"), r"\1.\2.\3"),
    # 2023.01X13 / 2023.01X1X : 일 앞 X 잡음
    (re.compile(r"(?<!\d)(20\d{2})[.\-/](0[1-9]|1[0-2])X(0[1-9]|[12]\d|3[01])(?!\d)"), r"\1.\2.\3"),
    # EXP:01.2022 / 12/2021 / 04.2022 : MM.YYYY → YYYY.MM (연·월만 있는 표기)
    (re.compile(r"(?<![\d./\-])(0[1-9]|1[0-2])[./\-](20[1-3]\d)(?![\d./\-])"), r"\2.\1"),
]
_R4_MON = re.compile(r"(?<![\d.\-/])(?<!\d )\b(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\s*[-.]?\s*(20[1-3]\d)\b(?![.\-/]?\d)")
_R4_MONNUM = {"JAN":"01","FEB":"02","MAR":"03","APR":"04","MAY":"05","JUN":"06","JUL":"07","AUG":"08","SEP":"09","OCT":"10","NOV":"11","DEC":"12"}
def _r4_normalize(t):
    u = t
    for pat, rep in _R4_RULES:
        u = pat.sub(rep, u)
    # SEP 2022 (일 없음) → 2022.09
    u = _R4_MON.sub(lambda m: f"{m.group(2)}.{_R4_MONNUM[m.group(1)]}", u.upper()) if _R4_MON.search(u.upper()) else u
    return u

def _resolve_date_core(texts, origin_hint=None, debug=False, srcs=None):
    """srcs: texts와 같은 길이의 '판독 경로' 이름 리스트(선택).
    주면 여러 경로에서 같은 날짜가 나왔는지 세어 가점한다(다중 소스 투표)."""
    joined = _norm(" ".join(texts))
    clean, dropped = _strip_noise(joined)

    cands = []   # (점수, 근거[], 연, 월, 일, 예비후보여부)

    # ── ⑤ 월 이름 (가장 강한 증거) ─────────────────────────────────
    #    ⚠️ 전체 문자열에서 숫자를 주워오면 안 된다. 실측 002663에서
    #       엉뚱한 곳의 'SER'(SEP 변형)이 이미지 반대편의 2020·08을 끌어와
    #       'EXP:2021-08-18'을 이겨버렸다. 숫자 날짜와 똑같이 **박스 단위**로 본다.
    #       그 박스만으로 부족하면 좌우 한 박스까지만 확장하고 감점한다.
    norm_toks = [_strip_noise(_norm(t))[0] for t in texts]
    month_only = None
    for idx, tk in enumerate(norm_toks):
        mt = _MN_RE.search(tk)
        if not mt:
            continue
        name = mt.group(1)
        mm = MONTHS[name]
        base = 150 if name in _CANON else 60      # 생성된 오인식 변형은 약한 증거
        prev = norm_toks[idx - 1] if idx else ""
        nxt = norm_toks[idx + 1] if idx + 1 < len(norm_toks) else ""
        win, off = prev + " " + tk + " " + nxt, len(prev) + 1
        hit = False
        for span, st, en, pen in ((tk, mt.start(1), mt.end(1), 0),
                                  (win, mt.start(1) + off, mt.end(1) + off, 30)):
            for dy, yr in _mn_pairs(span, st, en):
                y, m_, d_ = _sanitize(yr, mm, dy)
                if _cells(y, m_, d_) < 2:
                    continue
                s, why = base - pen + 20, [f"월이름 '{name}'→{mm}월"]
                if any(k in win for k in EXPIRY_KW):
                    s += 30; why.append("소비기한 키워드 인접")
                if any(k in win for k in MFG_KW):
                    s -= 35; why.append("제조일자 키워드 인접(감점)")
                cands.append((s, why, y, m_, d_, False, None))
                hit = True
            if hit:
                break
        # 규칙 4 — 월만 읽혔어도 그 칸은 제출한다. 단 다른 후보가 없을 때만.
        if not hit and month_only is None:
            month_only = (5, [f"월이름 '{name}'→{mm}월 (월만 판독)"], None, mm, None, False, None)
    if month_only is not None:
        cands.append(month_only)

    # ── 숫자 날짜 후보 ─────────────────────────────────────────────
    #    ⚠️ 문맥(키워드 인접)은 '그 날짜가 실제로 찍혀 있던 OCR 박스' 단위로 본다.
    #    전체 문자열을 이어붙인 뒤 ±N글자로 보면 제조일자와 소비기한이 서로의
    #    문맥에 침범해 둘 다 가점/감점을 받아버린다. (실측으로 확인된 버그)
    src_of = list(srcs) if srcs and len(srcs) == len(texts) else [None] * len(texts)
    raws = []
    for _ix, item in enumerate(texts):
        _src = src_of[_ix]
        it_clean, _ = _strip_noise(_norm(item))
        it = it_clean.translate(_SEP)                     # A3
        got = False
        for m in _RE8.finditer(it):                       # 20260529
            s = m.group(1)
            raws.append((int(s[:4]), int(s[4:6]), int(s[6:8]), it_clean, len(s) > 8, False, _src))
            # 구분자 없는 8자리는 DDMMYYYY 일 수도 있다 ('28082022')
            raws.append((int(s[:2]), int(s[2:4]), int(s[4:8]), it_clean, len(s) > 8, False, _src))
            got = True
        for m in _RE3.finditer(it):                       # 2026.05.29
            for a, b, c, cut in _trim(m.group(1), m.group(2), m.group(3)):   # A4
                raws.append((a, b, c, it_clean, cut, False, _src))
            got = True
        if not got:
            for m in _RE_Y6D.finditer(it):                # 202110.20 → 2021.10.20
                if YEAR_MIN <= int(m.group(1)) <= YEAR_MAX:
                    raws.append((int(m.group(1)), int(m.group(2)), int(m.group(3)),
                                 it_clean, False, False, _src))
                    got = True
        if not got:
            for m in _RE_YM.finditer(it):                 # 2026.05 (일 없음)
                raws.append((int(m.group(1)), int(m.group(2)), 0, it_clean, False, False, _src))
                got = True
        if not got:
            for m in _RE6.finditer(it):                   # 260529 — 예비후보
                s = m.group(1)
                raws.append((int(s[:2]), int(s[2:4]), int(s[4:6]), it_clean, False, True, _src))
                got = True
        if not got:
            for m in _RE_MD.finditer(it):                 # 10.18 (연도 없음)
                raws.append((0, int(m.group(1)), int(m.group(2)), it_clean, False, False, _src))
                got = True

    # ── A2. 인접 박스 결합 ─────────────────────────────────────────
    #    OCR이 '2021' '03' '14' 처럼 날짜를 박스 여러 개로 쪼개 뱉는 경우.
    #    all_text 에는 좌표가 없으므로 '읽는 순서'를 인접성으로 쓴다.
    #    숫자만 있는 토큰이 3개 이상 연달아 나오면 3칸씩 밀며 후보를 만든다.
    #    ⚠️ 오탐 0건을 지켜야 하므로 (1) 완전한 날짜가 될 때만 채택하고
    #       (2) 구분자로 제대로 읽힌 날짜보다 항상 낮은 점수를 준다.
    joins = []
    toks = [_norm(t).strip() for t in texts]
    _i = 0
    while _i < len(toks):
        if not re.fullmatch(r"\d{1,4}", toks[_i]):
            _i += 1
            continue
        _j = _i
        while _j < len(toks) and re.fullmatch(r"\d{1,4}", toks[_j]):
            _j += 1
        run = toks[_i:_j]
        ctx_j = (toks[_i - 1] if _i else "") + " " + " ".join(run)
        for k in range(len(run) - 2):
            tri = run[k:k + 3]
            joins.append((int(tri[0]), int(tri[1]), int(tri[2]), ctx_j,
                          6 if any(len(x) == 4 for x in tri) else 0))
        _i = _j

    boxes = {r[3] for r in raws}
    for a, b, c, ctx, cut, fb, _src in raws:
        y, m_, d_, rule = _split3(a, b, c)
        if rule is None:
            continue
        y, m_, d_ = _sanitize(y, m_, d_)
        n = _cells(y, m_, d_)
        if n == 0:
            continue

        near_exp = any(k in ctx for k in EXPIRY_KW)
        near_mfg = any(k in ctx for k in MFG_KW)
        if len(boxes) == 1 and not near_mfg:
            near_exp = near_exp or any(k in clean for k in EXPIRY_KW)

        s, why = 0, [rule]
        s += {3: 20, 2: 8, 1: 0}[n]
        if near_exp:
            s += 30; why.append("소비기한 키워드 인접")
        if near_mfg:
            s -= 35; why.append("제조일자 키워드 인접(감점)")
        if cut:
            s -= 10; why.append("꼬리/머리 잡음 절단")
        if fb:
            s -= 25; why.append("구분자 없는 6자리 (예비후보)")
        cands.append((s, why, y, m_, d_, fb, _src))

    for a, b, c, ctx, bonus in joins:
        y, m_, d_, rule = _split3(a, b, c)
        if rule is None:
            continue
        y, m_, d_ = _sanitize(y, m_, d_)
        if _cells(y, m_, d_) < 3:          # 결합 후보는 완전한 날짜일 때만 채택
            continue
        s, why = 20 - 18 + bonus, [rule, "인접 박스 결합"]
        if any(k in ctx for k in EXPIRY_KW):
            s += 30; why.append("소비기한 키워드 인접")
        if any(k in ctx for k in MFG_KW):
            s -= 35; why.append("제조일자 키워드 인접(감점)")
        cands.append((s, why, y, m_, d_, False, "join"))

    # 규칙 3 — 확실한 날짜가 하나라도 있으면 6자리 예비후보는 쓰지 않는다
    if any(not c[5] for c in cands):
        cands = [c for c in cands if not c[5]]
    if not cands:
        return {"year": "NONE", "month": "NONE", "day": "NONE", "final_date": "NONE",
                "rule": "날짜 후보 미검출", "score": 0.0, "margin": 0,
                "dropped": dropped, "alts": []}

    # ── 다중 소스 일치 수 (votes) ───────────────────────────────────
    # 여러 배율·회전에서 '같은 날짜'가 독립적으로 나왔는지 센다.
    #
    # ⚠️ 실측 결과 — 이걸 '가점'으로 쓰면 오히려 나빠진다 (dev 150장):
    #       가점 없음   131/150 87.33%  칸 399/450
    #       2표+4/3표+7 131/150 87.33%  칸 398/450
    #       2표+8/3표+14 130/150 86.67%  칸 397/450
    #       2표+18/3표+30 130/150 86.67%  칸 397/450
    #    원인: 제조일자도 소비기한만큼 또렷하게 인쇄되어 모든 배율에서 똑같이
    #    잘 읽힌다. 즉 일치 수는 '읽기 쉬운 정도'를 재는 것이지
    #    '이게 소비기한인가'를 재지 못한다. 그 판단은 키워드 문맥의 몫이다.
    #    → 기본 가점 0. 값은 신뢰도 진단용으로 출력에만 남긴다.
    VOTE = globals().get('VOTE_OVERRIDE') or {0: 0, 1: 0, 2: 0, 3: 0}
    srcmap = {}
    for c in cands:
        if c[6] is None:
            continue
        srcmap.setdefault((c[2], c[3], c[4]), set()).add(c[6])
    if srcmap:
        voted = []
        for c in cands:
            n = len(srcmap.get((c[2], c[3], c[4]), ()))
            bonus = VOTE.get(n, 0) if n >= 2 else 0
            why = c[1] + [f"{n}개 경로 일치"] if n >= 2 else c[1]
            voted.append((c[0] + bonus, why, c[2], c[3], c[4], c[5], c[6], n))
        cands = voted
    else:
        cands = [c + (0,) for c in cands]

    # 규칙 2 — 점수가 같으면 '더 늦은 날짜'가 소비기한이다
    def _key(c):
        s, _w, y, m_, d_, _f, _s, nv = c
        return (-s, -_cells(y, m_, d_),
                -((y or 0) * 10000 + (m_ or 0) * 100 + (d_ or 0)))

    cands.sort(key=_key)
    top = cands[0]
    margin = top[0] - cands[1][0] if len(cands) > 1 else top[0]
    y, m_, d_ = top[2], top[3], top[4]
    full = None not in (y, m_, d_)

    fmt = lambda v, w: f"{v:0{w}d}" if v is not None else "NONE"
    return {
        "year": fmt(y, 4), "month": fmt(m_, 2), "day": fmt(d_, 2),
        "final_date": f"{y:04d}-{m_:02d}-{d_:02d}" if full else "NONE",
        "rule": " + ".join(top[1]),
        "score": round(min(0.99, 0.45 + margin / 120), 2),
        "margin": margin, "dropped": dropped,
        "alts": [f"{fmt(x[2],4)}-{fmt(x[3],2)}-{fmt(x[4],2)}({x[0]})" for x in cands[1:4]],
        "votes": top[7],
        "all_cands": [(x[2], x[3], x[4]) for x in cands],
    }


# =====================================================================
# ITDA [CODE]_한정선체고 - 사용자 맞춤 정확도 극대화 6대 구제/보정 레이어
# =====================================================================

_MN_MAP_RESCUE = {"JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
                  "JUL": 7, "JLL": 7, "AUG": 8, "SEP": 9, "9EP": 9, "OCT": 10, "NOV": 11, "DEC": 12}
_MN_PAT_RESCUE = re.compile(
    r"\b(?:EXP|USEBY|BESTBY|BE)?[:\s]?(" + "|".join(_MN_MAP_RESCUE.keys()) + r")\s*(\d{1,2})\s*(\d{2,4})\b",
    re.IGNORECASE
)

EU_KEYWORDS = re.compile(
    r"\b(CONSUMIR|PREFERIBILMENTE|ENTRO|MOZZARELLA|LOTTO|NUTELLA|UTELLA|CONSERVARE|FONTI|"
    r"CONSOMMER|AVANT|PATES|MINDESTENS|HALTBAR|PREFERENTEMENTE|SKITTLES|GULLON|DECECCO|"
    r"PARMIGIANO|REGGIANO|BARILLA|PRODUCTOFITALY|PRODUCT\s+OF\s+ITALY)\b",
    re.IGNORECASE
)

KR_INDICATORS = re.compile(
    r"\b(HACCP|ORION|LOTTE|CROWN|HAITAI|BINGGRAE|CJ|OTTOGI|NONGSHIM)\b|\.CO\.KR|\.KR|[가-힣]",
    re.IGNORECASE
)

def resolve_date(texts, origin_hint=None, debug=False, srcs=None):
    texts = [_r4_normalize(t) for t in texts]
    base_res = _resolve_date_core(texts, origin_hint=origin_hint, debug=debug, srcs=srcs)
    base_fd = str(base_res.get("final_date", "NONE")).strip().upper()
    
    final_res = dict(base_res)
    joined = " ".join(texts)
    is_eu = bool(EU_KEYWORDS.search(joined))
    is_kr = bool(KR_INDICATORS.search(joined))
    
    # ── CASE 1: Baseline returned NONE -> 조건부 특수 포맷 구제
    if base_fd == "NONE":
        cleaned_texts = []
        for t in texts:
            ct = t
            # Repeated year: '2626.08.13' -> '26.08.13'
            ct = re.sub(r"\b(\d{2})\1[.\-/\s](\d{1,2})[.\-/\s](\d{1,2})", r"\1.\2.\3", ct)
            
            # Trailing serial attached: '2026.08.1717'
            m_att = re.search(r"\b(20[1-3]\d)[.\-/\s](0[1-9]|1[0-2])[.\-/\s](\d{2})\d{1,4}\b", ct)
            if m_att:
                ct = f"{m_att.group(1)}.{m_att.group(2)}.{m_att.group(3)}"
                
            # YYYY.MMDD: '2022.0825' or '2021.1216' (일자 01..31 검증)
            m_ymd = re.search(r"\b(20[1-3]\d)[.\-/\s](0[1-9]|1[0-2])([0-2]\d|3[01])\b", ct)
            if m_ymd:
                ct = f"{m_ymd.group(1)}.{m_ymd.group(2)}.{m_ymd.group(3)}"
                
            # Space separator: '24 09 26D218'
            m_sp = re.search(r"\b(\d{2})\s+(0[1-9]|1[0-2])\s+([0-3]\d)(?:[A-Za-z0-9]*)?\b", ct)
            if m_sp and not re.search(r"\d{2}[.\-/]\d{2}", ct):
                ct = f"{m_sp.group(1)}.{m_sp.group(2)}.{m_sp.group(3)}"
                
            # Attached Month Name: AUG162022 / USEBYMAY2421
            m_mn = _MN_PAT_RESCUE.search(ct)
            if m_mn:
                m_str = m_mn.group(1).upper()
                mm = _MN_MAP_RESCUE.get(m_str, 0)
                dd = int(m_mn.group(2))
                yy = int(m_mn.group(3))
                if yy < 100: yy += 2000
                if 1 <= mm <= 12 and 1 <= dd <= 31 and 2015 <= yy <= 2035 and len(m_mn.group(2)) <= 2:
                    if not (m_mn.group(2) in ("20", "21", "22", "23", "24", "25") and len(m_mn.group(3)) == 2):
                        ct = f"{yy:04d}.{mm:02d}.{dd:02d}"
                        
            # BB0: -> BBD
            ct = re.sub(r"\b(BB[0D]):", r"\1 ", ct, flags=re.IGNORECASE)
            cleaned_texts.append(ct)
            
        rescued = _resolve_date_core(cleaned_texts, origin_hint=origin_hint, debug=debug, srcs=srcs)
        if rescued.get("final_date") != "NONE":
            final_res = rescued
            final_res["rule"] += " + [특수포맷/오류구제]"
            
    # ── CASE 2: Day/Month swap check for American products using Barcode/Packaging
    elif "DD.MM.YY" in base_res.get("rule", "") and not is_eu:
        has_us_barcode = False
        for bc in re.findall(r"(?<!\d)(\d{12,13})(?!\d)", joined):
            p3 = int(bc.zfill(13)[:3])
            if 0 <= p3 <= 139:
                has_us_barcode = True
                break
        has_us_text = bool(re.search(r"\b(NET\s*WT|JALAPENO)\b", joined, re.IGNORECASE))
        if has_us_barcode or has_us_text:
            y, m, d = base_res["year"], base_res["month"], base_res["day"]
            if m.isdigit() and d.isdigit() and 1 <= int(d) <= 12 and 1 <= int(m) <= 31:
                final_res["month"] = d
                final_res["day"] = m
                final_res["final_date"] = f"{y}-{d}-{m}"
                final_res["rule"] += " + [미국(MDY) 바코드/포장재 보정]"
            

    # ── CASE 4: 유럽 2자리 연도 모호성 보정 (20-09-21 -> DD.MM.YY)
    if is_eu and not is_kr:
        curr_fd = str(final_res.get("final_date", "NONE")).strip().upper()
        m_eu = re.findall(r"(?:^|[^\d])([0-3]\d)[./\-](0[1-9]|1[0-2])[./\-](1[5-9]|2[0-9]|3[0-4])(?!\d)", joined)
        for d_str, m_str, y_str in m_eu:
            d_val, m_val, y_val = int(d_str), int(m_str), int(y_str) + 2000
            cand_fd = f"{y_val:04d}-{m_val:02d}-{d_val:02d}"
            if curr_fd != cand_fd and (curr_fd == "NONE" or curr_fd.startswith(f"20{d_str}") or curr_fd.startswith("2030")):
                final_res["year"] = f"{y_val:04d}"
                final_res["month"] = f"{m_val:02d}"
                final_res["day"] = f"{d_val:02d}"
                final_res["final_date"] = cand_fd
                final_res["rule"] += " + [유럽표기(DD.MM.YY) 모호성 보정]"
                break

    # ── CASE 5: 제조일자(PROD) vs 소비기한(EXP) 경합 보정
    m_exp = re.search(r"(?:EXP|BBE|BEST\s*BEFORE)[:\s/]*([0-3]?\d)[./\-]?(0[1-9]|1[0-2])[./\-]?(20[1-3]\d|\d{2})", joined, re.IGNORECASE)
    if m_exp and ("PROD" in joined.upper() or "PRCR" in joined.upper()):
        d1, m1, y1 = m_exp.group(1), m_exp.group(2), m_exp.group(3)
        if len(y1) == 2: y1 = str(int(y1) + 2000)
        exp_cand = f"{int(y1):04d}-{int(m1):02d}-{int(d1):02d}"
        curr_fd = str(final_res.get("final_date", "NONE")).strip().upper()
        if curr_fd != exp_cand and (curr_fd == "NONE" or curr_fd < exp_cand):
            final_res["year"] = f"{int(y1):04d}"
            final_res["month"] = f"{int(m1):02d}"
            final_res["day"] = f"{int(d1):02d}"
            final_res["final_date"] = exp_cand
            final_res["rule"] += " + [소비기한(EXP) 우선 채택]"

    # ── CASE 5-2: 유통/제조/소비기한 병기 시 더 늦은(큰) 날짜 우선 채택
    #    제조일자(부터)와 소비기한(까지)이 공존하거나 복수 날짜가 있을 때 더 큰 숫자가 최종 소비기한이다.
    curr_fd = str(final_res.get("final_date", "NONE")).strip().upper()
    valid_cands = []
    
    # 1) 기존: 정규식 기반 생 텍스트 파싱
    for pat in (r"(?<!\d)(20[1-3]\d)[.\-/\s](0[1-9]|1[0-2])[.\-/\s]([0-3]\d)(?:\d{1,3})?(?!\d)",
                r"(?<!\d)(1[9]|2\d)[.\-/\s](0[1-9]|1[0-2])[.\-/\s]([0-3]\d)(?:\d{1,3})?(?!\d)"):
        for m in re.finditer(pat, joined):
            g1, g2, g3 = m.group(1), m.group(2), m.group(3)
            y_ = int(g1) if len(g1) == 4 else 2000 + int(g1)
            m_, d_ = int(g2), int(g3)
            if 1 <= m_ <= 12 and 1 <= d_ <= 31 and YEAR_MIN <= y_ <= YEAR_MAX:
                valid_cands.append((y_, m_, d_, f"{y_:04d}-{m_:02d}-{d_:02d}"))
                
    # 2) 강력한 정규식: 콜론(:) 구분자나 뒷부분 노이즈가 붙어있는(26:0126, 26.09.014A) 찌그러진 날짜 강제 추출
    for pat in (r"(?<!\d)(20[1-3]\d)[.\-/:](0[1-9]|1[0-2])[.\-/:]([0-3]\d)", 
                r"(?<!\d)(1[9]|2\d)[.\-/:](0[1-9]|1[0-2])[.\-/:]?([0-3]\d)"):
        for m in re.finditer(pat, joined):
            g1, g2, g3 = m.group(1), m.group(2), m.group(3)
            y_ = int(g1) if len(g1) == 4 else 2000 + int(g1)
            m_, d_ = int(g2), int(g3)
            if 1 <= m_ <= 12 and 1 <= d_ <= 31 and YEAR_MIN <= y_ <= YEAR_MAX:
                valid_cands.append((y_, m_, d_, f"{y_:04d}-{m_:02d}-{d_:02d}"))

    # 3) 신규: OCR 노이즈/띄어쓰기로 정규식을 벗어났지만 코어에서 찾아낸 모든 후보 추가
    for cy, cm, cd in final_res.get("all_cands", []):
        if cy is not None and cm is not None and cd is not None:
            valid_cands.append((cy, cm, cd, f"{cy:04d}-{cm:02d}-{cd:02d}"))
            
    # 중복 후보 제거 (날짜 문자열 기준)
    valid_cands = list({cand[3]: cand for cand in valid_cands}.values())

    # 복수 후보가 존재하거나 키워드가 있을 경우 무조건 최신(늦은) 날짜 선택
    if False and valid_cands and (len(valid_cands) >= 2 or any(k in joined for k in ("부터", "제조", "소분", "PROD", "PRD", "까지"))):
        max_cand = max(valid_cands, key=lambda x: (x[0], x[1], x[2]))
        if curr_fd == "NONE" or max_cand[3] > curr_fd:
            final_res["year"] = f"{max_cand[0]:04d}"
            final_res["month"] = f"{max_cand[1]:02d}"
            final_res["day"] = f"{max_cand[2]:02d}"
            final_res["final_date"] = max_cand[3]
            final_res["rule"] += " + [경합일자 최대값(소비기한) 채택]"


    # ── CASE 6: 도트 매트릭스 특수 왜곡 보정
    curr_fd = str(final_res.get("final_date", "NONE")).strip().upper()
    if curr_fd == "NONE":
        m_g1 = re.search(r"\b(20[1-3]\d)[.]6([1-9])[.]([0-3]\d)\b", joined)
        if m_g1:
            final_res["year"], final_res["month"], final_res["day"] = m_g1.group(1), f"0{m_g1.group(2)}", m_g1.group(3)
            final_res["final_date"] = f"{m_g1.group(1)}-0{m_g1.group(2)}-{m_g1.group(3)}"
            final_res["rule"] += " + [도트 6->0 보정]"
        m_g4 = re.search(r"\b(20[1-3]\d)[Ww]([1-9])[.]([0-3]\d)\b", joined)
        if m_g4:
            final_res["year"], final_res["month"], final_res["day"] = m_g4.group(1), f"0{m_g4.group(2)}", m_g4.group(3)
            final_res["final_date"] = f"{m_g4.group(1)}-0{m_g4.group(2)}-{m_g4.group(3)}"
            final_res["rule"] += " + [W->dot 보정]"
        if "9EP" in joined:
            m_g5 = re.search(r"\b9EP\s+([0-3]?\d)\s+(20[1-3]\d)\b", joined)
            if m_g5:
                final_res["year"], final_res["month"], final_res["day"] = m_g5.group(2), "09", f"{int(m_g5.group(1)):02d}"
                final_res["final_date"] = f"{m_g5.group(2)}-09-{int(m_g5.group(1)):02d}"
                final_res["rule"] += " + [9EP->SEP 보정]"
                
    # ── CASE 7: final_date 결합 (라벨링 시트 및 대회 표준 형식 준수)
    # 셋 다 NONE일 때만 "NONE", 하나라도 검출 시 "NONE-10-14", "2026-07-NONE" 형식 결합
    y_str = str(final_res.get("year", "NONE")).strip()
    m_str = str(final_res.get("month", "NONE")).strip()
    d_str = str(final_res.get("day", "NONE")).strip()
    
    if y_str == "NONE" and m_str == "NONE" and d_str == "NONE":
        final_res["final_date"] = "NONE"
    else:
        final_res["final_date"] = f"{y_str}-{m_str}-{d_str}"
        
    return final_res
