"""
OCR 판독 사다리 (B군) — 검출 손실을 줄인다.

핵심 아이디어
  ① 검출은 작게, 인식은 원본 해상도로.
     원본 4032px 사진을 800px로 줄여 OCR에 넣으면 각인이 뭉개진다.
     작게 줄여 '글자 상자가 어디 있는지'만 찾고, 그 좌표를 원본으로
     되돌려 **원본 해상도에서 잘라내 다시 인식**한다.
  ② 실패했을 때만 축을 바꿔가며 사다리를 탄다.
     해상도만 계속 올리는 건 낭비다. 흐려서 못 읽는 건 확대해도 안 된다.

단계 (앞 단계에서 날짜꼴이 나오면 즉시 중단)
  0  전체를 800/1280/1920px 세 배율로 읽고 합침   ⬅ 배율 민감도가 무작위라서
  1  270/90/180 회전                    ⬅ 실측 적중률 1위(67%)라 앞으로 당김
  2  0단계 상자를 원본 해상도로 크롭 재인식
  3  전체 1920px (작은 원본은 2배 확대)
  4  대비 보정 + 언샤프                  실측 적중률 15%. 마지막 수단

⚠️ 순서 근거(봉인 200장 실측): 적중률 회전 67% > 크롭 50% > 확대 43% > 보정 15%.
   싸고 잘 맞는 것을 앞에 둬야 뒤 단계로 내려가는 장수 자체가 줄어든다.
"""
import re, time
import numpy as np
from PIL import Image, ImageOps, ImageFilter

DATE_ISH = re.compile(
    r"\d{1,4}\s*[./\-]\s*\d{1,2}\s*[./\-]\s*\d{1,4}"
    r"|(?<!\d)\d{6,8}(?!\d)"
    r"|(?i:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)"
)
NUM = re.compile(r"\d")

# 0단계에서 함께 읽을 배율 (실측 근거는 read() 주석 참고)
SCALES = (800, 1280, 1920)


def build(det_side=736):
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR()


def _pack(res, sx=1.0, sy=1.0, ox=0, oy=0, src="?"):
    """src: 이 결과가 나온 판독 경로 이름. 다중 소스 투표의 근거가 된다."""
    out = []
    for box, text, conf in (res or []):
        xs = [p[0] * sx + ox for p in box]
        ys = [p[1] * sy + oy for p in box]
        out.append({"text": text, "conf": round(float(conf), 3), "src": src,
                    "box": [int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))]})
    return out


def _hit(boxes):
    """엄격한 조기 종료 판정:
    단순한 숫자 파편(DATE_ISH)이 아니라, date_resolver가
    유효한 날짜(연/월/일이 모두 갖춰진 final_date)를 완성했을 때만 조기 종료한다.
    미완성 상태라면 다음 단계(회전, 이진화+팽창 등)로 사다리를 계속 탄다.
    """
    if not boxes:
        return False
    try:
        from date_resolver import resolve_date
        r = resolve_date([b["text"] for b in boxes], srcs=[b.get("src") for b in boxes])
        return r.get("final_date") != "NONE" and "NONE" not in (r.get("year"), r.get("month"), r.get("day"))
    except Exception:
        return any(DATE_ISH.search(b["text"]) for b in boxes)


def _cells_resolved(boxes):
    """판별기가 채운 칸 수 (0~3). 부분 날짜 조기 종료용."""
    if not boxes:
        return 0
    try:
        from date_resolver import resolve_date
        r = resolve_date([b["text"] for b in boxes], srcs=[b.get("src") for b in boxes])
        return sum(str(r.get(k)) != "NONE" for k in ("year", "month", "day"))
    except Exception:
        return 0


def _fit(im, side):
    r = side / max(im.size)
    if abs(r - 1.0) < 0.02:
        return im, 1.0
    return im.resize((max(1, int(im.width * r)), max(1, int(im.height * r))),
                     Image.LANCZOS), r


def _enhance(im):
    """대비 스트레치 + 언샤프. 잉크젯 각인·저대비 인쇄용."""
    g = ImageOps.autocontrast(im.convert("L"), cutoff=2)
    g = g.filter(ImageFilter.UnsharpMask(radius=2, percent=160, threshold=3))
    return g.convert("RGB")


def read(ocr, path, max_stage=4, deadline=None):
    """returns (boxes, stage, sec)"""
    t0 = time.time()
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    ow, oh = im.size

    def out_of_time():
        return deadline is not None and time.time() > deadline

    # ── 0단계: 여러 배율을 동시에 읽고 합친다
    #    ⚠️ 실측(dev150): 배율에 따른 판독 결과가 사실상 무작위다.
    #       000522는 1920px에서만, 001361은 800·1280px에서만, 000841은
    #       1600px에서만 정답이 나왔다. '좋은 배율' 하나를 고르는 건 불가능.
    #       그래서 조기 종료 없이 세 배율을 모두 읽고 후처리가 고르게 한다.
    #    ⚠️ 다만 1920px은 비싸다(장당 +2.5초). 원본이 작으면 3배 확대가 되는데
    #       실측상 2배 넘는 확대는 오히려 판독이 나빠졌다(001361). 그래서
    #       '2배 이하 확대'가 되는 배율만 쓴다. → 예산 44.7분 → 25분대
    boxes = []
    for side in SCALES:
        if side > 2 * max(ow, oh):
            continue
        sm, r = _fit(im, side)
        boxes += _pack(ocr(np.array(sm))[0], 1 / r, 1 / r, src=f"scale{side}")
        if _hit(boxes):
            break
        if out_of_time():
            break
    if _hit(boxes) or max_stage < 1 or out_of_time():
        return boxes, 0, time.time() - t0

    # ── 0.5단계: CLAHE 적용 후 1280px (난반사/음영 극복, 속도 개선 핵심)
    try:
        import cv2
        cv_img = np.array(im)
        lab = cv2.cvtColor(cv_img, cv2.COLOR_RGB2LAB)
        l_channel, a_channel, b_channel = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        cl = clahe.apply(l_channel)
        limg = cv2.merge((cl, a_channel, b_channel))
        clahe_img = Image.fromarray(cv2.cvtColor(limg, cv2.COLOR_LAB2RGB))
        
        c_sm, c_r = _fit(clahe_img, 1280)
        boxes += _pack(ocr(np.array(c_sm))[0], 1 / c_r, 1 / c_r, src="clahe1280")
        if _hit(boxes):
            return boxes, 0, time.time() - t0
    except Exception:
        pass

    # ── 1단계: 회전 (가장 잘 듣는 수단이므로 먼저)
    got = list(boxes)
    for ang in (270, 90, 180, 15, 345):
        rot, _ = _fit(im.rotate(ang, expand=True), 1280)
        got += _pack(ocr(np.array(rot))[0], src=f"rot{ang}")
        if _hit(got):
            return got, 1, time.time() - t0
        if out_of_time():
            return got, 1, time.time() - t0


    # ── 1.5단계: 적응형 이진화 + 팽창 연산 (도트 매트릭스 복원)
    try:
        import cv2
        cv_img = np.array(im)
        gray = cv2.cvtColor(cv_img, cv2.COLOR_RGB2GRAY)
        
        # 적응형 이진화: 조명 변화가 심한 패키지 표면에 유리 (글씨를 흰색으로 INV)
        binary = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 21, 10
        )
        
        # 팽창 연산: 점선으로 쪼개진 도트 잉크젯을 실선으로 잇는다
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        dilated = cv2.dilate(binary, kernel, iterations=1)
        
        # 다시 배경을 흰색, 글자를 검은색으로 반전
        inv_dilated = cv2.bitwise_not(dilated)
        
        dilated_img = Image.fromarray(inv_dilated).convert("RGB")
        d_sm, d_r = _fit(dilated_img, 1280)
        
        got += _pack(ocr(np.array(d_sm))[0], 1 / d_r, 1 / d_r, src="bin_dilate1280")
        if _hit(got):
            return got, 1.5, time.time() - t0
        if out_of_time():
            return got, 1.5, time.time() - t0
    except Exception:
        pass

    # ── 부분 날짜 조기 종료 (실측 V6): 연·월·일 중 두 칸 이상 채워졌으면 여기서 멈춘다.
    #    정답이 애초에 부분 날짜(2022-05-NONE 등)인 장은 완전한 날짜가 나올 수 없어
    #    사다리 끝(17~20초)까지 내려가던 낭비를 막는다. 300장 실측: 정확도 +1, 시간 −13%
    if max_stage < 2 or _cells_resolved(got) >= 2:
        return got, 1.5, time.time() - t0

    # ── 2단계: 0단계 상자를 원본 해상도로 크롭 재인식
    cands = [b for b in boxes if NUM.search(b["text"])] or boxes
    cands = sorted(cands, key=lambda b: -(b["box"][2] - b["box"][0]))[:6]
    for b in cands:
        x0, y0, x1, y1 = b["box"]
        pw, ph = (x1 - x0) * 0.35 + 12, (y1 - y0) * 0.9 + 12
        cx0, cy0 = max(0, int(x0 - pw)), max(0, int(y0 - ph))
        cx1, cy1 = min(ow, int(x1 + pw)), min(oh, int(y1 + ph))
        if cx1 - cx0 < 12 or cy1 - cy0 < 8:
            continue
        crop = im.crop((cx0, cy0, cx1, cy1))
        # 잘라낸 조각이 너무 작으면 키워서 인식
        if max(crop.size) < 480:
            k = 480 / max(crop.size)
            crop = crop.resize((int(crop.width * k), int(crop.height * k)), Image.LANCZOS)
            sx = sy = 1 / k
        else:
            crop, rc = _fit(crop, 1280)
            sx = sy = 1 / rc
        got += _pack(ocr(np.array(crop))[0], sx, sy, cx0, cy0, src="crop")
        if _hit(got):
            return got, 2, time.time() - t0
    if max_stage < 3 or out_of_time():
        return got, 2, time.time() - t0

    # ── 3단계: 전체 1920px (작은 원본은 확대). 0단계에서 이미 1920을 읽었으면 건너뜀
    if not any(b.get("src") == "scale1920" for b in boxes):
        big, r3 = _fit(im, 1920)
        got += _pack(ocr(np.array(big))[0], 1 / r3, 1 / r3, src="up1920")
        if _hit(got) or max_stage < 4 or out_of_time():
            return got, 3, time.time() - t0

    # ── 4단계: 대비 보정 + 언샤프
    en, re_ = _fit(_enhance(im), 1600)
    got += _pack(ocr(np.array(en))[0], 1 / re_, 1 / re_, src="enhance")
    return got, 4, time.time() - t0
