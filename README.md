# 소비기한 추출 파이프라인 — 제3회 ITDA 연합학술제 본선 · [CODE]_한정선체고

상품 뒷면 사진에서 소비기한을 추출해 `submission.csv`(`image_id, year, month, day, final_date`)로 출력한다.
사전학습 OCR(RapidOCR · PP-OCRv4 ONNX) + 판별기 연동 조기 종료 판독 사다리 + 결정론 날짜 판별기의 3계층 구조이며,
학습한 가중치 없음 · GPU 없음 · 유료 API 없음 · 실행 중 네트워크 접근 없음 · 추론 중 사람 개입 없음.

| | |
|---|---|
| 정확도(대표) | 규칙 설계·모델 선택에 쓰지 않은 제공 데이터 300장을 1회 개봉: 254/300 = **84.7%**, 칸 단위 89.0%, 오탐 1 (x86_64 Linux) |
| 정확도(자체 촬영) | 실제 매장 촬영 100장: 92/100 = 92.0%, 칸 단위 94.0%, 오탐 0 |
| 속도 | 장당 2.24초(1스레드, 중앙값 0.76초) → 4코어 500장 약 **4.7분** (상한 41.7분) |
| 자원 | 학습 0회 · GPU 0시간 · 유료 API 0원 · 가중치 16.2MB는 pip 휠에 내장 |

---

## 1. 가중치 다운로드 안내

별도 다운로드가 필요 없다. `rapidocr-onnxruntime` 휠 안에 PP-OCRv4 ONNX 모델 3개(검출 4.7MB · 인식 10.9MB · 방향 0.6MB, 합계 16.2MB)가 포함되어 있어 `pip install` 직후 인터넷이 차단된 환경에서도 바로 동작한다.
`download_weights.sh`는 ① 번들 모델의 존재를 확인하고, ② `rapidocr-onnxruntime`이 의존성으로 끌어오는 `opencv-python`(GUI 빌드, `libGL.so.1` 필요)이 `opencv-python-headless`를 덮어쓴 경우 headless 빌드를 다시 설치해 헤드리스 서버에서 `import cv2`가 실패하는 경로를 막는다. 가중치는 내려받지 않는다.
가중치 라이선스: PP-OCRv4 모델과 RapidOCR은 Apache-2.0 (PaddlePaddle/PaddleOCR, RapidAI/RapidOCR 저장소 LICENSE).

## 2. 환경 구축과 추론 실행 (본선 설명서 §2 절차)

권장 환경: Ubuntu 22.04 x86_64, Python 3.10, 4-Core CPU, GPU 없음. 모든 패키지는 `==`로 고정되어 있다.

```bash
python3.10 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
bash download_weights.sh
ITDA_INPUT_DIR=./sample ITDA_OUTPUT_PATH=/tmp/out.csv jupyter nbconvert --to notebook --execute predict.ipynb --output /tmp/executed.ipynb
```

- 반드시 저장소 루트에서 실행한다 (`predict.ipynb`가 `src/`를 상대 경로로 참조).
- 고정된 `nbconvert==7.16.4` / `nbclient==0.11.0`은 셀 타임아웃이 없으므로(`ExecutePreprocessor.timeout=None`) 위 명령 그대로 500장 실행이 가능하다. 다른 버전을 쓰는 경우에만 `--ExecutePreprocessor.timeout=2400`을 붙인다.
- 실행이 끝나면 노트북 마지막 셀이 출력 CSV를 자가 검증한다(헤더 · 행 수 · 컬럼 수 · 형식 · 실행 시간).
- 입력 폴더의 이미지는 `sorted()`로 순서를 고정하고 난수를 쓰지 않으므로 같은 환경에서 결과가 재현된다.

### 제출 전 검증 스크립트

`verify.sh`는 위 4개 명령을 새 가상환경에서 그대로 실행하고, 설치된 패키지 목록 · 노트북 셀 출력 · 결과 CSV · 판정을 `logs/verify_<일시>.log`에 남긴다.

```bash
bash verify.sh                      # 종료 코드 0 = 전 단계 성공 + 자가 검증 ALL PASS
PYTHON=python3.10 bash verify.sh    # python3.10 이 PATH 에 없으면 경로 지정
```

`logs/`에 실제 실행 로그가 들어 있다.

| 로그 | 환경 | 결과 |
|---|---|---|
| `logs/verify_20260928_153807.log` | Ubuntu x86_64, Python 3.10.20, 2코어 | 5장 / 5행, ALL PASS |
| `logs/run_sample_20260924.log` | macOS VM aarch64, Python 3.10.12, 4코어 | 5장 / 5행, ALL PASS |

## 3. 저장소 구조

```
.
├── predict.ipynb                 # 채점용 메인 노트북 (CONFIG 셀 원문 유지)
├── requirements.txt              # == 고정
├── download_weights.sh           # 번들 모델 확인 + headless cv2 보정 (다운로드 없음)
├── verify.sh                     # 본선 설명서 §2 절차를 새 가상환경에서 실행하고 logs/ 에 기록
├── README.md
├── .gitignore
├── src/
│   ├── runner.py                 # 이미지 1장 워커 (multiprocessing 자식이 import 가능하도록 모듈 파일)
│   ├── ocr/ocr_ladder.py         # OCR 판독 사다리 — 검출 손실 담당
│   └── postprocess/date_resolver.py   # 결정론 날짜 판별기 — 판별 손실 담당
├── sample/                       # 실행 확인용 샘플 5장 (부분 날짜 · 연월 표기 · 판독 불가 포함)
├── logs/                         # 새 가상환경 실행 로그와 출력 CSV
├── docs/파이프라인-로직-정리.md    # 전체 로직 · 예선 제출본 대비 변경 이력 · 설계 근거
├── custom_data/                  # 자체 촬영 100장 라벨 시트 (이미지는 README 의 드라이브 링크)
└── experiments/                  # 보고서 수치의 재현 스크립트와 결과 요약 (experiments/README.md)
    ├── gold300/                  # 규칙 조정용 300장: 임계값 7조합 · 사다리 V0~V6 · 판별기 R0~R4 비교
    ├── custom100/                # 자체 촬영 100장 검증 (미열람 1차)
    └── unseen300/                # 미사용 300장 검증 (미열람 2차, 대표 수치)
```

## 4. 파이프라인 요약

```
입력 → EXIF 회전 복원
     → [0] 800 → 1280 → 1920px 순차 판독. 판별기가 연·월·일 완전한 날짜를 내면 즉시 종료 (2배 초과 확대 금지)
     → [0.5] CLAHE → [1] 회전 270/90/180/15/345° → [1.5] 적응형 이진화+팽창
     → 두 칸 이상 채워진 부분 날짜는 여기서 종료
     → [2] 원본 해상도 크롭 재인식 → [3] 1920px(0단계에서 읽었으면 생략) → [4] 대비 보정+언샤프
     → 날짜 판별기: 형태 정규화 → 노이즈 제거 → 후보 생성(월명·숫자·인접 상자 결합)
                    → 형식 결정론 해석 → 칸 단위 검증 → 문맥 점수 → 정렬(점수 → 칸 수 → 동점 시 늦은 날짜)
     → submission.csv
```

- 시간 예산: 전역 2,100초(마진 300초), 장당 예산 = 남은 시간 ÷ 남은 장수. 예산이 빠듯하면 사다리가 스스로 얕아져 완주를 보장한다.
- 병렬: 4프로세스 × 1스레드(`OMP/ORT_NUM_THREADS=1`).
- 부분 날짜는 읽힌 칸만 기입한다(`2022-01-NONE`). 없는 날짜를 만들지 않는다.
- 2자리 연도 해석창은 `[올해−7, 올해+1]`이며 환경변수 `ITDA_YY_BACK`(기본 7) · `ITDA_YY_FWD`(기본 1)로 운영 환경에 맞게 조정할 수 있다. 채점 시에는 설정하지 않는다.

설계 근거와 실측 수치는 `docs/파이프라인-로직-정리.md`, 실험 전체는 `experiments/README.md`를 참고한다.

## 5. 예선 제출본 대비 변경 (전부 라벨 데이터 실측으로 채택)

| 변경 | 근거 |
|---|---|
| 판별기 CASE 5-2 `max([])` 크래시 가드 | 300장 중 3장이 예외로 통째 NONE |
| 「복수 후보면 무조건 늦은 날짜」(CASE 5-2) 비활성화 | 300장 +4, 개발150 +8, 봉인200 +2, 손실 0. 오독 변종·로트번호를 승격시키던 규칙 |
| OCR 원문 형태 정규화 5규칙 (연·월만 표기, 구분자 탈락 등) | 300장 +12, 개발150 +2, 봉인200 +1, 손실 0 |
| 부분 날짜 조기 종료 (이진화 단계 뒤) | 시간 −13%, 정확도 +1 |
| 3단계 1920px 중복 실행 제거 | 장당 2.5초 |
| 2자리 연도 해석창 하한을 상수 19에서 올해−7로 (2026년 결과 동일) | 실행 연도가 지나도 창 폭이 유지됨. 300장 재채점 264/300 동일 |
| 검출 임계값·조기종료 판정·배율 순차·CLAHE·이진화·±15° | 변경 없음 — 7개 임계값 조합 ±2건, 정규식 종료 −16, 3배율 상시 병합 −9로 현행이 최적임을 확인 |
