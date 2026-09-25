# 런북 — 헌법 토큰 실측 (HARN-121 ① · Claude Max 경로)

> 실행 주체: **Kiki** · 게이트: `G-harn121-constitution-token-measure-context`
> (구 게이트 `G-harn121-constitution-token-measure`는 2026-09-24 waived — 아래 "방식 변경" 참조)

## 방식 변경 (2026-09-24 · ARCH-66)

Kiki 결정으로 **2026-12-31까지 Anthropic API를 쓰지 않는다**. Claude는 Claude Max 구독
(Claude Code 등 개발 도구)으로만 쓴다. 그래서 `count_tokens` API 대신 Claude Code의
`/context` 명령으로 잰다.

- `/context`는 **Claude 토크나이저로 센 실제 수치**다. 문자 수로 짐작한 추정이 아니므로
  "문자 수 대체 금지" 원칙과 충돌하지 않는다.
- tiktoken으로 대체하지 않는다. tiktoken은 OpenAI 토크나이저라 Claude와 수가 다르다.
- `scripts/ops/measure_constitution_tokens.py`(API 방식)는 지우지 않고 남겨 둔다. API가
  재개되면 AGENTS.md까지 포함한 보강 측정에 쓴다.

## 1. 과제 명칭

`CLAUDE.md`와 세션 시작 컨텍스트의 **실토큰 수 측정**.

## 2. 목적

헌법 다이어트 목표는 "코어 ≤ 1.5만 토큰"이다. 현재 기준선(4.5만~6.8만)은 문자 수 기반
추정이라, 이 측정이 진짜 분모를 확정한다. 3분리(HARN-121 ②)의 전후 비교 기준선이 된다.

## 3. 구체적 절차 (1분)

1. WhyMath 저장소를 연 Claude Code 세션에서 `/context`를 입력한다. 명령어 한 줄뿐이고
   API 키가 필요 없다.
2. 표가 나온다. 항목은 System prompt, System tools, Memory files, Messages 등이다.
3. 출력 전문을 복사해 세션에 회신한다. 세션이 수치를 `metrics/constitution_tokens.json`에
   기록한다.

## 4. 성공 기준

- **성공**: `Memory files` 항목 아래에 `CLAUDE.md`의 토큰 수가 따로 나온다.
- **부분 성공**: Memory files가 합계로만 나온다. 수치는 그대로 쓰되 "파일별 분리 불가"를
  증거에 적는다.
- **실패**: `/context`가 알 수 없는 명령이라고 나온다. Claude Code 버전이 낮다는 뜻이다.
  출력 전문을 보내 주면 세션이 대안을 찾는다.

## 5. 실행 환경

Claude Code 세션이면 어디서든 된다(웹 claude.ai/code, 데스크톱 앱, Phaiakes9 터미널).
Claude Max 구독 로그인 상태면 된다. **이 측정을 요청한 세션 안에서 바로 입력하는 것이
가장 간단하다.**

Phaiakes9 터미널에서 할 때는 아래처럼 연다.

```powershell
cd C:\Users\kiki\Desktop\__AI\WhyMath
git fetch origin main
git checkout -B harn121-token-measure origin/main
git log -1 --oneline
claude
```

`claude`가 뜨면 프롬프트에 `/context`를 입력한다. `git log` 줄이 최신 main 해시인지
눈으로 확인한다. 트리가 다르면 CLAUDE.md 크기가 달라 수치가 바뀐다.

## 6. 창 구분

기존 Claude Code 세션이면 새 창이 필요 없다. 터미널 경로는 **새 PowerShell 창 1개**를 쓴다.
`claude`가 그 창을 차지하므로 측정이 끝나면 `/exit`로 나온다.

## 알려진 한계

- **AGENTS.md는 잡히지 않는다.** Claude Code는 AGENTS.md를 읽지 않는다(Codex 등 다른
  에이전트용). 이 수치는 API 재개 뒤 스크립트로 보강하거나, 판정에 제외 사유를 적는다.
- **SessionStart 브리핑이 따로 안 나올 수 있다.** 훅 출력은 Messages에 합산된다. 파일별로
  나뉘지 않으면 그 사실을 증거에 남긴다.
