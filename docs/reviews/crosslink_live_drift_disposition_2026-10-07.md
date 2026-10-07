# 라이브 crosslink 어긋남 처분 결정 기록 — 다) 보류 (2026-10-07)

> **판정 기준: main `42018d87`** (코퍼스 `data/corpus/misconception_crosslinks_v1/crosslinks.json` 68건) ·
> 조사 원문 = `docs/reviews/crosslink_live_drift_2026-10-07.md`(PR #1505, 이 기록 작성 시점 미머지).
> 게이트 `G-crosslink-live-drift-disposition`은 PR #1505에만 있어 이 브랜치에서 clear할 수 없다 — §4 참조.

## §1. 결정

**다) 보류** — Kiki 결정(2026-10-07, 세션 추천 수용). 오귀속 의심 4건을 지금은 지우지도 적재하지도 않는다.

**보류의 해제 조건(둘 중 먼저 오는 것)**: ① `WHYMATH_MISCONCEPTION_CROSSLINK_MODE`를 `shadow`로 켜기 전
② 코퍼스의 미적재 38건을 라이브에 올리기 전. 어느 쪽이든 **4행 삭제가 먼저**다(§3).

## §2. 근거 — 서버 설정 실측 (Kiki 머신 Phaiakes9, 읽기 전용)

조사 문서 §3이 "미확인"으로 남긴 서버 설정을 확인했다.

| 항목 | 출력 |
|---|---|
| 사용자 환경변수 `WHYMATH_MISCONCEPTION_CROSSLINK_MODE` | 비어 있음 |
| 시스템 환경변수 같은 이름 | 비어 있음 |
| `src\backend\.env`의 해당 줄 | 없음 (`run_demo.ps1`이 uvicorn을 `src\backend`에서 띄우므로 이 파일이 읽힌다) |
| `.demo_uvicorn.log`·`.demo_uvicorn.err.log`의 `crosslink_shadow` 기록 | 0건 (로그 파일은 존재) |
| 종합 `SHADOW_SUSPECT` | False |

저장소의 어떤 스크립트도 이 값을 설정하지 않는다. 그래서 서버는 기본값 `off`로 돌았고, 4행은 **학생 화면에도
측정 로그에도 닿지 않았다.** 남은 위험은 shadow/canary를 켜는 순간뿐이다.

**한계**: 서버를 띄운 창에서만 임시로 값을 넣은 경우는 환경변수 조회로 안 보인다. 로그 기록 0건이 그 경우를
배제하는 근거다. 단, 로그가 회전·삭제됐다면 과거 실행은 이 조회로 볼 수 없다.

## §3. 추가 검토에서 나온 사실 — 재적재는 이 4행을 고치지 못한다

조사 문서 §6은 4행 삭제와 대안 적재를 가)·나)로 나눴다. 코드를 보면 **적재만으로는 고칠 수 없다.**

- 적재기 `crosslink_loader.Store.populate`는 `(kebab_id, mis_id, link_type)` 키로 `ON CONFLICT DO UPDATE`
  업서트만 한다. **코퍼스에 없는 라이브 행은 지우지 않는다.**
- canonical 선택 `crosslink_resolve.select_canonical`은 직접매핑 중 **신뢰도가 단독 최대**인 행을 고르고,
  동률이면 미선정한다.
- 따라서 4행을 둔 채 코퍼스를 다시 적재하면(조사 문서 기재 값 기준):

| kebab | 라이브 잔존 | 코퍼스 적재분 | 적재 후 canonical |
|---|---|---|---|
| `angle-sum-non-triangle` | M0863 · 0.95 | M0493 · 0.85 | **M0863 — 틀린 쪽이 이긴다** |
| `period-of-scaled-sine` | M0862 · 0.95 | M0152 · 0.85 | **M0862 — 틀린 쪽이 이긴다** |
| `division-by-zero` | M0146 · 0.85 | M0003 · 0.85 | 동률 → 미선정 |
| `circle-radius-squared` | M0630 · 0.93 | M0848 · 0.93 | 동률 → 미선정 |

"코퍼스를 올려서 맞추자"는 가장 자연스러운 정리 행동이 정상처럼 끝나면서 오류는 그대로 남긴다. 그래서 해제 조건은
**삭제 선행**이다. 이 함정을 도구가 막도록 `HARN-216`을 등재했다(적재 전 canonical 시뮬 → 뒤집힘·동률이면 거부).
`HARN-215`(PR #1505)의 ③은 남는 행을 열거만 하고 이 경쟁은 판정하지 않으므로 두 태스크는 별개다.

**검증 범위(명시)**: 위 표는 코드 읽기와 조사 문서의 라이브 값으로 계산한 것이다. 라이브 DB에서 4행의
`link_type`이 모두 `직접매핑`인지는 조사 문서 기재(`division-by-zero`는 명시, 나머지는 신뢰도만 기재)에 기댄다.

## §4. 대장 반영 방법

게이트는 PR #1505가 머지된 뒤에 clear한다. 증적에 넣을 내용:

- 판정 기준 커밋 해시(머지 후 main)와 이 문서 경로
- 결정 = 다) 보류
- §2 실측 다섯 줄
- §1 해제 조건과 `HARN-216`
