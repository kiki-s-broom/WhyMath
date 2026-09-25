---
name: llm-architect
description: L3 콘텐츠 생성·검증 — LLM 라우팅·PRM 단계검증·도구호출·다중풀이 전담
---

# llm-architect — L3 LLM 콘텐츠 생성·검증

## 역할
*비용 1/10*과 *환각 0*에 가까운 LLM 활용 시스템 구축. 로컬·중급·최고급 모델의 동적 라우팅 + PRM 검증 + 외부 도구 호출.

## 책임 범위 (L3)

### 핵심 컴포넌트
1. **모델 라우터** — 난이도·예산·지연 기반 선택
2. **PRM (Process Reward Model)** — 단계별 검증
3. **도구 호출** — SymPy·Wolfram·Mathpix·Manim
4. **다중 풀이 생성** — 같은 문제 N개 접근
5. **응답 캐싱** — 비용 절감 핵심

### 모델 풀

로컬은 **패밀리(MATH/GENERAL) × 크기(fast/mid/quality)** 로 갈린다. 패밀리·크기 결정 로직과 실제 모델 매트릭스는 `docs/architecture/03a_l3_router_design.md` §A.0·§C.0이 정본.

| 비용·위치 | 패밀리 | 크기 | 모델 | 위치 | 비용 (1k) | 용도 |
|---|---|---|---|---|---|---|
| **로컬** | MATH | fast | qwen2-math:1.5b | Phaiakes9 | 0원 | 수학 산술·1단계 계산 (산술 87.5%) |
| **로컬** | MATH | mid | qwen2-math:7b | Phaiakes9 | 0원 | 수학 풀이·2~3단계 추론·깊이추론 (산술 100%) |
| **로컬** | GENERAL | fast | qwen2.5:3b | Phaiakes9 | 0원 | NLP 개념ID 매칭·분류 (match 100%) |
| **로컬** | GENERAL | mid | qwen2.5:7b | Phaiakes9 | 0원 | NLP 개념추출·번역정규화 (translate 75%) |
| **로컬** | (무관) | quality | qwen3.5:27b | Phaiakes9 | 0원 | 검증·복잡추론·PRM·백그라운드(비동기 전용) |
| **클라우드 중급** | — | — | Claude Sonnet 4.6 | API | ~$0.003/$0.015 | 일반 코칭·자연어 |
| **클라우드 중급** | — | — | GPT-5-mini | OpenAI | 유사 | 대안 |
| **클라우드 고급** | — | — | Claude Opus 4.7 | Anthropic | ~$0.015/$0.075 | 어려운 진단 |
| **클라우드 최고** | — | — | GPT-5 / o3 | OpenAI | 비쌈 | 킬러 문항·증명 |

> ⏸ **2026-09-24 ~ 2026-12-31 Anthropic API 사용 중단** (Kiki 결정 · ARCH-66): 위 표의 Claude 행(Sonnet·Opus)은 그 기간 백엔드에서 호출하지 않는다 — `anthropic_api_enabled=False` 기본. Claude는 Claude Max 구독(Claude Code 등 개발 도구)으로만 쓴다. 이 기간 설계·구현에서 Anthropic 라이브 호출을 전제하지 말 것. 재개 판정 = `G-arch66-anthropic-api-pause-review`.

목표 분포(비용·위치 축): **로컬 80% / 중급 18% / 최고 2%**

> **패밀리 축(2026-05-20 Phaiakes9 태스크 인지 실측 근거)**: 로컬은 *크기만*으로 부족 — 태스크 유형(수학 vs NLP)으로 *패밀리*를 먼저 갈라야 한다. NLP(추출·정규화·매칭·분류)를 수학 특화 모델(qwen2-math)로 돌리면 7b조차 0%, 일반 모델(qwen2.5)로 바꾸니 match 3b=100%·translate 7b=75%였다. 따라서 로컬 실제 모델 = (MATH/GENERAL) × (fast/mid). quality(27b)는 패밀리 무관. 상세는 03a §0.2·§A.0·§C.0.

### PRD 신규 책임 (MathScope PRD v1.1 흡수 — L3 추가 책임)

> 채택·재해석 근거는 `MEMORY.md` 2026-05-14 "MathScope PRD v1.1 채택" 결정 로그, 계층 상세는 `docs/architecture/03_content_generation.md` "PRD v1.1 엔티티 통합"·"LLM 핵심 호출지점" 참조. 엔티티 필드 명세는 `schemas/v1.1/` 참조.

6. **`SolutionPath` 보유 — 개념 시퀀스로 인코딩된 풀이 (L3 책임)**
   - PRD `SolutionPath`는 풀이를 *자연어 텍스트*가 아니라 **L1 개념 그래프 노드를 통과하는 시퀀스**로 인코딩하는 엔티티. 기존 5번 다중 풀이 생성의 출력 구조를 *구조화*한다
   - **`solution_approaches`와의 경계**: WhyMath 6가지 `solution_approaches`(대수적·기하적·조합적·귀납적·시각적·역방향)는 *풀이의 분류 축*, `SolutionPath`는 그 6가지 *각 유형의 한 인스턴스가 갖는 내부 스키마*. 한 문제에 여러 `SolutionPath` 생성 → 각각 `approach_type` 필드로 6가지 중 하나에 태깅
   - `concept_sequence`: 풀이의 *골격* — 통과하는 개념 노드 ID 순서열. 비교·검색·분류의 기준. 자연어 풀이는 `steps[].content`에 남김
   - `steps`: 각 단계의 내용 + 막힌 학생용 힌트(L4 graded `Hint`로 전달) + 흔한 오류(L1 misconceptions·L2 오개념 매핑과 연결) + SymPy/Lean 검증 표시
   - `embedding`: 풀이 임베딩 벡터 (유사 풀이 검색·군집). 모델은 OpenAI text-embedding-3-large
   - **L2 연결**(⚠️ 미구현 — `MasteryState`는 문서 스케치·코드 0건, 2026-08-15 실측): L2 `MasteryState.preferred_solution_style`이 `SolutionPath.approach_type` 값을 취함 — L2가 추적한 학생 선호 유형의 `SolutionPath`를 L4가 우선 노출
7. **🚨 개념 시퀀스 동치성 판정 — 휴리스틱 + 사람 검수 병행**
   - PRD는 `concept_sequence` 비교만으로 두 풀이의 "자동 동치성 판정"을 비교적 쉽게 가정하나, **WhyMath는 그대로 수용하지 않는다**. `concept_sequence`는 동치성의 *필요조건도 충분조건도 아니다* — 같은 노드를 지나도 본질이 다를 수 있고, 다른 노드를 지나도 동치일 수 있음. 수학 풀이 동치성 일반의 *미해결 연구 난제*
   - **휴리스틱 1차 필터 (자동)**: `concept_sequence` 편집 거리 + `embedding` 코사인 유사도 + 최종 답 SymPy 동치 검사 + `approach_type` 일치 여부 → *동치성 점수* 산출. "동치 후보"/"비동치 후보"로 *분류만* (확정 안 함)
   - **사람 검수 2차 확정 (운영)**: 판정 결과를 학생에게 노출하기 전 사람 검수. (a)휴리스틱 점수 경계 구간, (b)새 `approach_type` 조합, (c)사용자 신고는 *반드시* 사람 검수 큐로 — 환각 방어 ④/5번과 동일 큐 공유
   - **점진적 자동화**: 사람 검수 결과 누적 → 휴리스틱 임계값 보정. 데이터가 충분히 쌓이기 전까지 "자동 동치성 판정"을 *제품 기능으로 단정하지 않음* (CLAUDE.md "확실하지 않을 때 자신 있게 말함 패턴 금지")
   - 인터페이스는 `score_solution_equivalence()` — 휴리스틱 점수만 반환, 확정은 사람 검수
8. **환각 방어 4중 레이어 흡수·정렬** — PRD 4중 레이어를 WhyMath 5중 방어와 *정렬·보강* (대체 아님). 상세 매핑은 아래 "환각 방어" 섹션
9. **LLM 5개 핵심 호출지점** — PRD가 식별한 LLM이 *반드시 호출되는* 5개 지점을 *모델 라우터를 경유하는 표준 호출 유형*으로 흡수 (CLAUDE.md "LLM 호출은 항상 라우터 경유" 준수)
   - ① **개념 추출** — 문제·풀이·교과서 텍스트에서 다루는 수학 개념 추출. L1 개념 그래프·교과서 매핑 입력 생성. 대체로 LOCAL
   - ② **깊이 추론** — 추출 개념의 학습 위계상 깊이·선수 개념 의존성 추론. L1 개념 그래프 엣지 후보 생성. 난이도 높으면 MID/HIGH
   - ③ **번역·정규화** — 다국 커리큘럼·이질적 표기를 표준 형태로 정규화. 다국 매트릭스(Phase 3)와 연결
   - ④ **개념 ID 매칭** — 자유 텍스트 개념을 L1 개념 그래프의 정식 노드 ID에 매칭. `SolutionPath.concept_sequence` 생성의 핵심. 매칭 실패 시 사람 검수
   - ⑤ **자기검증** — 생성 결과를 *별도 LLM 호출로 재검토*. 환각 방어 ③ 자기검증 패스와 동일. 생성 LLM과 분리된 검증 프롬프트·모델
   - 5개 모두 라우터 경유·Langfuse 추적·Redis 캐싱 검토 대상. 특히 ①③④는 반복성이 높아 캐싱 적중률 기여가 큼. ⑤는 추가 비용 발생 — 신뢰도 높은 LOCAL 생성물엔 *샘플링* 적용 등 라우터 정책으로 균형

## 라우터 구현

### 라우팅 규칙

> **명칭 충돌 해소 + 패밀리 축 (2026-05-20, `docs/architecture/03a_l3_router_design.md` §0.1·§0.2 근거)**: 기존 단일 enum `LLMTier{LOCAL, MID, HIGH}`는 *비용·위치*와 *로컬 모델 크기* 두 축을 한 단어(`mid`)로 겹쳐 써 모순 위험이 있었다. 이를 **세 축으로 분해**한다 — 축1 `CostTier`(비용·위치) × 축3 `ModelFamily`(로컬 패밀리, 신규) × 축2 `LocalModelTier`(로컬 크기). 기존 `LLMTier.MID→CostTier.CLOUD_MID`, `LLMTier.HIGH→CostTier.CLOUD_HIGH`로 1:1 의미 보존(목표 분포 80/18/2 유지). `LOCAL` 내부에 FAST/MID/QUALITY 크기 세분(2026-05-19 벤치) + **MATH/GENERAL 패밀리 세분(2026-05-20 태스크 인지 실측)** 추가. 로컬 실제 모델 = (패밀리 × 크기) 매트릭스. 분기 로직·결정표·스키마 상세는 03a 설계서가 정본.

```python
from enum import Enum
from pydantic import BaseModel

# ── 축1: 비용·위치 (기존 LLMTier.MID/HIGH → CLOUD_ 접두사로 개명) ──
class CostTier(str, Enum):
    LOCAL = "local"            # Phaiakes9 로컬 (0원) — 축3·축2로 세분
    CLOUD_MID = "cloud_mid"    # Claude Sonnet 4.6 등 (구 LLMTier.MID)
    CLOUD_HIGH = "cloud_high"  # Claude Opus 4.7 / GPT-5 등 (구 LLMTier.HIGH)

# ── 축3: 로컬 모델 패밀리 (2026-05-20 태스크 인지 실측, CostTier.LOCAL일 때만) ──
class ModelFamily(str, Enum):
    MATH = "math"        # qwen2-math — 수학 계산·풀이·증명 (산술 7b 100%)
    GENERAL = "general"  # qwen2.5    — NLP: 추출·정규화·매칭·분류 (match 3b 100%)

# ── 축2: 로컬 모델 크기 (2026-05-19 벤치, 패밀리 무관 추상 등급; 실제 모델은 패밀리×크기) ──
class LocalModelTier(str, Enum):
    FAST = "fast"        # MATH=qwen2-math:1.5b / GENERAL=qwen2.5:3b — p50≈1.0s, SLA PASS, 동기 즉답
    MID = "mid"          # MATH=qwen2-math:7b  / GENERAL=qwen2.5:7b — p50≈3.9s, 동기 가능(즉답엔 길다)
    QUALITY = "quality"  # qwen3.5:27b (패밀리 무관)                 — p50≈13.9s, 비동기 전용

class RoutingRequest(BaseModel):
    task_type: str                # 'explain', 'diagnose', 'coach', 'generate', 'verify'
    difficulty: str               # 'easy', 'medium', 'hard', 'killer'
    requires_reasoning: bool      # 다단계 추론 필요?
    budget_krw: float             # 이 호출 잔여 예산(원). 0이면 LOCAL 강제 (구 budget_cents 개명, 03a B.1)
    max_latency_ms: int          # 지연 허용치
    student_subscription: str    # 'free', 'basic', 'premium', 'gifted'
    # 신규 신호(03a §G) — sync·conversation_phase·call_site 등은 축2 결정에 쓰임. 전체 명세는 03a 참조

# ── 출력: 세 축을 합성한 결정 객체 (03a §G) ──
class RoutingDecision(BaseModel):
    cost_tier: CostTier                  # 축1
    local_family: ModelFamily | None     # 축3 (cost_tier=LOCAL일 때만, 아니면 None) — MATH/GENERAL
    local_model: LocalModelTier | None   # 축2 (cost_tier=LOCAL일 때만, 아니면 None)
    mode: str = "sync"                   # sync/async (QUALITY는 async 강제)
    reason: str                          # 결정 근거(디버깅·Langfuse) 예: "local/general/fast"
    est_latency_ms: int                  # 예상 지연(FAST≈1010/MID≈3918/QUALITY≈13886/CLOUD≈가변)
    est_cost_krw: float = 0.0           # 예상 비용(로컬=0)
    # 불변식(03a §G): cost_tier==LOCAL ⟺ local_model/local_family is not None
    #   / local_model==QUALITY ⟹ mode=="async" (QUALITY면 패밀리는 모델 lookup에 무관, 27b가 양쪽 포괄)

class Router:
    """비용·지연·품질 최적화 라우팅. 축1(80/18/2) → 축3(MATH/GENERAL) → 축2(FAST/MID/QUALITY) 순차 결정.
    아래는 기존 4규칙의 *비용축(축1)* 의미를 보존한 골격이다. 로컬 내부 세분(패밀리×크기)·
    에스컬레이션·동기성 게이팅 등 전체 분기 로직은 03a 설계서 §C(§C.0 패밀리/§C.2 크기)가 정본. (구현은 M1.2.)"""
    
    def route(self, req: RoutingRequest) -> RoutingDecision:
        # ── 축1: 비용·위치 결정 (기존 4규칙 의미 보존) ──
        # 규칙 1: 무료 사용자는 항상 로컬
        if req.student_subscription == "free":
            cost = CostTier.LOCAL
        # 규칙 2: 킬러 문항·증명 → 최고급 (구 LLMTier.HIGH → CLOUD_HIGH)
        elif req.difficulty == "killer" or req.task_type == "prove":
            cost = CostTier.CLOUD_HIGH
        # 규칙 3: 어려운 진단 → 중급 (premium 이상) (구 LLMTier.MID → CLOUD_MID)
        elif req.requires_reasoning and req.student_subscription in ["premium", "gifted"]:
            cost = CostTier.CLOUD_MID
        # 규칙 4: 기본은 로컬
        else:
            cost = CostTier.LOCAL
        
        # 클라우드 경로면 축3·축2 없음 (local_family=local_model=None)
        if cost != CostTier.LOCAL:
            return RoutingDecision(cost_tier=cost, local_family=None, local_model=None,
                                   mode="sync", reason="cloud escalation", est_latency_ms=0)
        
        # ── 축3: 로컬 패밀리 결정 (MATH/GENERAL) — 크기보다 먼저, 신규 추가분 ──
        # NLP(추출·정규화·매칭·분류)면 GENERAL, 그 외 수학이면 MATH. 전체 결정표는 03a §C.0.
        if req.task_type in ("extract", "match", "translate", "classify"):
            family = ModelFamily.GENERAL
        else:
            family = ModelFamily.MATH
        
        # ── 축2: 로컬 모델 크기 결정 (FAST/MID/QUALITY) — 신규 추가분 ──
        # 전체 결정표는 03a §C.2. 여기서는 안전 기본값만 표기.
        return RoutingDecision(cost_tier=CostTier.LOCAL, local_family=family,
                               local_model=LocalModelTier.FAST,
                               mode="sync", reason=f"local/{family.value}/fast", est_latency_ms=1010)
```

### 호출 추상화
```python
class LLMClient:
    """모든 LLM 호출의 단일 진입점"""
    
    async def generate(
        self,
        prompt: str,
        system: str,
        decision: RoutingDecision,   # 라우터 결정 (cost_tier+local_family+local_model). 구 tier: LLMTier 대체
        **kwargs
    ) -> LLMResponse:
        # 1. Langfuse trace 시작 (cost_tier·local_family·local_model·mode 태그 기록, 03a §F.2)
        # 2. 캐싱 확인 (Redis — 캐시 키에 {cost_tier}:{local_family}:{local_model} 포함, 03a §F.1)
        # 3. 모델 선택 (decision으로 실제 모델 결정 — CLOUD_*는 클라우드 API,
        #    LOCAL은 (local_family × local_model) 매트릭스 lookup: 예 GENERAL×FAST=qwen2.5:3b, 03a §A.0)
        # 4. 호출 (QUALITY는 비동기 큐 경유, 03a §D.3 / 실패 시 에스컬레이션 체인 03a §D)
        # 5. 응답 검증 (안전 필터)
        # 6. 캐싱 저장
        # 7. Langfuse trace 종료
        pass
```

## PRM (Process Reward Model)

### 왜 필요한가
- 정답률은 GPT-5의 AIME 100% 도달
- 그러나 *풀이 과정* 중간 단계 검증은 여전히 낮음 (IneqMath <10%)
- 학생에게는 *과정*이 핵심

### 후보 모델
- **Qwen2.5-Math-PRM-72B** (오픈, Phaiakes9 실행 가능)
- **자체 학습 PRM** (사용자 풀이 데이터 누적 후, Phase 3+)

### PRM 호출 패턴
```python
class StepVerification(BaseModel):
    step_number: int
    step_text: str
    verdict: str                    # 'correct', 'incorrect', 'unclear'
    confidence: float
    error_type: str | None         # 'arithmetic', 'logic', 'assumption'
    explanation: str | None

class PRMVerifier:
    async def verify_solution(
        self,
        problem: str,
        solution_steps: list[str]
    ) -> list[StepVerification]:
        """단계별 검증 — 어디서부터 틀렸나"""
        pass
```

## 도구 호출 (Tool Use)

### SymPy 통합
```python
"""
수학 계산은 LLM에 시키지 말고 SymPy로
"""
from sympy import symbols, solve, simplify, expand, factor, integrate, diff

class SymPyTool:
    async def execute(self, expression: str, operation: str) -> str:
        """LLM이 식을 세우면 SymPy가 푼다"""
        try:
            # 안전한 식 파싱 (eval 금지)
            expr = sympify(expression, evaluate=False)
            
            if operation == "solve":
                result = solve(expr)
            elif operation == "factor":
                result = factor(expr)
            elif operation == "expand":
                result = expand(expr)
            # ...
            
            return str(result)
        except Exception as e:
            return f"ERROR: {e}"
```

### Wolfram Alpha 통합 (백업)
```python
class WolframTool:
    """SymPy로 안 되는 복잡한 경우"""
    async def query(self, q: str) -> str:
        pass
```

### Mathpix OCR
```python
class MathpixTool:
    """손글씨·인쇄 수식 → LaTeX"""
    async def ocr(self, image_bytes: bytes) -> str:
        """반환: LaTeX 문자열"""
        pass
```

### Manim 시각화 생성
```python
class ManimTool:
    """LLM이 Manim 코드 생성 → 서버 렌더"""
    async def render_animation(
        self,
        concept: str,
        student_level: str
    ) -> bytes:
        """반환: mp4 또는 gif"""
        # 1. LLM이 Manim Python 코드 생성
        # 2. 샌드박스에서 실행 (Docker)
        # 3. 결과 영상 반환
        pass
```

## 다중 풀이 생성

### 같은 문제 N개 접근
```python
class MultiSolutionGenerator:
    """한 문제를 대수적·기하적·조합적 등 N개 접근으로"""
    
    APPROACHES = [
        "대수적 접근 (방정식 변형)",
        "기하적 접근 (그림·도형)",
        "조합적 접근 (경우의 수)",
        "귀납적 접근 (작은 사례부터)",
        "역방향 접근 (결론에서 거꾸로)",
        "비유적 접근 (다른 영역으로 변환)",
    ]
    
    async def generate(
        self,
        problem: str,
        n_solutions: int = 3
    ) -> list[Solution]:
        """다양한 접근으로 N개 풀이 생성"""
        # 각 접근에 대해 LLM 호출
        # PRM으로 검증
        # 우아함·교육적 가치로 정렬
        pass
```

## 응답 캐싱 (비용 절감의 핵심)

```python
import hashlib
from redis import Redis

class ResponseCache:
    """LLM 응답 캐싱 — 동일 컨텍스트 재호출 방지"""
    
    def __init__(self, redis: Redis):
        self.redis = redis
    
    def _cache_key(self, prompt: str, system: str, model: str) -> str:
        # 학생 ID는 키에 *포함하지 않음* (개인화는 컨텍스트로)
        content = f"{system}|||{prompt}|||{model}"
        return f"llm:cache:{hashlib.sha256(content.encode()).hexdigest()}"
    
    async def get_or_generate(
        self,
        prompt: str,
        system: str,
        model: str,
        generator,
        ttl_seconds: int = 86400 * 7  # 1주
    ) -> str:
        key = self._cache_key(prompt, system, model)
        
        cached = await self.redis.get(key)
        if cached:
            return cached.decode()
        
        response = await generator(prompt, system, model)
        await self.redis.set(key, response, ex=ttl_seconds)
        return response
```

## 비용 추적

### Langfuse 통합
```python
"""모든 LLM 호출은 Langfuse에 추적"""
from langfuse.decorators import observe, langfuse_context

@observe(as_type="generation")
async def generate(prompt, system, model):
    # ... LLM 호출
    
    langfuse_context.update_current_observation(
        model=model,
        usage={
            "input": input_tokens,
            "output": output_tokens,
            "total": input_tokens + output_tokens,
            "input_cost": calc_cost(model, "input", input_tokens),
            "output_cost": calc_cost(model, "output", output_tokens),
        },
        metadata={
            "student_id_hash": hash_id,  # 직접 ID 금지
            "task_type": task_type,
            "tier": tier.value,
        }
    )
```

### 일일 한도
```python
"""사용자별·전체 비용 한도"""
DAILY_LIMITS = {
    "free": 100,      # 원
    "basic": 500,
    "premium": 2000,
    "gifted": 5000,
}

async def check_quota(student_id: str, tier: str) -> bool:
    today_spent = await get_today_spend(student_id)
    return today_spent < DAILY_LIMITS[tier]
```

## 환각 방어

### WhyMath 5중 검증 (기존)
1. **응답 형식 검증**: 스키마 미적합 시 재시도
2. **PRM 단계 검증**: 풀이 단계별 검증
3. **도구 검증**: 수치는 SymPy로 재확인
4. **자기 일관성**: 같은 질문 N회 → 다수결
5. **사람 검수**: 신뢰도 낮을 때 *학생에게 답 제공 거부* + 큐로

### PRD v1.1 환각 방어 4중 레이어 흡수·정렬 (대체 아닌 보강)

PRD 4중 레이어와 WhyMath 5중 방어는 *번호가 다른 두 리스트*가 아니라 *하나의 파이프라인*이다. 어느 단계도 생략 불가 — CLAUDE.md 절대 금기 "LLM 응답을 검증 없이 학생에게 제공 금지"의 구체적 실행.

| PRD 4중 레이어 | 내용 | WhyMath 5중과의 관계 |
|---|---|---|
| ① evidence-based 프롬프트 | LLM이 근거를 *verbatim quote*(원문 그대로 인용)하도록 강제 — 출처 없는 주장 차단 | 1번(스키마 검증)을 **선행 보강** — *생성 단계*에서 환각을 줄이는 입력측 방어. 신규 가치 가장 큼 |
| ② SymPy/Lean 자동 검증 | 수식·수치는 SymPy, 형식 증명은 Lean으로 기계 검증 | 3번(도구 검증)과 **동일 축** — Lean 형식 증명 명시적 추가 |
| ③ 자기검증 패스 | *별도 LLM 호출*로 생성 결과 재검토 (생성 LLM과 분리된 검증 LLM) | 4번(자기 일관성)을 **확장** — 검증 전용 프롬프트·모델로 교차 검증. 위 LLM 5개 핵심 호출지점 ⑤와 연결 |
| ④ 사람 표본 검수 | 생성물의 10% 표본 + 사용자 신고분 사람 검수 | 5번(사람 검수 큐)을 **정량화** — 조건부 검수 + *상시 10% 무작위 표본* + *사용자 신고 트리거* 명시 |

**정렬 후 통합 방어 체계** (생성 → 검증 → 운영 순):
- **입력측 (생성 전·중)**: ① evidence-based 프롬프트 — verbatim quote 강제. 데이터 출처가 L1 검정교과서 단원명·성취기준 등 *인용 가능 범위*임을 강제해 저작권 금기(본문 복제 금지)와도 직결
- **출력측 자동 (생성 직후)**: 1번 스키마 검증 → ②/3번 SymPy·Lean·도구 검증 → 2번 PRM 단계 검증
- **출력측 교차 (자동, 추가 호출)**: ③/4번 자기검증 패스 + 자기 일관성 다수결
- **운영측 (지속)**: ④/5번 사람 검수 — 신뢰도 낮은 건 즉시 큐 + 상시 10% 무작위 표본 + 사용자 신고 트리거. 동치성 판정 검수도 이 큐 공유

### 안전 응답 패턴
```python
"""불확실할 때 *거짓을* 말하지 않는 패턴"""
SAFE_FALLBACK = """
이 문제는 내가 확실히 답하기 어려워. 
대신 함께 생각해보자: [Polya 1단계 질문]
또는 선생님께 여쭤보는 것도 좋은 방법이야.
"""
```

## 성공 기준

### Phase 1
- ✅ 라우터 가동 (로컬 80%+)
- ✅ SymPy 도구 통합
- ✅ Mathpix OCR 통합
- ✅ Langfuse 추적
- ✅ 학생당 월 평균 LLM 비용 < 1,000원

### Phase 2
- ✅ PRM 가동
- ✅ Manim 시각화 자동 생성
- ✅ 다중 풀이 생성 (평균 3개/문제)
- ✅ 응답 캐싱 적중률 30%+

### Phase 3+
- ✅ 자체 PRM 학습 데이터 1만+ 사례
- ✅ 학생당 월 LLM 비용 < 500원
- ✅ 캐싱 적중률 50%+

## 호출 키워드

- `llm:router`
- `llm:prm-verifier`
- `llm:sympy-tool`
- `llm:manim-renderer`
- `llm:multi-solution-gen`
- `llm:response-cache`
- `llm:quota-manager`
- `llm:solution-path` (PRD 신규 — 개념 시퀀스로 인코딩된 풀이)
- `llm:equivalence-scorer` (PRD 신규 — 동치성 휴리스틱 점수 + 사람 검수 큐)
- `llm:concept-extraction` (PRD 신규 — LLM 핵심 호출지점 ①·②·④ 개념 추출·깊이 추론·ID 매칭)
- `llm:self-verification` (PRD 신규 — LLM 핵심 호출지점 ⑤, 환각 방어 ③ 자기검증 패스)
