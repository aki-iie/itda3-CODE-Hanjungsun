"""RapidOCR 검출 임계값 스위프 — gold_300 기준, 사람 개입 없음.
사용: python sweep.py --name base --thresh 0.3 --box 0.5 --unclip 1.6 [--workers 4] [--budget 16.8]
결과: results/<name>.jsonl (이미지별, 재개 가능) + results/<name>.summary.json
"""
import os, sys, json, csv, time, glob, argparse, multiprocessing as mp
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
for p in (ROOT, os.path.join(ROOT, "src"), os.path.join(ROOT, "src", "ocr"), os.path.join(ROOT, "src", "postprocess")):
    sys.path.insert(0, p)

_OCR = None
_CFG = {}

def _init(cfg):
    global _CFG
    _CFG = cfg
    for v in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS", "ORT_NUM_THREADS"):
        os.environ[v] = "1"

def _ocr():
    global _OCR
    if _OCR is None:
        from rapidocr_onnxruntime import RapidOCR
        _OCR = RapidOCR(det_thresh=_CFG["thresh"], det_box_thresh=_CFG["box"], det_unclip_ratio=_CFG["unclip"],
                        intra_op_num_threads=1, inter_op_num_threads=1)
    return _OCR

def _one(args):
    path, iid, budget = args
    t0 = time.time()
    try:
        import ocr_ladder as L
        from date_resolver import resolve_date
        boxes, stage, sec = L.read(_ocr(), path, deadline=t0 + budget)
        r = resolve_date([b["text"] for b in boxes], srcs=[b.get("src") for b in boxes])
        return {"image_id": iid, "year": str(r["year"]), "month": str(r["month"]), "day": str(r["day"]),
                "final_date": str(r["final_date"]), "rule": r.get("rule", ""), "stage": stage,
                "sec": round(time.time() - t0, 2), "boxes": boxes}
    except Exception as e:
        return {"image_id": iid, "year": "NONE", "month": "NONE", "day": "NONE", "final_date": "NONE",
                "rule": "ERROR " + repr(e)[:200], "stage": -1, "sec": round(time.time() - t0, 2), "boxes": []}

def score(rows, gold):
    n = full = cells = fp = miss = 0; secs = []; st = {}
    for r in rows:
        g = gold.get(r["image_id"].zfill(6)) or gold.get(r["image_id"])
        if not g: continue
        n += 1
        ok = all(r[k] == g[k] for k in ("year", "month", "day"))
        full += ok
        cells += sum(r[k] == g[k] for k in ("year", "month", "day"))
        pred_none = all(r[k] == "NONE" for k in ("year", "month", "day"))
        gold_none = all(g[k] == "NONE" for k in ("year", "month", "day"))
        if g["final_date"] == "NONE" and r["year"] != "NONE" and r["month"] != "NONE" and r["day"] != "NONE": fp += 1
        if pred_none and not gold_none: miss += 1
        secs.append(r["sec"]); st[str(r["stage"])] = st.get(str(r["stage"]), 0) + 1
    secs.sort()
    return {"n": n, "full": full, "full_pct": round(100 * full / max(1, n), 2), "cells_pct": round(100 * cells / max(1, 3 * n), 2),
            "false_positive": fp, "miss_all_none": miss, "sec_mean": round(sum(secs) / max(1, len(secs)), 2),
            "sec_median": secs[len(secs) // 2] if secs else None, "sec_max": secs[-1] if secs else None,
            "min_4core_500": round(sum(secs) / max(1, len(secs)) * 500 / 4 / 60, 1), "stages": st}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True); ap.add_argument("--thresh", type=float, default=0.3)
    ap.add_argument("--box", type=float, default=0.5); ap.add_argument("--unclip", type=float, default=1.6)
    ap.add_argument("--workers", type=int, default=4); ap.add_argument("--budget", type=float, default=16.8)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    cfg = {"thresh": a.thresh, "box": a.box, "unclip": a.unclip}
    gold = {r["image_id"].zfill(6): r for r in csv.DictReader(open(os.path.join(HERE, "gold_300.csv"), encoding="utf-8-sig"))}
    imgs = sorted(p for p in glob.glob(os.path.join(HERE, "images", "*")) if os.path.splitext(p)[1].lower() in (".jpg", ".jpeg", ".png"))
    if a.limit: imgs = imgs[:a.limit]
    out = os.path.join(HERE, "results", a.name + ".jsonl")
    done = {}
    if os.path.exists(out):
        for line in open(out, encoding="utf-8"):
            try: r = json.loads(line); done[r["image_id"]] = r
            except Exception: pass
    todo = [(p, os.path.splitext(os.path.basename(p))[0].zfill(6), a.budget) for p in imgs
            if os.path.splitext(os.path.basename(p))[0].zfill(6) not in done]
    print(f"[{a.name}] cfg={cfg} total={len(imgs)} done={len(done)} todo={len(todo)} workers={a.workers}", flush=True)
    t0 = time.time()
    if todo:
        ctx = mp.get_context("fork")
        with ctx.Pool(a.workers, initializer=_init, initargs=(cfg,)) as pool, open(out, "a", encoding="utf-8") as fh:
            for i, r in enumerate(pool.imap_unordered(_one, todo), 1):
                done[r["image_id"]] = r
                fh.write(json.dumps(r, ensure_ascii=False) + "\n"); fh.flush()
                if i % 20 == 0 or i == len(todo):
                    s = score(list(done.values()), gold)
                    print(f"  {i}/{len(todo)}  elapsed {time.time()-t0:.0f}s  running full={s['full']}/{s['n']} ({s['full_pct']}%)", flush=True)
    s = score(list(done.values()), gold); s.update({"name": a.name, "cfg": cfg, "budget": a.budget, "wall_sec": round(time.time() - t0)})
    json.dump(s, open(os.path.join(HERE, "results", a.name + ".summary.json"), "w"), ensure_ascii=False, indent=1)
    print("[summary]", json.dumps(s, ensure_ascii=False), flush=True)

if __name__ == "__main__":
    main()
