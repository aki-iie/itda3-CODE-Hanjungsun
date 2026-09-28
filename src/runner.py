"""
이미지 1장을 처리하는 워커. **반드시 모듈 파일에 두어야 한다.**

⚠️ 실측 사고: 이 함수를 predict.ipynb 셀 안에 정의하고 multiprocessing
   spawn 으로 넘겼더니 채점 명령(nbconvert --execute)에서 이렇게 죽었다.

     AttributeError: Can't get attribute '_worker' on <module '__main__' (built-in)>

   노트북 셀에서 정의한 함수는 자식 프로세스가 이름으로 찾지 못한다.
   모듈에 두면 자식이 import 로 찾을 수 있다. 이걸 놓치면 정량 0점이다.
"""
import os
import sys
import time
import traceback

_OCR = None


def init_worker(repo_root):
    """자식 프로세스 초기화. 스레드 수를 1로 묶고 import 경로를 심는다."""
    for v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
              "NUMEXPR_NUM_THREADS", "ORT_NUM_THREADS"):
        os.environ[v] = "1"
    for p in (repo_root,
              os.path.join(repo_root, "src", "ocr"),
              os.path.join(repo_root, "src", "postprocess")):
        if p not in sys.path:
            sys.path.insert(0, p)


def run_one(args):
    """(path, image_id, per_image_budget_sec)
       → (image_id, year, month, day, final_date, stage, sec)"""
    global _OCR
    path, iid, budget = args
    t0 = time.time()
    try:
        import ocr_ladder as L
        from date_resolver import resolve_date
        if _OCR is None:
            _OCR = L.build(736)
        boxes, stage, _ = L.read(_OCR, path, deadline=t0 + budget)
        r = resolve_date([b["text"] for b in boxes],
                         srcs=[b.get("src") for b in boxes])
        return (iid, r["year"], r["month"], r["day"], r["final_date"],
                stage, round(time.time() - t0, 2))
    except Exception:
        # 한 장이 터져도 나머지를 전부 살린다. 실패 행은 NONE 으로 채운다.
        sys.stderr.write("[warn] %s\n%s" % (iid, traceback.format_exc(limit=2)))
        return (iid, "NONE", "NONE", "NONE", "NONE", -1, round(time.time() - t0, 2))
