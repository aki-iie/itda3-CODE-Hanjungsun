#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────
# [CODE]_한정선체고 · 가중치 준비 스크립트
#
# 1) 가중치 다운로드: 필요 없음.
#    rapidocr-onnxruntime 휠에 PP-OCRv4 ONNX 모델 3개(검출 4.7MB · 인식 10.9MB ·
#    방향 0.6MB, 합계 16.2MB)가 포함되어 있어 pip install 만으로 오프라인 실행됩니다.
#    아래에서 번들 모델 존재를 확인만 합니다.
#
# 2) libGL 함정 방어 (헤드리스 채점 서버 대응):
#    rapidocr-onnxruntime 은 의존성으로 opencv-python(GUI 빌드)을 끌어오고, pip 설치
#    순서상 GUI 빌드가 opencv-python-headless 를 덮어씁니다. GUI 빌드는 libGL.so.1 이
#    없는 서버에서 `import cv2` 가 ImportError 로 죽습니다(정량 0점 경로).
#    그래서 여기서 headless 빌드를 마지막에 다시 설치해 최종 cv2 가 headless 가 되게 합니다.
#    (pip 캐시/네트워크가 없으면 경고만 남기고 넘어갑니다. 이미 headless 면 아무 일도 안 합니다.)
# ──────────────────────────────────────────────────────────────────────────
set -u
PY=${PYTHON:-python3}

echo "[weights] 번들 모델 확인"
$PY - <<'PY'
import os, glob, rapidocr_onnxruntime as R
d = os.path.join(os.path.dirname(R.__file__), "models")
fs = sorted(glob.glob(os.path.join(d, "*.onnx")))
assert len(fs) >= 3, f"번들 모델을 찾지 못함: {d}"
for f in fs:
    print(f"[weights]   {os.path.basename(f):40s} {os.path.getsize(f)/1e6:5.1f} MB")
print("[weights] OK — 다운로드 불필요 (휠 내장)")
PY

echo "[cv2] 최종 설치본이 headless 인지 확인"
if $PY - <<'PY'
import cv2, glob, os, sys
# GUI 빌드의 cv2 공유객체는 libQt5* 에 링크되어 있고, Qt5Gui 가 시스템 libGL.so.1 을 요구한다. headless 빌드에는 Qt 링크가 없다.
d = os.path.dirname(cv2.__file__)
so = glob.glob(os.path.join(d, "cv2*.so"))
gui = any(b"libQt5" in open(f, "rb").read() for f in so)
sys.exit(1 if gui else 0)
PY
then
  echo "[cv2] headless OK"
else
  echo "[cv2] GUI 빌드가 활성 → headless 로 재설치 시도"
  if $PY -m pip install -q --force-reinstall --no-deps opencv-python-headless==4.9.0.80; then
    echo "[cv2] headless 재설치 완료"
  else
    echo "[cv2] ⚠️ 재설치 실패(네트워크/캐시 없음). libGL 이 있는 환경이면 GUI 빌드로도 동작합니다."
  fi
fi
$PY -c "import cv2; print('[cv2] import OK', cv2.__version__)" 2>/dev/null | grep -v cpuid || echo "[cv2] ⚠️ import cv2 실패 — apt-get install -y libgl1 후 재시도"
