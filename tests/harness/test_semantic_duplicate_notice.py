"""HARN-51 — 이름이 달라도 같은 문제를 겨누는 태스크를 고지한다.

배경(2026-08-31~09-01 실사고): `HARN-45`와 `HARN-48`이 같은 뿌리(차단이 교차 세션
보호를 지운다)를 반대 극성으로 각자 구현했다. 같은 기간 동종 6건 중 앞선 5건은 전부
*같은 식별자*를 두 세션이 배정한 형태라 번호 가드가 전건 실거부했으나, 이 건은 ID가
서로 달라 **어떤 가드에도 걸리지 않았다**. 발견 경로는 기계가 아니라 상대 세션이
자기 YAML에 중복을 스스로 적어 둔 것이었다.

이 파일이 동결하는 계약은 **양방향**이다(acceptance ④). 검출만 검증하면 "전부 유사"로
판정하는 반대 결함을 놓치고, 침묵만 검증하면 아무것도 못 잡는 구현이 통과한다.
그래서 같은 신호로 ①실사고 텍스트는 잡히고 ②무관한 텍스트는 침묵하는지 둘 다 본다.

고지는 **차단이 아니다** — `add`는 어떤 경우에도 exit 0이며 태스크는 등재된다.
"""

from __future__ import annotations

import similar
import store

import backlog as cli

# ── 실사고 텍스트(등재 시점 원본에서 발췌) ──────────────────────────────────
# 현재 YAML에는 사후에 쓴 cancel 사유가 서로를 직접 언급하므로 그대로 쓰면 점수가
# 부풀려진다. 여기서는 등재 시점 원본의 결정적 부분만 옮겨 담는다.
HARN45_TITLE = "게이트 대기와 차단을 같은 전이로 표현하는 문제 — block이 claim을 반납해 병렬 세션이 태스크를 집어가는 창"
HARN45_NOTES = (
    "cmd_block이 원격 claim을 반납 → 05:00:05Z에 타 세션이 claim. "
    "게이트 해소 후 원 세션이 재claim하려 했으나 CAS 충돌로 거부. --force 우회는 하지 않았다. "
    "구조적 원인: '게이트 대기'와 '차단'은 의미가 다른데 같은 전이를 쓴다 — "
    "전자는 자리를 지켜야 하고 후자는 인계 가능해야 한다."
)
HARN45_ACCEPTANCE = [
    "① 사람 게이트 대기를 차단과 구분해 표현한다 — 현재 cmd_block은 "
    "_release_remote_claim으로 claim을 반납하므로 게이트 해소를 기다리는 세션이 자리를 잃는다",
    "② 변별력 실측: 게이트 대기 후에도 원격 claim이 유지되어 타 세션의 start가 거부되는지, "
    "진짜 차단에서는 인계가 가능한지 양방향 동결. 한 방향만 검증하면 반대 결함을 못 잡는다",
]

#: `HARN-48`과 **같은 뿌리**(`cmd_block`/`cmd_unblock`의 `_release_remote_claim`)를
#: 다루는 태스크들의 id 접두. 실코퍼스 보정 테스트가 1위로 허용하는 집합이며, 여기
#: 넣기 전에 정말 같은 뿌리인지 확인한다 — 목록이 길어지는 것 자체가 재보정 신호다.
#:   · HARN-48  : 원격 홀드 게시 (차단이 머지 지연 창에서 무력화되던 축)
#:   · HARN-134 : 그 ④의 교차 세션 해제 축 승계 (차단한 세션이 끝나면 아무도 못 걷는다)
_LINEAGE = ("HARN-48-", "HARN-134-")

HARN48_TITLE = "차단(block)의 원격 게시 — 머지 지연 창에서 차단이 무력화되는 결함 해소"
HARN48_NOTES = (
    "세션 A가 block → 13분 뒤 세션 B가 원격 claim → B가 구현·머지 완료. "
    "근본 원인: cmd_block이 _release_remote_claim으로 원격 레코드를 지워, "
    "보호를 거는 행위가 유일한 교차 세션 신호를 제거했다. "
    "일반형 — 대장 조치의 실효 시점은 조치 시점이 아니라 머지 시점이다."
)
HARN48_ACCEPTANCE = [
    "① block이 원격 대장에 홀드를 게시한다 — 자리를 비우지 않고 kind=block으로 구분",
    "② --handover로 인계 의도를 명시할 때만 claim을 반납한다. force 탈취를 유도하지 않도록 "
    "start가 차단 홀드를 따로 안내한다",
]

# 무관 텍스트 — 같은 저장소·같은 레이어지만 문제가 다르다.
UNRELATED_TITLE = "학생 손글씨 분수 표기 OCR 인식률 저하 — 대분수 가로선 오검출"
UNRELATED_NOTES = "PaddleOCR 폴백 경로에서 가로선이 나눗셈 기호로 오분류되는 사례 관측"
UNRELATED_ACCEPTANCE = ["① 대분수 표기 샘플 200건으로 인식률을 측정한다"]


def _text(title, notes, acceptance):
    return similar.task_text(title, notes, acceptance)


def _corpus_filler() -> dict[str, str]:
    """IDF가 성립하려면 코퍼스가 있어야 한다 — '흔한 말'이 정의되지 않으면
    모든 단어가 똑같이 희소해져 점수가 무의미해진다. 하네스 태스크에서 실제로
    흔한 어휘(태스크·세션·원격·검증·게이트…)를 반복 등장시켜 배경을 만든다."""
    # 실제 하네스 태스크에서 흔한 어휘를 그대로 쓴다 — `인계`·`해소`·`원인`·`자리를`·
    # `force` 같은 말은 저장소 전체에 널려 있어 IDF가 낮다. 이것을 넣지 않으면 픽스처
    # 안에서 그 단어들이 `cmd_block`만큼 희소해져, 무엇이 결정적 신호인지 구별되지 않는다
    # (초안 픽스처가 그래서 IDF 동률이 됐고, 테스트가 해시 순서 운으로 통과했다).
    base = [
        "태스크 세션 원격 검증 게이트 대장 브랜치 머지 테스트 계약 구현 확인 인계 해소",
        "백로그 상태 전이 세션 원격 claim 브랜치 머지 검증 테스트 원인 자리를 force",
        "게이트 대기 사람 승인 대장 기록 세션 확인 검증 인계 해소 원인 자리를",
        "원격 브랜치 스캔 머지 지연 대장 사본 세션 태스크 force 인계 해소 원인",
        "테스트 계약 동결 뮤테이션 변별력 검증 회귀 자리를 force 인계 원인 해소",
    ]
    return {f"FILL-{i:02d}": base[i % len(base)] for i in range(40)}


class TestSignalCatchesTheRealIncident:
    """검출 축 — 이 신호가 실사고를 잡지 못하면 만들 이유가 없다."""

    def test_harn45_ranks_harn48_first(self):
        """실사고_HARN45는_HARN48을_1위_후보로_지목한다"""
        corpus = _corpus_filler()
        corpus["HARN-48"] = _text(HARN48_TITLE, HARN48_NOTES, HARN48_ACCEPTANCE)
        corpus["HARN-22"] = _text(
            "ID 번호 제안 경합", "add가 제안한 번호를 다른 세션이 먼저 쓴다", []
        )
        corpus["OCR-01"] = _text(UNRELATED_TITLE, UNRELATED_NOTES, UNRELATED_ACCEPTANCE)
        index = similar.SimilarityIndex(corpus)
        # floor는 실코퍼스(485건) 기준으로 보정된 값이라 40건짜리 픽스처에서는
        # 점수 스케일이 다르다. 여기서 동결하는 것은 **순위**(스케일 무관 속성)이고,
        # 보정값이 실사고를 실제로 넘기는지는 아래 실코퍼스 테스트가 따로 본다.
        found = index.candidates(
            _text(HARN45_TITLE, HARN45_NOTES, HARN45_ACCEPTANCE), corpus, floor=0.0
        )

        assert found, "실사고를 못 잡으면 이 기능은 존재 이유가 없다"
        assert found[0].task_id == "HARN-48"

    def test_decisive_terms_are_rare_identifiers_not_common_words(self):
        """점수를_만드는_것은_희소_식별자다 — 설계 근거의 동결

        `차단`·`block`·`세션` 같은 일반어는 하네스 태스크 어디에나 있다. 이 신호가
        작동한 이유는 `cmd_block`·`_release_remote_claim`처럼 **저장소 안에서 드문**
        식별자를 공유했기 때문이다. 그 사실이 깨지면 신호의 근거가 사라진다.
        """
        corpus = _corpus_filler()
        corpus["HARN-48"] = _text(HARN48_TITLE, HARN48_NOTES, HARN48_ACCEPTANCE)
        index = similar.SimilarityIndex(corpus)
        found = index.candidates(
            _text(HARN45_TITLE, HARN45_NOTES, HARN45_ACCEPTANCE), corpus, floor=0.0
        )

        assert found
        terms = set(found[0].shared_terms)
        assert {
            "cmd_block",
            "_release_remote_claim",
        } & terms, f"결정적 희소어가 근거에 없다: {found[0].shared_terms}"

    def test_real_corpus_calibration_clears_the_floor(self):
        """실코퍼스_보정값이_실사고를_실제로_검출한다 — 보정 자체의 동결

        위 두 테스트는 *순위*만 본다(픽스처는 점수 스케일이 다르다). 순위가 맞아도
        `SIMILARITY_FLOOR`가 너무 높으면 실사고는 여전히 안 잡힌다 — 그 간극을 이
        테스트가 막는다. 저장소의 진짜 백로그를 코퍼스로 써서 보정값을 그대로 건다.

        브리틀함은 의도적이다: 코퍼스가 이 검출을 못 하게 될 만큼 바뀌었다면
        그것 자체가 재보정이 필요하다는 신호이고, 조용히 지나가면 안 된다.

        [재보정 2026-09-22] 1위 단언이 `HARN-48` **단수**였다가 `_LINEAGE` 집합으로
        바뀌었다. 계기는 `HARN-134`(HARN-48 ④의 교차 세션 축 승계)가 등재되자 이
        테스트가 RED가 된 것이다 — 그리고 그 RED는 **오탐이 아니었다**. 같은 뿌리
        (`cmd_block`/`cmd_unblock`의 `_release_remote_claim`)를 다루는 태스크가
        코퍼스에 둘이 되면 둘 다 정답이므로, 그중 하나를 1위로 못 박는 것은
        과다 명세다. 등재 시점의 `add` 고지는 침묵했다 — pool이 미완 상태만 보므로
        `done`인 `HARN-48`을 구조적으로 못 본다(그 사각의 처분 = `HARN-134` 축 ⑥).

        약화를 막기 위해 **근거 단언을 함께 추가**했다: 1위는 계보에 속하는 것만으로
        부족하고 결정적 희소 식별자를 근거로 갖고 있어야 한다. 이름만 비슷한 태스크가
        1위로 올라오면 여전히 RED다. 계보에 새 id를 넣을 때는 그것이 정말 같은 뿌리인지
        확인하고 넣는다 — 이 목록이 길어지는 것 자체가 다음 재보정 신호다.
        """
        import pathlib

        import yaml

        root = pathlib.Path(__file__).resolve().parents[2]
        corpus = {}
        for path in (root / "backlog" / "tasks").glob("*.yaml"):
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            corpus[data["id"]] = similar.task_text(
                data.get("title") or "", data.get("notes") or "", data.get("acceptance") or []
            )
        lineage = {k for k in corpus if k.startswith(_LINEAGE)}
        if not lineage:
            import pytest

            pytest.skip(f"{_LINEAGE} 어느 것도 백로그에 없다 — 이 회귀의 기준점이 사라졌다")

        index = similar.SimilarityIndex(corpus)
        pool = {k: v for k, v in corpus.items() if not k.startswith("HARN-45-")}
        found = index.candidates(_text(HARN45_TITLE, HARN45_NOTES, HARN45_ACCEPTANCE), pool)

        assert found, f"보정값 floor={similar.SIMILARITY_FLOOR}가 실사고를 놓친다 — 재보정 필요"
        assert found[0].task_id in lineage, (
            f"1위 {found[0].task_id}가 HARN-48 계보 밖이다 — 신호가 엉뚱한 곳을 가리킨다. "
            f"계보={sorted(lineage)}"
        )
        # 계보 소속만으로는 통과시키지 않는다 — 1위가 *왜* 1위인지까지 건다.
        assert {"cmd_block", "cmd_unblock", "_release_remote_claim"} & set(
            found[0].shared_terms
        ), f"1위의 근거에 결정적 희소어가 없다: {found[0].shared_terms}"


class TestSignalStaysQuietOtherwise:
    """침묵 축 — '전부 유사'로 판정하는 반대 결함을 잡는다(acceptance ④)."""

    def test_unrelated_task_yields_no_candidate(self):
        """무관한_태스크는_후보를_내지_않는다"""
        corpus = _corpus_filler()
        corpus["HARN-48"] = _text(HARN48_TITLE, HARN48_NOTES, HARN48_ACCEPTANCE)
        corpus["HARN-45"] = _text(HARN45_TITLE, HARN45_NOTES, HARN45_ACCEPTANCE)
        index = similar.SimilarityIndex(corpus)
        found = index.candidates(
            _text(UNRELATED_TITLE, UNRELATED_NOTES, UNRELATED_ACCEPTANCE), corpus
        )

        assert found == [], f"무관 태스크에 후보가 떴다: {[c.task_id for c in found]}"

    def test_empty_pool_is_silent_not_crash(self):
        """대조군이_비면_조용히_빈_결과다 — 첫 태스크 등재에서 터지면 안 된다"""
        index = similar.SimilarityIndex(_corpus_filler())
        assert index.candidates(_text(HARN45_TITLE, HARN45_NOTES, []), {}) == []

    def test_floor_is_what_creates_silence(self):
        """침묵을_만드는_것은_floor다 — 이 손잡이의 변별력 동결

        floor가 없으면 *가장 덜 안 닮은* 것이 그냥 1위로 뽑혀 매번 후보가 나온다.
        실코퍼스 485건 측정에서 floor 제거 시 침묵률이 20%→3%로 무너졌다. 이 테스트가
        없으면 floor를 0으로 바꿔도 스위트가 통과한다(실제로 그랬다 — 뮤테이션 M2 생존).
        """
        corpus = _corpus_filler()
        corpus["HARN-48"] = _text(HARN48_TITLE, HARN48_NOTES, HARN48_ACCEPTANCE)
        index = similar.SimilarityIndex(corpus)
        probe = _text(UNRELATED_TITLE, UNRELATED_NOTES, UNRELATED_ACCEPTANCE)

        assert index.candidates(probe, corpus) == []
        assert index.candidates(
            probe, corpus, floor=0.0
        ), "floor를 0으로 내려도 결과가 같다면 floor는 아무 일도 하지 않는 손잡이다"

    def test_limit_is_what_caps_dense_series(self):
        """밀집_계열의_폭주를_막는_것은_limit다 — 이 손잡이의 변별력 동결

        `ARCH-0N-playbook-audit` 같은 *의도적* 시리즈는 서로 매우 유사해 floor를 전부
        넘는다. 실코퍼스에서 상한을 풀면 한 번에 최대 23건까지 나왔다.
        """
        corpus = _corpus_filler()
        series = "플레이북 파트 감사 구조 원칙 붕괴 연쇄 점검 질문 세트 대조 기록 상환"
        for i in range(12):
            corpus[f"ARCH-{i:02d}-playbook-audit"] = f"{series} 파트{i}"
        index = similar.SimilarityIndex(corpus)
        probe = f"{series} 파트99"

        assert len(index.candidates(probe, corpus)) <= similar.MAX_CANDIDATES
        assert (
            len(index.candidates(probe, corpus, limit=99)) > similar.MAX_CANDIDATES
        ), "상한을 풀어도 개수가 같다면 limit는 아무 일도 하지 않는 손잡이다"


class TestNoticeIsANoticeNotAGate:
    """`add`는 고지 유무와 무관하게 성공한다 — 차단이 아니다(acceptance ②)."""

    def test_add_succeeds_and_prints_notice(self, bare_remote, monkeypatch, capsys):
        """중복_후보가_있어도_add는_성공하고_고지만_남긴다"""
        _, clone = bare_remote
        repo = clone("owner")
        monkeypatch.chdir(repo)
        assert cli.main(["seed"]) == 0

        assert (
            cli.main(
                [
                    "add",
                    "--eos-priority",
                    "P2",
                    "--id",
                    "S9-20-prior",
                    "--title",
                    HARN48_TITLE,
                    "--track",
                    "math-completion",
                    "--stage",
                    "S2",
                    "--note",
                    HARN48_NOTES,
                    *sum((["--acceptance", a] for a in HARN48_ACCEPTANCE), []),
                ]
            )
            == 0
        )
        capsys.readouterr()

        exit_code = cli.main(
            [
                "add",
                "--eos-priority",
                "P2",
                "--id",
                "S9-21-duplicate",
                "--title",
                HARN45_TITLE,
                "--track",
                "math-completion",
                "--stage",
                "S2",
                "--note",
                HARN45_NOTES,
                *sum((["--acceptance", a] for a in HARN45_ACCEPTANCE), []),
            ]
        )
        err = capsys.readouterr().err

        assert exit_code == 0, "고지는 차단이 아니다 — 등재를 막으면 안 된다"
        assert "의미 중복 후보" in err
        assert "S9-20-prior" in err
        # 라벨의 반례 (HARN-134 ⑥) — `S9-20-prior`는 todo다. 이 단언이 없으면 "전부
        # 완료됨으로 찍는다"는 구현이 통과하고, 그러면 라벨이 구별을 못 하므로 존재
        # 이유가 사라진다. 절을 하나 둘 때마다 그 절의 반례를 픽스처에 둔다.
        assert "완료됨" not in err, "미완 후보에 완료됨 라벨이 붙었다 — 구별이 무의미해진다"

    def test_done_task_surfaces_with_a_completed_label(self, bare_remote, monkeypatch, capsys):
        """완료된_태스크도_고지에_뜨되_구분되는_라벨을_단다 (HARN-134 ⑥ 판정 ⓐ).

        종전 pool은 in-flight 4종뿐이라 `done`을 **구조적으로 못 봤다**. 그 사각에
        들어가는 것이 *미이행 acceptance를 남긴 done 태스크의 승계*이며, 2026-09-22에
        실제로 `HARN-48`(done)을 이 고지가 침묵했다 — 잡아낸 것은 등재가 아니라 CI였다.

        라벨을 함께 재는 이유: 그냥 pool에 넣으면 완료된 태스크가 "지금 누가 하고 있다"와
        같은 색으로 나와, 읽는 사람이 병렬 충돌로 오독하고 엉뚱하게 cancel할 수 있다.
        고지의 목적은 *행동을 고르게* 하는 것이므로 두 경우가 구별돼야 한다.

        변별력: pool에서 done을 빼면 고지 자체가 사라지고, 라벨을 지우면 "로컬"로 나온다
        — 두 뮤테이션이 각각 다른 단언을 RED로 만든다.
        """
        _, clone = bare_remote
        repo = clone("owner")
        monkeypatch.chdir(repo)
        assert cli.main(["seed"]) == 0

        assert (
            cli.main(
                [
                    "add",
                    "--eos-priority",
                    "P2",
                    "--id",
                    "S9-22-finished",
                    "--title",
                    HARN48_TITLE,
                    "--track",
                    "math-completion",
                    "--stage",
                    "S2",
                    "--note",
                    HARN48_NOTES,
                    *sum((["--acceptance", a] for a in HARN48_ACCEPTANCE), []),
                ]
            )
            == 0
        )
        # 완료 상태로 만든다 — CLI done은 증적·claim 경로를 타므로 여기서는 대장에
        # 직접 쓴다(이 테스트가 재는 것은 done 처리 절차가 아니라 pool 필터다).
        backlog, _ = store.load_backlog(repo)
        finished = backlog.tasks["S9-22-finished"]
        finished.status = "done"
        store.save_task(repo, finished)
        capsys.readouterr()

        assert (
            cli.main(
                [
                    "add",
                    "--eos-priority",
                    "P2",
                    "--id",
                    "S9-23-successor",
                    "--title",
                    HARN45_TITLE,
                    "--track",
                    "math-completion",
                    "--stage",
                    "S2",
                    "--note",
                    HARN45_NOTES,
                    *sum((["--acceptance", a] for a in HARN45_ACCEPTANCE), []),
                ]
            )
            == 0
        )
        err = capsys.readouterr().err
        assert "S9-22-finished" in err, "완료된 태스크가 고지에 안 뜬다 — 사각 그대로"
        assert "완료됨" in err, "완료됨 라벨이 없으면 병렬 충돌과 구별되지 않는다"

    def test_unrelated_add_prints_no_duplicate_notice(self, bare_remote, monkeypatch, capsys):
        """무관한_add에서는_중복_고지가_아예_안_뜬다 — 조용할 때는 조용하다"""
        _, clone = bare_remote
        repo = clone("owner")
        monkeypatch.chdir(repo)
        assert cli.main(["seed"]) == 0
        assert (
            cli.main(
                [
                    "add",
                    "--eos-priority",
                    "P2",
                    "--id",
                    "S9-22-prior",
                    "--title",
                    HARN48_TITLE,
                    "--track",
                    "math-completion",
                    "--stage",
                    "S2",
                    "--note",
                    HARN48_NOTES,
                ]
            )
            == 0
        )
        capsys.readouterr()

        assert (
            cli.main(
                [
                    "add",
                    "--eos-priority",
                    "P2",
                    "--id",
                    "S9-23-unrelated",
                    "--title",
                    UNRELATED_TITLE,
                    "--track",
                    "math-completion",
                    "--stage",
                    "S2",
                    "--note",
                    UNRELATED_NOTES,
                ]
            )
            == 0
        )
        assert "의미 중복 후보" not in capsys.readouterr().err


class TestRemoteReadContract:
    """원격 본문 읽기 — 네트워크 0 · 사전 필터 · 판정 불가는 판정 불가라고 말한다."""

    def test_reader_never_fetches(self, bare_remote, monkeypatch):
        """원격_본문_읽기는_git_fetch를_부르지_않는다 — fetch=False 비용 계약 승계"""
        import remote_claims

        _, clone = bare_remote
        repo = clone("owner")
        monkeypatch.chdir(repo)
        real = remote_claims._git
        seen: list[tuple[str, ...]] = []

        def spy(root, *argv, **kw):
            seen.append(argv)
            return real(root, *argv, **kw)

        monkeypatch.setattr(remote_claims, "_git", spy)
        files, _ = remote_claims.scan_remote_task_files(repo)
        remote_claims.read_remote_task_texts(repo, files)

        assert not [a for a in seen if a and a[0] == "fetch"], f"fetch 호출됨: {seen}"

    def test_skip_filter_applies_before_reading(self, monkeypatch):
        """로컬에_있는_ID는_읽기_전에_걸러진다 — 상한에 걸려 판정 불가가 뜨는 것 방지

        필터가 읽기 *뒤*에 있으면 실측상 원격 고유 595건을 전부 읽어 상한에 걸리고,
        정상 상태에서도 매번 '판정 불가' 경고가 떠 소음이 된다.
        """
        from pathlib import Path

        import remote_claims

        files = [
            remote_claims.RemoteTaskFile(f"T-{i:03d}", f"refs/remotes/origin/b{i}", f"b{i}")
            for i in range(50)
        ]
        asked: list[str] = []

        def fake_git(root, *argv, input_text=None, **kw):
            asked.extend((input_text or "").strip().splitlines())
            import subprocess

            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        monkeypatch.setattr(remote_claims, "_git", fake_git)
        skip = {f"T-{i:03d}" for i in range(45)}
        remote_claims.read_remote_task_texts(Path("."), files, skip=skip)

        assert len(asked) == 5, f"필터가 읽기 앞에 없다 — {len(asked)}건 조회"

    def test_remote_failure_never_blocks_add_and_names_the_exception(
        self, bare_remote, monkeypatch, capsys
    ):
        """원격_조회가_죽어도_add는_통과하고_예외_타입명이_남는다

        고지는 관측 기능이다 — 어떤 식으로 죽든 등재를 막으면 안 된다. 다만 무타입
        경고는 금지다(CLAUDE.md 침묵 실패 금지). 이 계약이 없으면 고지를 붙이는 것만으로
        `add`가 exit 3으로 죽는다 — 실제로 그렇게 만들었다가 기존 계약 테스트가 잡았다.
        """
        import remote_claims

        _, clone = bare_remote
        repo = clone("owner")
        monkeypatch.chdir(repo)
        assert cli.main(["seed"]) == 0

        def _boom(root, *a, **kw):
            raise RuntimeError("원격 본문 읽기 불가")

        monkeypatch.setattr(remote_claims, "read_remote_task_texts", _boom)
        capsys.readouterr()

        exit_code = cli.main(
            [
                "add",
                "--eos-priority",
                "P2",
                "--id",
                "S9-24-remote-dead",
                "--title",
                HARN45_TITLE,
                "--track",
                "math-completion",
                "--stage",
                "S2",
                "--note",
                HARN45_NOTES,
            ]
        )
        err = capsys.readouterr().err

        assert exit_code == 0, "관측 기능의 실패가 등재를 막으면 안 된다"
        assert "RuntimeError" in err, "예외 타입명 없는 경고는 금지(무증상 전멸의 원인)"
        assert "판정 불가" in err, "조회 실패를 '중복 없음'과 같은 색으로 두면 안 된다"

    def test_korean_bodies_are_read_intact_from_real_git(self, tmp_path):
        """한국어_본문_여러_건이_온전히_읽힌다 — 바이트/문자 오프셋 함정 회귀

        `git cat-file --batch`의 `<size>`는 **바이트 수**인데 디코드된 문자열에서 그
        숫자만큼 전진하면 한국어(3바이트/자)에서 위치가 밀린다. 초안이 파싱을 직접
        구현하다 정확히 이 함정에 빠졌다 — **3건 요청에 1건만, 그것도 다음 blob의 sha가
        섞인 채** 돌아오면서 status는 `ok`였다(조용한 손상). PR #947 리뷰가 잡았다.

        모의 git으로는 이 결함을 볼 수 없다(stdout을 우리가 만들면 함정이 재현되지
        않는다). 그래서 **실제 git 저장소**를 만들어 실제 `cat-file --batch` 출력을 태운다.
        개수만 세면 안 된다 — 손상은 개수가 아니라 **내용**에서 드러난다.
        """
        import subprocess

        import remote_claims

        repo = tmp_path / "repo"
        (repo / "backlog" / "tasks").mkdir(parents=True)
        bodies = {
            "T-001": "title: 게이트 대기와 차단의 분리 문제\nnotes: cmd_block이 claim을 반납한다\n",
            "T-002": "title: 두 번째 태스크\nnotes: 완전히 다른 내용 손글씨 OCR 인식률\n",
            "T-003": "title: 세 번째 태스크\nnotes: 또 다른 한국어 본문 라이선스 검토\n",
        }
        for tid, body in bodies.items():
            (repo / "backlog" / "tasks" / f"{tid}.yaml").write_text(body, encoding="utf-8")
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(repo),
                "-c",
                "user.email=t@t",
                "-c",
                "user.name=t",
                "commit",
                "-qm",
                "seed",
            ],
            check=True,
            capture_output=True,
        )
        files = [remote_claims.RemoteTaskFile(tid, "HEAD", f"b{i}") for i, tid in enumerate(bodies)]

        texts, branches, status = remote_claims.read_remote_task_texts(repo, files)

        assert status == "ok"
        assert texts == bodies, "본문이 손상됐다 — 개수만 보면 안 보이는 결함이다"
        assert branches == {tid: f"b{i}" for i, tid in enumerate(bodies)}

    def test_truncation_is_reported_not_hidden(self, monkeypatch):
        """상한_초과는_truncated로_보고된다 — 부분 결과를 '전부 봤다'로 위장하지 않는다"""
        from pathlib import Path

        import remote_claims

        files = [
            remote_claims.RemoteTaskFile(f"T-{i:03d}", f"refs/remotes/origin/b{i}", f"b{i}")
            for i in range(10)
        ]

        def fake_git(root, *argv, input_text=None, **kw):
            import subprocess

            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        monkeypatch.setattr(remote_claims, "_git", fake_git)
        _, _, status = remote_claims.read_remote_task_texts(Path("."), files, limit=3)

        assert status == "truncated"
