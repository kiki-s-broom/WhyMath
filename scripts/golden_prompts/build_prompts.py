#!/usr/bin/env python3
# ruff: noqa: E501  — 지시문 템플릿(삼중따옴표 문자열)의 한국어 문장 줄은 출력 리터럴이라 100자로 접을 수 없다
"""작업 지시서(markdown) + 설정(JSON) → 작업별 AI 지시문 파일 묶음.

사용법:
    python build_prompts.py <작업지시서.md> <설정.json> <출력 폴더>

결과:
    <출력 폴더>/README.md
    <출력 폴더>/단계01_병렬_2개/<세션이름>.md ...
    (파일 이름 = 세션 이름 = <접두어>-단계NN-<작업번호>-<짧은이름>)

작업 지시서 형식은 references/spec-format.md 를 따른다.
"""

import json
import os
import re
import shutil
import sys


def load_spec(path):
    md = open(path, encoding="utf-8").read().replace("\\~", "~")
    return md.split("\n")


def block_between(lines, start_pat, end_pat):
    """start_pat 줄 다음부터 end_pat 줄 전까지를 돌려준다."""
    s = next(i for i, line in enumerate(lines) if re.match(start_pat, line))
    e = next((i for i in range(s + 1, len(lines)) if re.match(end_pat, lines[i])), len(lines))
    return lines[s + 1 : e]


def parse_sections(lines, ids):
    """### <작업번호>. <제목> 섹션과, 그 위 ## 레인 소개 문단을 모은다."""
    sections, lane_intro, i = {}, "", 0
    id_pat = "|".join(re.escape(t) for t in ids)
    while i < len(lines):
        line = lines[i]
        if line.startswith("## ") and not line.startswith("## 공통"):
            j, intro = i + 1, []
            while j < len(lines) and not lines[j].startswith("### "):
                if lines[j].strip():
                    intro.append(lines[j].strip())
                j += 1
            lane_intro = " ".join(intro)
        m = re.match(rf"### ({id_pat})\. (.+)", line)
        if m:
            j, body = i + 1, []
            while j < len(lines) and not lines[j].startswith(("## ", "### ")):
                body.append(lines[j])
                j += 1
            sections[m.group(1)] = (m.group(2), "\n".join(body).strip(), lane_intro)
            i = j
            continue
        i += 1
    return sections


def main(spec_path, config_path, out):
    cfg = json.load(open(config_path, encoding="utf-8"))
    tasks = cfg["tasks"]  # 순서 = 설정에 적힌 순서
    order = list(tasks)
    deps = {t: tasks[t].get("deps", []) for t in order}
    gates = cfg.get("gates", {})  # {"B7": "①", ...}
    out_root = cfg["output_root"]  # 저장소 안 산출물 폴더, 예: "ped17/산출물"
    branch_prefix = cfg["branch_prefix"]  # 예: "ped17"
    prefix = cfg["session_prefix"]  # 예: "PED17"
    project = cfg["project"]  # 예: "PED-17"
    plan_url = cfg.get("plan_url", "")
    role = cfg["role_line"]  # 예: "교육 앱 PED-17 프로젝트"
    repo_location = cfg.get("repo_location", "<여기에 저장소 주소나 폴더 경로>")

    for t in order:
        for d in deps[t]:
            if d not in tasks:
                sys.exit(f"설정 오류: {t}의 선행 작업 {d}가 tasks에 없다")

    lines = load_spec(spec_path)
    rules = [
        x for x in block_between(lines, r"\*\*공통 규칙\*\*", r"\*\*") if re.match(r"\d+\. ", x)
    ]
    # 용어 표는 "**공유 계약**" 표식 또는 다음 "## " 전까지만 읽는다(공유 계약 안의 표가 섞이지 않게)
    glossary = [
        x
        for x in block_between(lines, r"\*\*용어\*\*", r"(## |\*\*공유 계약\*\*)")
        if x.startswith("|")
    ]
    # WhyMath 보강: 모든 세션이 같은 모양(API·JSON·숙련도 규칙)을 쓰도록 "공유 계약" 절을 통째로 싣는다
    try:
        contracts = "\n".join(block_between(lines, r"\*\*공유 계약\*\*", r"## ")).strip()
    except StopIteration:
        contracts = ""
    if len(rules) < 2:
        sys.exit("작업 지시서에서 '**공통 규칙**' 번호 목록을 찾지 못했다")

    # 파일 하나만 붙여 넣는 방식에 맞게 규칙 1, 2를 표준 문장으로 바꾼다
    gate_ids = ", ".join(gates) if gates else "없음"
    rules[0] = (
        '1. **읽을 범위:** 이 지시문과, 이 지시문이 "선행 산출물"로 적은 결과물만 읽는다. '
        "다른 작업 번호의 일은 하지 않는다."
    )
    rules[1] = (
        f'2. **선행 작업 확인:** 선행 작업마다 `{out_root}/<번호>/보고.md`가 있고 결과가 "완료"인지 확인한다. '
        f"관문 작업({gate_ids})은 판정이 go인지도 확인한다. 하나라도 아니면 시작하지 말고, "
        "비어 있는 번호를 보고하고 멈춘다."
    )

    sections = parse_sections(lines, order)
    missing = [t for t in order if t not in sections]
    if missing:
        sys.exit(f"작업 지시서에 '### <번호>. <제목>' 섹션이 없는 작업: {missing}")

    # 실행 단계 = 가장 빨리 시작할 수 있는 순서
    stage = {}

    def st(t):
        if t not in stage:
            stage[t] = 1 + max((st(d) for d in deps[t]), default=0)
        return stage[t]

    for t in order:
        st(t)
    nstage = max(stage.values())
    by_stage = {s: [t for t in order if stage[t] == s] for s in range(1, nstage + 1)}

    # 늦어도 되는 단계(여유) = 뒤 작업들의 늦은 단계에서 거꾸로 계산
    latest = {}

    def lt(t):
        if t not in latest:
            users = [u for u in order if t in deps[u]]
            latest[t] = min((lt(u) - 1 for u in users), default=nstage)
        return latest[t]

    for t in order:
        lt(t)
    nxt = {t: [u for u in order if t in deps[u]] for t in order}

    def session_name(t):
        return f"{prefix}-단계{stage[t]:02d}-{t}-{tasks[t]['short']}"

    def peers(t):
        return [u for u in by_stage[stage[t]] if u != t]

    def exec_block(t):
        s, p = stage[t], peers(t)
        out_ = [f"- **실행 단계:** {s}단계 (전체 {nstage}단계 중)"]
        if p:
            out_.append(
                f"- **실행 방식: 병렬 가능.** 같은 {s}단계의 {', '.join(p)}와 동시에 다른 세션에서 실행해도 된다."
            )
            out_.append(
                "- **병렬 주의:** 동시에 도는 다른 세션과 같은 파일을 고치게 되면, 자기 브랜치에서만 고치고 합칠 때 충돌을 보고한다."
            )
        else:
            out_.append(
                f"- **실행 방식: 순차 (단독).** {s}단계에는 이 작업 하나뿐이다. 앞 단계가 끝난 뒤 이 세션만 실행한다."
            )
        if latest[t] > s:
            out_.append(
                f"- **여유:** 늦어도 {latest[t]}단계 안에만 끝나면 전체 일정이 밀리지 않는다."
            )
        else:
            out_.append("- **여유: 없음 (크리티컬 패스).** 이 작업이 늦어지면 전체가 늦어진다.")
        return "\n".join(out_)

    def deps_lines(t):
        if not deps[t]:
            return "- 선행 작업: 없음 (바로 시작할 수 있다)"
        out_ = ["- 선행 작업과 그 산출물 위치:"]
        for d in deps[t]:
            out_.append(f"    - {d} ({sections[d][0]}) → `{out_root}/{d}/`")
        return "\n".join(out_)

    background = "\n".join(f"- {b}" for b in cfg.get("background", []))

    if os.path.exists(out):
        shutil.rmtree(out)
    os.makedirs(out)
    folder = {}
    for s, ts in by_stage.items():
        kind = f"병렬_{len(ts)}개" if len(ts) > 1 else "순차"
        folder[s] = f"단계{s:02d}_{kind}"
        os.makedirs(os.path.join(out, folder[s]))

    files = {}
    for t in order:
        title, body, intro = sections[t]
        name = session_name(t)
        files[t] = f"{folder[stage[t]]}/{name}.md"
        gate = (
            f"\n- 이 작업은 **관문 {gates[t]}**이다. 보고에 판정(go 또는 no-go)을 반드시 적는다."
            if t in gates
            else ""
        )
        lane = tasks[t].get("lane", "")
        report = (
            f"작업 번호: {t}\n결과: 완료 | 일부 완료 | 중단\n"
            + ("판정: go | no-go (근거 수치 포함)\n" if t in gates else "")
            + "만든 것: 파일·테이블·화면 이름 (경로 포함)\n"
            "완료 기준 확인: 항목별 통과/실패와 근거 (실행한 명령 또는 본 화면)\n"
            '미확인·가정한 것: 없으면 "없음"\n'
            '다음 작업이 알아야 할 것: 없으면 "없음"'
        )
        text = f"""세션 이름: {name}

# [{project}] 작업 {t}: {title}

> **사용법:** 새 세션을 열고 세션 이름을 `{name}`(이 파일 이름)으로 정한다. 아래 "작업 환경"이 맞는지 보고, 이 파일 전체를 그대로 붙여 넣는다.

## 작업 환경

- 저장소 위치: {repo_location}
- 산출물 폴더: 저장소 안의 `{out_root}/` (없으면 만든다)
- 기본 브랜치: main · 작업 브랜치: `{branch_prefix}/{t}` (아래 "산출물 저장 규칙")
- 계획서: {plan_url}

## 너의 역할

너는 {role}에서 **작업 {t}만** 맡은 AI다. 이 지시문에 적힌 일만 하고, 끝나면 정해진 형식으로 보고한다.
세션 제목을 바꾸는 기능이 있으면 이 세션 제목을 `{name}`으로 바꾼다. 없으면 이 줄은 건너뛴다.

## 실행 방식

{exec_block(t)}

## 프로젝트 배경

{background}

## 이 작업의 위치

- 레인: {lane}
{deps_lines(t)}
- 이 작업의 결과를 쓰는 다음 작업: {", ".join(nxt[t]) if nxt[t] else "없음 (마지막 작업)"}{gate}
- 레인 메모: {intro}

## 공통 규칙 (작업보다 먼저 지킨다)

규칙과 작업 지시가 충돌하면 규칙이 우선한다.

{chr(10).join(rules)}

## 용어

{chr(10).join(glossary)}

{("## 공유 계약 (모든 세션이 같은 모양을 쓴다 — 바꾸려면 보고하고 멈춘다)" + chr(10) + chr(10) + contracts + chr(10)) if contracts else ""}
## 작업 지시: {t}. {title}

{body}

## 산출물 저장 규칙

- 이 작업에서 만든 문서, 표, 보고서는 모두 `{out_root}/{t}/`에 저장한다.
- 코드 변경은 저장소의 기존 위치에 하되, git을 쓰는 저장소라면 `{branch_prefix}/{t}` 브랜치에서 작업하고 기본 브랜치에 직접 반영하지 않는다.
- 마지막으로 `{out_root}/{t}/보고.md`에 아래 형식의 완료 보고를 쓰고, 같은 내용을 답변으로도 보여준다.

## 완료 보고 형식

```
{report}
```

## 시작 순서

1. 공통 규칙 2번대로 선행 작업의 `보고.md`를 확인한다.
2. "작업 지시"의 할 일을 순서대로 수행한다.
3. "완료 기준"을 하나씩 확인하고 결과를 기록한다.
4. `{out_root}/{t}/보고.md`를 쓰고 보고한다.
"""
        open(os.path.join(out, files[t]), "w", encoding="utf-8").write(text)

    # README
    stage_rows = []
    for s, ts in by_stage.items():
        m = "병렬" if len(ts) > 1 else "순차"
        names = "<br>".join(f"[{session_name(t)}]({files[t]})" for t in ts)
        stage_rows.append(f"| {s} | {m} ({len(ts)}개) | {names} |")
    task_rows = []
    for t in order:
        m = "병렬" if peers(t) else "순차"
        slack = "없음" if latest[t] == stage[t] else f"{latest[t]}단계까지"
        task_rows.append(
            f"| {t} | {session_name(t)} | {stage[t]} | {m} | {', '.join(deps[t]) or '없음'} | {slack} |"
        )
    critical = [t for t in order if latest[t] == stage[t]]
    gate_rows = "\n".join(f"| {g} | {w} | {c} |" for g, w, c in cfg.get("gate_table", []))
    gate_block = (
        f"""## 관문 (판정이 go여야 다음으로 넘어간다)

| 관문 | 작업 | 기준 |
| --- | --- | --- |
{gate_rows}
"""
        if gate_rows
        else ""
    )
    notes = "\n\n".join(cfg.get("readme_notes", []))
    human = "\n".join(f"- {h}" for h in cfg.get("human_tasks", []))
    human_block = f"## 사람이 직접 해야 하는 일\n\n{human}\n" if human else ""
    sample = session_name(order[min(len(order) - 1, len(order) // 2)])
    readme = f"""# {project} AI 작업 지시문

계획서: {plan_url}

작업 하나에 파일 하나다. **파일 이름이 곧 세션 이름**이다. 각 파일은 그것만 붙여 넣어도 AI가 작업할 수 있도록 배경, 실행 방식, 공통 규칙, 용어, 작업 지시, 보고 형식을 모두 담고 있다.

## 사용법

1. 실행할 단계 폴더를 연다(단계01부터).
2. 폴더 안의 파일마다 새 세션을 하나씩 연다. 세션 이름은 파일 이름 그대로 쓴다(예: `{sample}`).
3. 파일 맨 위 "작업 환경"이 맞는지 보고(저장소 위치는 미리 채워져 있다), 파일 전체를 붙여 넣는다.
4. 그 단계의 모든 세션이 `{out_root}/<작업번호>/보고.md`를 남기면 다음 단계로 넘어간다.

- **폴더 이름이 "병렬"이면** 그 안의 세션들을 동시에 돌려도 된다.
- **폴더 이름이 "순차"이면** 그 작업 하나만 실행하고, 끝난 뒤 다음 단계로 간다.
- 단계 번호는 "가장 빨리 시작할 수 있는 순서"다. 정확한 조건은 선행 작업이므로, 선행 작업만 끝났으면 다음 단계 작업을 먼저 시작해도 된다.

## 실행 단계 ({nstage}단계)

| 단계 | 방식 | 세션 (= 파일 이름) |
| --- | --- | --- |
{chr(10).join(stage_rows)}

## 작업별 실행 정보

"여유"는 그 단계까지 늦어져도 전체 일정이 밀리지 않는다는 뜻이다. "없음"이면 크리티컬 패스(늦어지면 전체가 늦어지는 줄)다.

| 번호 | 세션 이름 | 단계 | 방식 | 선행 작업 | 여유 |
| --- | --- | --- | --- | --- | --- |
{chr(10).join(task_rows)}

크리티컬 패스: {" → ".join(critical)}

{gate_block}
{notes}

{human_block}"""
    readme = re.sub(r"\n{3,}", "\n\n", readme)
    open(os.path.join(out, "README.md"), "w", encoding="utf-8").write(readme)

    for s, ts in by_stage.items():
        print(f"{folder[s]}: {', '.join(ts)}")
    print("크리티컬 패스:", " → ".join(critical))
    print(f"파일 {len(order)}개 + README.md 생성: {out}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])
