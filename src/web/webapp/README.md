# WhyMath 별도 웹 (webapp) — 공개 랜딩 v1

> Next.js 15 App Router · React 19 · **정적 export**(`output: "export"` → `out/`)
> 정본 설계: [`docs/architecture/web_strategy.md`](../../../docs/architecture/web_strategy.md)

---

## 이 앱이 무엇이고 무엇이 아닌가

CLAUDE.md 슬라이스 89의 **③ "별도 웹"** 좌석이다. 학생 *학습 경험*은 Flutter 단일이고,
여기는 **유입·소개 표면**이다(web_strategy §1).

| 지금 있는 것 | 이후 들어올 것 | 여기에 절대 없는 것 |
|---|---|---|
| `app/(public)/` 공개 랜딩 1페이지 | `app/admin/` 운영 백오피스 (ADMIN-06·내부망 한정) | 학생 학습 기능 |
| `robots.txt` · `sitemap.xml` | 교사 웹 (Phase 3+·재평가 후) | 수학 판정·채점·오개념 진단 로직 |

`src/web/graphing-calculator/`(슬89 ④ 국소 비상구·Vite SPA)와는 **별개 앱**이다. 그쪽은
불가침이며 이 앱과 코드를 공유하지 않는다.

---

## 경계 — 기계로 동결된 세 가지

`tests/infra/test_webapp_landing_governance.py`가 CI(`infra-contracts` 잡)에서 상시 검사한다.

1. **수학 판정 0** — 정오 판정·채점·동치 판정의 단일 권위는 백엔드 L3(SymPy)다. ARCH-10의
   웹앱 축이며, graphing-calculator 쪽 동형 게이트는
   `src/web/graphing-calculator/test/no_math_judgement_governance.test.js`다.
2. **백엔드 호출 0** — v1 랜딩은 네트워크 호출을 하지 않는다. 베타 신청은 **외부 폼 링크**만
   (web_strategy §3.2). CORS 배선은 ADMIN-06이 소유한다.
3. **공개 빌드에 admin 코드 0** — 백오피스가 들어와도 공개 산출물에 섞이면 안 된다
   (web_strategy §2 배포 요건). 지금은 `app/admin/` 부재 자체를 동결한다.

추가로 **카피 가드**(효과 단정 금지)를 보조 탐지기로 둔다 — 아래 §법적 게이트 참조.

---

## 개발

```bash
cd src/web/webapp
npm ci            # lockfile 고정 설치 (CI와 동일)
npm run dev       # http://localhost:3000
npm run lint      # eslint (next/core-web-vitals + next/typescript)
npm run build     # 정적 export → out/  (타입 검사 포함)
npm run typecheck # tsc --noEmit (next-env.d.ts가 필요하므로 build 이후에 실행)
```

`out/`은 서버 런타임이 필요 없는 완전 정적 산출물이다. `node_modules/`·`.next/`·`out/`은
커밋하지 않는다(`.gitignore`) — CI가 매번 `npm ci`로 재현한다.

## 의존성 메모 — `overrides`로 postcss를 올려 둔 이유

`next@15.5.25`는 `postcss`를 **정확히 `8.4.31`로 핀**하는데, 그 버전은 권고 4건(`<=8.5.22`)에
걸린다. `npm audit fix`가 제시하는 유일한 경로는 **Next 16**이고, 그건 CLAUDE.md 스택 표
("React 19 + Next.js 15")를 바꾸는 일이라 MEMORY 결정 로그가 선결이다. 그래서 스택은 15에
두고 `package.json`의 `overrides`로 postcss만 `^8.5.28`로 올린다.

실측(2026-09-22): override 후 `npm audit` **0건**, `npm run lint`·`npm run build` 통과,
CSS 모듈 해시·`globals.css` 번들 포함 정상. 이 override와 Next 15 핀은 둘 다 *의도*이므로
`tests/infra/test_webapp_landing_governance.py` 계약 ⑦-b가 조용한 소실을 막는다 —
Next 16으로 올릴 때 그 테스트가 RED로 사람을 세운다.

---

## 환경변수 (전부 선택 — 미설정이 정상 기본값)

| 변수 | 용도 | 미설정 시 |
|---|---|---|
| `NEXT_PUBLIC_SITE_URL` | 배포 도메인 — `sitemap.xml`·OG의 절대 URL 기준 | `http://localhost:3000` (도메인 확정은 WEB-02·Kiki) |
| `NEXT_PUBLIC_BETA_FORM_URL` | 베타 신청 외부 폼 링크 | CTA가 링크 대신 **"준비 중"**으로 렌더 — 죽은 링크를 내보내지 않는다 |

값이 확정되지 않은 자리에 그럴듯한 가짜 값을 박지 않는다. 미확정은 미확정으로 보여야
"누가 확정해야 하는가"가 드러난다.

---

## 공개 전 선결 — 변호사 검토 게이트 (기계 대체 금지)

배포는 **WEB-02**가 소유하고, 그 선결이 게이트 `G-web01-landing-legal-review`다
(`python3 scripts/harness/backlog.py gates list`). 검토 항목 3종(web_strategy §3.4):

- **광고·마케팅 규제** — RCT 검증 전 "성적이 오른다" 류 효과 단정 금지·비교 광고 자문
- **웹접근성(KWCAG)** — 지능정보화기본법 §46의 적용 범위가 웹 개설로 실제 변동(법률 판단)
- **개인정보** — 외부 폼 채택 시 **처리위탁 고지**·수집 최소화·처리방침 문구

코드 쪽 카피 가드(금지 문구 스캔)는 위 거버넌스 테스트에 있으나 **보조 탐지기**다. 문자열
열거는 표현을 바꾸면 빠져나가므로, 효과 단정 여부의 최종 판정은 사람(변호사)이 한다.
CLAUDE.md "법령 유래 절차의 기계 대체 금지" 그대로다.
