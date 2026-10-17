"use client";

import { useState, type FormEvent } from "react";

import {
  createCmsEdge,
  deleteCmsEdge,
  fetchCmsConcepts,
  type CmsConceptDetail,
  type CmsConceptList,
  type CmsConceptRow,
  type CmsEdgeRow,
  type CmsResult,
} from "../_lib/adminCmsApi";

import {
  CmsFailureBox,
  CmsNoticeView,
  describeCmsFailure,
  type CmsNotice,
  type NoteResult,
} from "./CmsCommon";

import styles from "./Cms.module.css";

/**
 * 관계(선수·후행) 편집 패널 (P3-26).
 *
 * 용어: A가 B의 **선수**라는 것은 "A를 알아야 B를 이해한다"는 뜻이다. 이 패널은 이 개념의
 *   · 선수 목록(`incoming` — 이 개념 앞에 와야 하는 개념)
 *   · 후행 목록(`outgoing` — 이 개념을 알아야 하는 뒤쪽 개념)
 * 을 보이고, CMS가 만든 관계만 지우고, 새 선수 관계를 더한다.
 *
 * 경계(CLAUDE.md "표현 ≠ 의미")
 * ----------------------------
 * 순환 여부·권한·파일 소유 여부를 이 파일이 판정하지 않는다. 화면이 하는 일은 ①서버가 준
 * `can_write_graph`·`cms_owned`대로 버튼을 그리고 ②서버가 거부하면 사유를 그대로 보이는 것뿐이다.
 * (버튼을 숨기는 것은 보안이 아니다 — 403이 와도 안내 문구로 처리한다.)
 */

interface Props {
  token: string;
  note: NoteResult;
  detail: CmsConceptDetail;
  /** 관계가 바뀌어 서버 값이 달라졌을 때(부모가 개념 상세·목록을 서버에서 다시 읽는다). */
  onChanged: () => void;
}

export function CmsEdgePanel({ token, note, detail, onChanged }: Props) {
  const [notice, setNotice] = useState<CmsNotice>(null);
  const [busy, setBusy] = useState(false);
  // 삭제 확인 대기 중인 관계(edge_id) — 한 번에 하나만 묻는다.
  const [askingId, setAskingId] = useState<string | null>(null);

  const canWrite = detail.can_write_graph;

  async function removeEdge(edge: CmsEdgeRow): Promise<void> {
    if (busy) return;
    setBusy(true);
    const result = await deleteCmsEdge(token, edge.edge_id);
    setBusy(false);
    setAskingId(null);
    note(result.kind);
    if (result.kind === "ok") {
      setNotice({ tone: "info", text: "관계를 지웠습니다: " + edge.other_code + " " + edge.other_name_ko });
    } else {
      setNotice({ tone: "failure", failure: result, what: "관계 삭제" });
    }
    // 성공이든 충돌·없음이든 서버 값이 바뀌었을 수 있다 — 낙관적 갱신 없이 다시 읽는다.
    if (result.kind === "ok" || result.kind === "conflict" || result.kind === "not-found") onChanged();
  }

  return (
    <div>
      <CmsNoticeView notice={notice} />

      <EdgeGroup
        title="선수 (이 개념을 이해하려면 먼저 알아야 하는 개념)"
        edges={detail.incoming}
        canDelete={canWrite}
        busy={busy}
        askingId={askingId}
        onAsk={setAskingId}
        onConfirm={(edge) => void removeEdge(edge)}
      />
      <EdgeGroup
        title="후행 (이 개념을 알아야 이해할 수 있는 개념)"
        edges={detail.outgoing}
        canDelete={canWrite}
        busy={busy}
        askingId={askingId}
        onAsk={setAskingId}
        onConfirm={(edge) => void removeEdge(edge)}
      />

      <p className={styles.hint}>
        &quot;원천 파일 소유&quot; 관계는 그래프 원천 파일이 정본이라 여기서 지울 수 없습니다(지워도 다음 적재가
        되살립니다). &quot;CMS가 만듦&quot; 관계만 지울 수 있습니다.
      </p>

      {canWrite ? (
        <AddEdgeForm
          token={token}
          note={note}
          detail={detail}
          busy={busy}
          onNotice={setNotice}
          onChanged={onChanged}
        />
      ) : (
        <p className={styles.muted}>
          이 계정은 관계를 추가·삭제할 권한이 없어 읽기 전용입니다(서버가 허용한 계정에게만 쓰기가 열립니다).
        </p>
      )}
    </div>
  );
}

function EdgeGroup(props: {
  title: string;
  edges: CmsEdgeRow[];
  canDelete: boolean;
  busy: boolean;
  askingId: string | null;
  onAsk: (edgeId: string | null) => void;
  onConfirm: (edge: CmsEdgeRow) => void;
}) {
  return (
    <div>
      <p className={styles.label}>
        {props.title} ({props.edges.length}건)
      </p>
      {props.edges.length === 0 ? (
        <p className={styles.muted}>(없음)</p>
      ) : (
        <ul className={styles.edgeList}>
          {props.edges.map((edge) => {
            const asking = props.askingId === edge.edge_id;
            return (
              <li key={edge.edge_id}>
                {edge.other_code} {edge.other_name_ko} — {edge.edge_type}{" "}
                <span className={styles.badge}>{edge.cms_owned ? "CMS가 만듦" : "원천 파일 소유"}</span>
                {edge.cms_owned && props.canDelete && (
                  <>
                    {" "}
                    <button
                      className={styles.secondaryButton}
                      type="button"
                      disabled={props.busy}
                      aria-pressed={asking}
                      aria-label={"관계 삭제: " + edge.other_code + " " + edge.other_name_ko}
                      onClick={() => props.onAsk(asking ? null : edge.edge_id)}
                    >
                      삭제
                    </button>
                  </>
                )}
                {asking && (
                  <div className={styles.confirm} role="group" aria-label="관계 삭제 확인">
                    <p className={styles.confirmText}>
                      <strong>
                        {edge.other_code} {edge.other_name_ko}
                      </strong>
                      과(와)의 관계를 지웁니다. 지운 뒤에는 다시 추가해야 합니다. 계속할까요?
                    </p>
                    <div className={styles.actions}>
                      <button
                        className={styles.primaryButton}
                        type="button"
                        disabled={props.busy}
                        onClick={() => props.onConfirm(edge)}
                      >
                        {props.busy ? "처리 중…" : "관계 지우기"}
                      </button>
                      <button
                        className={styles.secondaryButton}
                        type="button"
                        disabled={props.busy}
                        onClick={() => props.onAsk(null)}
                      >
                        취소
                      </button>
                    </div>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

// ── 관계 추가 ────────────────────────────────────────────────────────────

/** 이 개념이 선수인가(`self-first`), 후행인가(`self-last`). */
type Direction = "self-first" | "self-last";

type SearchState = null | { kind: "loading" } | CmsResult<CmsConceptList>;

const SEARCH_LIMIT = 8;

function AddEdgeForm(props: {
  token: string;
  note: NoteResult;
  detail: CmsConceptDetail;
  busy: boolean;
  onNotice: (notice: CmsNotice) => void;
  onChanged: () => void;
}) {
  const { token, detail } = props;
  const [typed, setTyped] = useState("");
  const [search, setSearch] = useState<SearchState>(null);
  const [partner, setPartner] = useState<CmsConceptRow | null>(null);
  const [direction, setDirection] = useState<Direction>("self-last");
  const [strength, setStrength] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const disabled = props.busy || saving;

  async function runSearch(event: FormEvent): Promise<void> {
    event.preventDefault();
    setSearch({ kind: "loading" });
    const result = await fetchCmsConcepts(token, typed, SEARCH_LIMIT, 0);
    props.note(result.kind);
    setSearch(result);
  }

  async function submit(): Promise<void> {
    if (disabled) return;
    if (partner === null) {
      setError("상대 개념을 먼저 검색해서 선택하세요.");
      return;
    }
    let edgeStrength: number | null = null;
    const trimmed = strength.trim();
    if (trimmed.length > 0) {
      const parsed = Number(trimmed);
      if (!Number.isFinite(parsed)) {
        setError("강도는 숫자로 입력하세요(예: 0.8). 비워 두면 강도 없이 추가합니다.");
        return;
      }
      edgeStrength = parsed;
    }
    setError(null);

    // from이 to의 선수다. 이 개념이 선수면 (이 개념 → 상대), 후행이면 (상대 → 이 개념).
    const fromId = direction === "self-first" ? detail.concept_id : partner.concept_id;
    const toId = direction === "self-first" ? partner.concept_id : detail.concept_id;

    setSaving(true);
    const result = await createCmsEdge(token, fromId, toId, edgeStrength);
    setSaving(false);
    props.note(result.kind);
    if (result.kind === "ok") {
      props.onNotice({
        tone: "info",
        text:
          "관계를 추가했습니다: " + result.data.from_code + "은(는) " + result.data.to_code +
          "의 선수입니다(" + result.data.from_code + " → " + result.data.to_code + ").",
      });
      setPartner(null);
      setStrength("");
      setSearch(null);
      props.onChanged();
      return;
    }
    props.onNotice({ tone: "failure", failure: result, what: "관계 추가" });
    // 이미 있음·개념 사라짐 등은 서버 상태가 달라졌다는 신호 — 최신 값을 다시 읽는다.
    if (result.kind === "conflict" || result.kind === "not-found") props.onChanged();
  }

  const partnerLabel = partner === null ? "(상대 개념)" : partner.code + " " + partner.name_ko;
  const selfLabel = detail.code;
  const sentence =
    direction === "self-first"
      ? partnerLabel + "을(를) 이해하려면 " + selfLabel + "을(를) 먼저 알아야 합니다."
      : selfLabel + "을(를) 이해하려면 " + partnerLabel + "을(를) 먼저 알아야 합니다.";

  return (
    <section className={styles.block} aria-label="관계 추가">
      <h4 className={styles.blockTitle}>선수 관계 추가</h4>

      <form className={styles.searchRow} onSubmit={(event) => void runSearch(event)} role="search">
        <label className={styles.srOnly} htmlFor="wm-cms-edge-q">
          상대 개념 검색
        </label>
        <input
          id="wm-cms-edge-q"
          className={styles.input}
          type="search"
          value={typed}
          maxLength={100}
          disabled={disabled}
          placeholder="상대 개념의 코드 또는 이름"
          onChange={(event) => setTyped(event.target.value)}
        />
        <button className={styles.secondaryButton} type="submit" disabled={disabled}>
          상대 개념 검색
        </button>
      </form>

      <SearchResults
        search={search}
        selfId={detail.concept_id}
        pickedId={partner === null ? null : partner.concept_id}
        disabled={disabled}
        onPick={(row) => {
          setPartner(row);
          setError(null);
        }}
        onRetry={() => setSearch(null)}
      />

      <fieldset className={styles.fieldset}>
        <legend className={styles.label}>두 개념의 순서</legend>
        <label>
          <input
            type="radio"
            name="wm-cms-edge-direction"
            checked={direction === "self-last"}
            disabled={disabled}
            onChange={() => setDirection("self-last")}
          />{" "}
          상대 개념이 이 개념의 선수입니다
        </label>
        <br />
        <label>
          <input
            type="radio"
            name="wm-cms-edge-direction"
            checked={direction === "self-first"}
            disabled={disabled}
            onChange={() => setDirection("self-first")}
          />{" "}
          이 개념이 상대 개념의 선수입니다
        </label>
        <p className={styles.hint} aria-live="polite">
          {sentence}
        </p>
      </fieldset>

      <div className={styles.fieldRow}>
        <label className={styles.label} htmlFor="wm-cms-edge-strength">
          관계 강도 (선택, 0~1 사이 숫자 — 비우면 강도 없음)
        </label>
        <input
          id="wm-cms-edge-strength"
          className={`${styles.input} ${styles.fieldInput}`}
          type="text"
          inputMode="decimal"
          value={strength}
          disabled={disabled}
          onChange={(event) => setStrength(event.target.value)}
        />
      </div>

      {error !== null && (
        <p className={styles.fieldError} role="alert">
          {error}
        </p>
      )}

      <div className={styles.actions}>
        <button className={styles.primaryButton} type="button" disabled={disabled} onClick={() => void submit()}>
          {saving ? "처리 중…" : "관계 추가"}
        </button>
      </div>
      <p className={styles.hint}>
        순환(A→B→…→A처럼 한 바퀴 도는 선수 관계)이 생기면 서버가 거부하고 그 경로를 알려 줍니다.
      </p>
    </section>
  );
}

function SearchResults(props: {
  search: SearchState;
  selfId: string;
  pickedId: string | null;
  disabled: boolean;
  onPick: (row: CmsConceptRow) => void;
  onRetry: () => void;
}) {
  const { search } = props;
  if (search === null) return null;
  if (search.kind === "loading") return <p className={styles.muted}>검색 중…</p>;
  if (search.kind !== "ok") {
    return <CmsFailureBox text={describeCmsFailure(search, "개념 검색")} onRetry={props.onRetry} />;
  }
  // 자기 자신은 후보에서 뺀다(표시 편의 — 자기 참조 거부는 서버가 한다).
  const rows = search.data.items.filter((row) => row.concept_id !== props.selfId);
  if (rows.length === 0) {
    return <p className={styles.emptyBox}>검색 결과가 없습니다(서버 응답 기준). 다른 단어로 검색해 보세요.</p>;
  }
  return (
    <ul className={styles.edgeList} aria-label="상대 개념 검색 결과">
      {rows.map((row) => {
        const picked = row.concept_id === props.pickedId;
        return (
          <li key={row.concept_id}>
            {row.code} {row.name_ko}{" "}
            <button
              className={styles.secondaryButton}
              type="button"
              disabled={props.disabled}
              aria-pressed={picked}
              aria-label={"상대 개념으로 선택: " + row.code + " " + row.name_ko}
              onClick={() => props.onPick(row)}
            >
              {picked ? "선택됨" : "선택"}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
