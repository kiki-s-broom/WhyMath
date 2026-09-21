# 테스트 표준

## 피라미드

```
       /\
      /UI\        ← E2E (적게)
     /----\
    / 통합  \      ← API·DB 통합 (중간)
   /--------\
  /  단위    \     ← 단위 테스트 (많이)
 /------------\
```

## 커버리지 목표

커버리지의 단일 진실은 **CI에서 실제로 차단(exit 1)되는 게이트**다. 두 축으로 강제한다 —
① **집계 하한**(패키지 전체) ② **계층별 하한**(백엔드 서브패키지). (2026-07-25 ARCH-14 ② '강화'
— 그동안 집계 70%만 강제되고 계층별 목표는 문서 선언만이던 불일치를, 계층별 게이트를 실제로
배선해 해소.)

### ① 집계 하한 (CI 차단 — 미달 시 exit 1)

| 대상 | 게이트 | 강제 위치 |
|---|---|---|
| 백엔드 (`whymath_backend`) | 집계 ≥ 70% | `ci.yml` `--cov-fail-under=70` |
| 데이터 파이프라인 (`data_pipeline` — L1) | 집계 ≥ 70% | `ci.yml` `--cov-fail-under=70` |
| 웹 수학 코어 (`src/lib/**`) | 라인·함수·분기·구문 ≥ 70% | `vitest.config.js` `thresholds` |
| Flutter (모바일) | 라인 ≥ 60% | `ci.yml` mobile 커버리지 게이트(awk) |

### ② 계층별 하한 (백엔드 서브패키지 게이트)

백엔드는 L2~L5가 한 패키지(`whymath_backend`)로 묶여 집계 70%만으로는 한 계층이 낮아도
평균에 묻힌다. 이를 막기 위해 **서브패키지별 라인 커버리지 바닥선을 별도 게이트로 강제**한다
(`scripts/coverage/check_layer_coverage.py` · `ci.yml` "계층별 커버리지 게이트" 스텝 · 집계와 상보).
바닥선의 **정본은 스크립트의 `LAYER_FLOORS`**다. 2026-07-25 CI 실측이 전 계층에서 선언 목표를
상회해(아래 '실측' 열) **바닥선 = 선언 목표**로 강제한다(즉 아래 목표치가 곧 CI가 차단하는 하한):

| 서브패키지 | 목표 = 강제 floor | 실측(2026-07-25) |
|---|---|---|
| 도메인 로직 `l4` | 90% | 95.2% |
| 데이터 `l1` | 80% | 86.7% |
| ML 모델 `l2` | 80% | 96.9% |
| LLM 통합 `l3` | 70% (모킹) | 95.4% |
| API `api` (L5) | 80% | 98.3% |
| Flutter UI | 60% (위젯·골든) | 86.6% (모바일 잡) |

백엔드 집계 실측은 92.83%. `l5`(상호작용·OCR/Manim 등 외부 의존)·`l6`·횡단(db·schema·ops·
privacy·whs)은 계층 게이트를 부여하지 않고 집계 70%로 커버한다(외부 의존 과다 또는 미선언).
목표(=floor)는 **하향 금지·상향만 허용**한다(점진 강화) — 커버리지가 목표 아래로 내려가면 red.

프로젝트 표준(CLAUDE.md "커버리지 70%+")의 집행이 위 게이트다.

## Python 테스트

```python
# pytest + pytest-asyncio
# 디렉토리: tests/

@pytest.fixture
async def db_session():
    """테스트용 DB 세션"""
    pass

@pytest.mark.asyncio
async def test_bkt_update(db_session):
    """BKT 업데이트 정상 동작"""
    # Given
    # When
    # Then
    pass
```

### 로컬 실행 — 호출 방식이 결과를 바꾼다 (OPS-61)

**CI와 같게 `src/backend`에서 bare로 부른다.** 명시 테스트 경로를 인자로 주면 pytest가 인자의
공통조상을 상향 탐색해 **저장소 루트를 `rootdir`로 잡고**, 루트 `pyproject.toml`에는 pytest 설정이
없어 `src/backend/pyproject.toml`의 `asyncio_mode = "auto"`가 **읽히지 않는다**(strict 폴백).
그러면 `async def` 테스트가 전부 실패한다 — 2026-09-05 실측으로 730 실패 중 **718건(98.4%)**이
이 형태였고, 같은 커밋의 CI는 11,727 passed·0 failed였다. **pin 버전과 무관하다.**

```bash
# ✅ CI와 동일 — rootdir=src/backend · asyncio_mode=auto
cd src/backend && python -m pytest -k "<필터>"; echo "EXIT=$?"

# ✅ 경로를 꼭 줘야 하면 설정을 명시로 고정
python -m pytest -c src/backend/pyproject.toml --rootdir=src/backend tests/backend/<경로>; echo "EXIT=$?"

# ❌ 함정 — 설정이 안 읽힌다(가드가 UsageError로 멈춘다)
cd src/backend && python -m pytest ../../tests/backend/<경로>
```

`tests/backend/conftest.py`의 `pytest_configure` 가드가 이 상태를 **1건의 즉시 실패**로 바꾼다 —
718건의 혼란 대신 원인을 지목하는 UsageError 하나다. 실행기는 `python -m pytest`로 못 박는다
(단독 `pytest` 금지 — 다중 환경에서 다른 인터프리터에 결합될 수 있다).

**CI 스텝도 같은 함정을 밟는다 (2026-09-06 · PR #1003 Codex P1).** 위 규칙은 로컬 전용이 아니다 —
`ci.yml`에는 `working-directory: src/backend`에서 `../../tests/backend/...`를 **위치 인자로** 주는
pytest 스텝이 3개 있었고(concept-reach 가드 · e2e 관통 · 앵커 A4), 전부 같은 이유로 backend ini가
통째로 안 읽힌 채 돌고 있었다. `asyncio_mode`뿐 아니라 `--strict-markers`·`--strict-config`·
`--import-mode=importlib`도 전부 빠진 상태였는데, **그 파일들에 async 테스트가 없어 초록으로 보였다**
— 즉 증상 없는 결함이었다. conftest 가드가 붙으면서 비로소 드러났다. 셋 다 `-c pyproject.toml`을
붙여 고쳤고(cwd가 `src/backend`이므로 상대 표기), 같은 형태의 재유입은
`tests/infra/test_backend_pytest_config_wiring.py`가 토큰 파싱으로 막는다.

> `--ignore=../../tests/backend/l3`처럼 **옵션의 값**으로 경로가 오는 형태는 위치 인자가 아니라
> 함정 대상이 아니다(실측 확인). 그래서 가드는 문자열 포함이 아니라 토큰 파싱으로 판정한다 —
> 문자열 검사였다면 이 스텝을 오탐했을 것이다.

**로컬 전체 스위트의 최소 의존성** — 위 함정을 제거하고도 남는 실패 12건(sync 10 + 판정 불가 2)은
전부 *컨테이너 의존성* 부재다(Ollama 데몬 · langfuse 클라이언트 · log formatter · 선택 extra의
`ImportError`). **CI에는 해당하지 않으며**(CI는 해당 서비스를 띄우거나 그 테스트를 skip한다) 별도
과제로 추적하지 않는다 — 로컬에서 전건 초록을 원하면 그 서비스들을 함께 띄운다.

## Flutter 테스트

```dart
// 위젯·골든·통합

testWidgets('PolyaStageIndicator highlights active', (tester) async {
  await tester.pumpWidget(
    ProviderScope(
      overrides: [...],
      child: MaterialApp(home: PolyaStageIndicator(...)),
    ),
  );
  expect(find.text('2. 계획'), findsOneWidget);
});

testGoldens('chat bubble layout', (tester) async {
  // 골든 테스트 — UI 회귀 방지
});
```

## LLM 호출 테스트

```python
# LLM은 *반드시* 모킹
@pytest.fixture
def mock_llm(monkeypatch):
    async def fake_generate(*args, **kwargs):
        return LLMResponse(text="모의 응답")
    monkeypatch.setattr("services.l3_llm.generate", fake_generate)
```

모킹은 *동작* 검증용이다 — **SDK 표면 정합**(우리가 호출하는 메서드가 pin 허용 범위의 *실물*
SDK에 존재하는가)은 모킹 테스트로 선언하지 않는다 (CLAUDE.md 절대 금기 "외부 SDK 표면을
시임 테스트만으로 정합 선언 금지" · `langfuse>=2.50,<5` 선례 — 2026-08-10 통합점검 부기).

## 부하 테스트 (Phase 2+)

- 도구: `locust` 또는 `k6`
- 시나리오: 동시 사용자 1,000명 채팅
- 목표: p99 < 3초
