#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────
# [CODE]_한정선체고 · 제출 전 실행 검증
#
# 본선 설명서 §2 "제출 전 아래 절차를 새 가상환경에서 반드시 수행하고, 실행 로그를
# 저장소에 포함해 주세요"를 그대로 수행하고 logs/verify_<일시>.log 에 기록한다.
#
#   python3.10 -m venv .venv && source .venv/bin/activate
#   pip install -r requirements.txt
#   bash download_weights.sh
#   ITDA_INPUT_DIR=./sample ITDA_OUTPUT_PATH=/tmp/out.csv jupyter nbconvert --to notebook --execute predict.ipynb --output /tmp/executed.ipynb
#
# 사용: bash verify.sh            (저장소 루트에서. 기존 .venv 는 삭제 후 새로 만든다)
#       PYTHON=python3.10 bash verify.sh   (python3.10 이 PATH 에 없으면 경로 지정)
# 종료 코드: 0 = 전 단계 성공 + 노트북 자가 검증 ALL PASS, 1 = 실패
# ──────────────────────────────────────────────────────────────────────────
set -o pipefail
cd "$(dirname "$0")"
PY=${PYTHON:-python3.10}
# download_weights.sh 도 PYTHON 변수를 읽는다. 가상환경 밖 파이썬이 넘어가지 않도록 여기서 지운다.
unset PYTHON
STAMP=$(date +%Y%m%d_%H%M%S)
mkdir -p logs
LOG="logs/verify_${STAMP}.log"
OUT_CSV=/tmp/out.csv
OUT_NB=/tmp/executed.ipynb
rm -f "$OUT_CSV" "$OUT_NB"

{
  echo "# 본선 제출 전 실행 검증 로그 — $(date '+%Y-%m-%d %H:%M:%S')"
  echo "# 환경: $(uname -s) $(uname -m) / cpu $(nproc 2>/dev/null || sysctl -n hw.ncpu) / $($PY --version 2>&1)"
  echo "# 커밋: $(git rev-parse HEAD 2>/dev/null || echo '(git 미초기화)')"
  echo

  echo "\$ $PY -m venv .venv && source .venv/bin/activate"
  rm -rf .venv
  $PY -m venv .venv && source .venv/bin/activate || { echo "[FAIL] venv 생성 실패"; exit 1; }
  echo "  python: $(python --version 2>&1)  ($(command -v python))"
  echo

  echo "\$ pip install -r requirements.txt"
  pip install -r requirements.txt 2>&1 | grep -v -E "^\s*$|Requirement already|notice" | tail -n 20 || { echo "[FAIL] pip install 실패"; exit 1; }
  echo "  설치된 패키지(pip freeze):"
  pip freeze | sed 's/^/    /'
  echo

  echo "\$ bash download_weights.sh"
  bash download_weights.sh || { echo "[FAIL] download_weights.sh 실패"; exit 1; }
  echo

  # 노트북 커널을 이 가상환경의 파이썬으로 고정한다. 사용자 전역에 등록된 python3 커널
  # (다른 버전의 파이썬)이 대신 잡히면 노트북이 가상환경 밖에서 실행되기 때문이다.
  # 채점 명령은 그대로 두고, 커널 탐색 경로만 가상환경으로 맞춘다.
  python -m ipykernel install --prefix "$PWD/.venv" --name python3 --display-name "Python 3 (.venv)" >/dev/null 2>&1
  export JUPYTER_PATH="$PWD/.venv/share/jupyter"
  export JUPYTER_PREFER_ENV_PATH=1
  VENV_PYVER=$(python -c 'import platform; print(platform.python_version())')
  echo "# 노트북 커널: $(python -c 'import json,sys; print(json.load(open(sys.argv[1]))["argv"][0])' "$PWD/.venv/share/jupyter/kernels/python3/kernel.json") (Python $VENV_PYVER)"
  echo

  echo "\$ ITDA_INPUT_DIR=./sample ITDA_OUTPUT_PATH=$OUT_CSV jupyter nbconvert --to notebook --execute predict.ipynb --output $OUT_NB"
  T0=$(date +%s)
  ITDA_INPUT_DIR=./sample ITDA_OUTPUT_PATH=$OUT_CSV jupyter nbconvert --to notebook --execute predict.ipynb --output $OUT_NB 2>&1 || { echo "[FAIL] nbconvert 실행 실패"; exit 1; }
  echo "  소요 $(( $(date +%s) - T0 ))초"
  echo

  echo "# 노트북 셀 출력:"
  python - "$OUT_NB" <<'PY'
import json, sys
nb = json.load(open(sys.argv[1], encoding="utf-8"))
for c in nb["cells"]:
    for o in c.get("outputs", []):
        txt = "".join(o.get("text", [])) if o.get("output_type") == "stream" else ""
        if o.get("output_type") == "error":
            txt = "\n".join(o.get("traceback", []))
        for line in txt.rstrip("\n").splitlines():
            print("  " + line)
PY
  echo
  echo "# $OUT_CSV:"
  sed 's/^/  /' "$OUT_CSV"
  echo

  # 결과 판정: 자가 검증 ALL PASS + 행 수 = 샘플 수 + 노트북이 가상환경 파이썬에서 실행됨
  N_IMG=$(ls sample | grep -E -i '\.(jpg|jpeg|png)$' | wc -l | tr -d ' ')
  N_ROW=$(( $(wc -l < "$OUT_CSV") - 1 ))
  PASS=$(python - "$OUT_NB" <<'PY'
import json, sys
nb = json.load(open(sys.argv[1], encoding="utf-8"))
txt = "".join("".join(o.get("text", [])) for c in nb["cells"] for o in c.get("outputs", []) if o.get("output_type") == "stream")
print("1" if "[self-check] ALL PASS" in txt else "0")
PY
)
  if grep -q "\[env\] python=$VENV_PYVER " <(python - "$OUT_NB" <<'PY'
import json, sys
nb = json.load(open(sys.argv[1], encoding="utf-8"))
print("".join("".join(o.get("text", [])) for c in nb["cells"] for o in c.get("outputs", []) if o.get("output_type") == "stream"))
PY
); then KERNEL_OK=1; else KERNEL_OK=0; fi
  echo "# 커널 확인: 노트북 실행 파이썬 $([ "$KERNEL_OK" = 1 ] && echo "= 가상환경 Python $VENV_PYVER" || echo "≠ 가상환경 Python $VENV_PYVER (전역 커널이 잡힘)")"
  echo "# 판정: 샘플 ${N_IMG}장 / 출력 ${N_ROW}행 / 자가 검증 $([ "$PASS" = 1 ] && echo 'ALL PASS' || echo 'FAIL')"
  if [ "$PASS" = 1 ] && [ "$N_IMG" = "$N_ROW" ] && [ "$KERNEL_OK" = 1 ]; then
    echo "# 결과: PASS"
  else
    echo "# 결과: FAIL"; exit 1
  fi
} 2>&1 | tee "$LOG"
RC=${PIPESTATUS[0]}
cp -f "$OUT_CSV" "logs/out_${STAMP}.csv" 2>/dev/null
echo "로그: $LOG"
exit $RC
