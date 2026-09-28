# 2자리 연도 해석창 하한 변경 검증 (2026-09-27)

변경: src/postprocess/date_resolver.py
- YY_LO = 19 (상수) → (THIS_YEAR - YY_BACK) % 100, YY_BACK 기본 7
- YY_HI = (THIS_YEAR + 1) % 100 → (THIS_YEAR + YY_FWD) % 100, YY_FWD 기본 1
- 환경변수 ITDA_YY_BACK / ITDA_YY_FWD 로 운영 시 조정 가능

검증: 신규 300장의 저장된 OCR 출력(V6_R4_fast_partial15, x86_64)에 대해 판별기만 재실행
- 변경 전: 창 [19, 27], 완전일치 264/300 (88.0%), 칸 단위 91.44%
- 변경 후: 창 [19, 27], 완전일치 264/300 (88.0%), 칸 단위 91.44%, 저장 결과와 다른 장 0
- 환경변수 반영 확인: ITDA_YY_BACK=2 ITDA_YY_FWD=3 → 창 [24, 29] (파라미터가 반영되는지만 확인)

2026년 실행에서는 두 경계가 이전과 같은 값으로 평가되므로 채점 결과에 영향이 없다.
