"""results/*.summary.json 을 표로 모으고, 기준 대비 이미지 단위 득/실을 뽑는다."""
import os, sys, json, csv, glob
HERE = os.path.dirname(os.path.abspath(__file__))
gold = {r["image_id"].zfill(6): r for r in csv.DictReader(open(os.path.join(HERE, "gold_custom100.csv"), encoding="utf-8-sig"))}
def load(name):
    d = {}
    for line in open(os.path.join(HERE, "results", name + ".jsonl"), encoding="utf-8"):
        r = json.loads(line); d[r["image_id"]] = r
    return d
def ok(r, g): return all(r[k] == g[k] for k in ("year", "month", "day"))
names = sorted(os.path.basename(p)[:-13] for p in glob.glob(os.path.join(HERE, "results", "*.summary.json")) if "smoke" not in p)
base = sys.argv[1] if len(sys.argv) > 1 else "base_t0.30_b0.50_u1.6"
print(f"{'config':26} {'full':>9} {'full%':>7} {'cell%':>7} {'FP':>3} {'miss':>5} {'sec/장':>7} {'4core500':>9} {'stage0%':>8}  vs base")
B = load(base) if base in names else {}
for n in names:
    s = json.load(open(os.path.join(HERE, "results", n + ".summary.json")))
    d = load(n)
    gain = lose = 0
    if B:
        for iid, r in d.items():
            g = gold.get(iid); b = B.get(iid)
            if not g or not b: continue
            a, c = ok(r, g), ok(b, g)
            gain += (a and not c); lose += (c and not a)
    st0 = s["stages"].get("0", 0)
    print(f"{n:26} {s['full']:>4}/{s['n']:<4} {s['full_pct']:>7} {s['cells_pct']:>7} {s['false_positive']:>3} {s['miss_all_none']:>5} {s['sec_mean']:>7} {s['min_4core_500']:>8}m {100*st0/max(1,s['n']):>7.1f}%  +{gain}/-{lose}")
if len(sys.argv) > 2:
    n = sys.argv[2]; d = load(n)
    print(f"\n== {n} vs {base}: 득/실 이미지 ==")
    for iid in sorted(d):
        g = gold.get(iid); b = B.get(iid)
        if not g or not b: continue
        a, c = ok(d[iid], g), ok(b, g)
        if a != c:
            print(("GAIN " if a else "LOSE ") + iid, "gold", g["final_date"] if g["final_date"] != "NONE" else f"{g['year']}-{g['month']}-{g['day']}",
                  "| base", f"{b['year']}-{b['month']}-{b['day']}", f"st{b['stage']}", "| new", f"{d[iid]['year']}-{d[iid]['month']}-{d[iid]['day']}", f"st{d[iid]['stage']}")
