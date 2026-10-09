"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import {
  fetchCmsConcept,
  fetchCmsConcepts,
  fetchCmsResources,
  type CmsConceptDetail,
  type CmsConceptList,
  type CmsResources,
  type CmsResult,
} from "../_lib/adminCmsApi";

import { CmsConceptStudioPane } from "./CmsConceptStudioPane";
import { CmsFailureBox, CmsSessionGate, describeCmsFailure, type NoteResult } from "./CmsCommon";
import { CmsVersionPane } from "./CmsVersionPane";

import styles from "./Cms.module.css";

/**
 * 개념 작업대 — 개념 목록에서 하나를 골라 **모드에 따라** 다른 패널을 보인다 (P3-12).
 *
 *   studio   개념 편집: 현재 행·관계(읽기 전용) + 새 초안 만들기 + 스킬 연결
 *   versions 판 이력과 상태 전이: 제출·검토·승인·발행 등(서버가 허용한 것만)
 *   deploy   발행과 롤백: 위와 같고 롤백 영역이 더해진다
 *
 * 모드는 **표시를 고르는 값**일 뿐이다. 어떤 처리가 가능한지는 모드가 아니라 서버가 준 값
 * (`allowed_actions`·`can_edit`)과 서버의 권한 검사가 정한다 — 모드를 바꿔도 권한은 늘지 않는다.
 */

export type CmsWorkspaceMode = "studio" | "versions" | "deploy";

const MODE_TITLE: Record<CmsWorkspaceMode, string> = {
  studio: "개념 편집",
  versions: "판 이력과 상태 전이",
  deploy: "발행과 롤백",
};

const PAGE_SIZE = 20;

type ListState = { kind: "loading" } | CmsResult<CmsConceptList>;
type DetailState = { kind: "loading" } | CmsResult<CmsConceptDetail>;

export function CmsConceptWorkspace({ mode }: { mode: CmsWorkspaceMode }) {
  return <CmsSessionGate>{(token, note) => <Body mode={mode} token={token} note={note} />}</CmsSessionGate>;
}

function Body({ mode, token, note }: { mode: CmsWorkspaceMode; token: string; note: NoteResult }) {
  const [resources, setResources] = useState<{ kind: "loading" } | CmsResult<CmsResources>>({
    kind: "loading",
  });
  const [typed, setTyped] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [list, setList] = useState<ListState>({ kind: "loading" });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  // 늦게 도착한 낡은 응답이 최신 화면을 덮지 않게 하는 요청 번호
  const listSeq = useRef(0);

  const loadResources = useCallback(async () => {
    const result = await fetchCmsResources(token);
    note(result.kind);
    setResources(result);
  }, [token, note]);

  const loadList = useCallback(async () => {
    const mine = ++listSeq.current;
    const result = await fetchCmsConcepts(token, q, PAGE_SIZE, offset);
    if (mine !== listSeq.current) return;
    note(result.kind);
    setList(result);
  }, [token, note, q, offset]);

  useEffect(() => {
    void loadResources();
  }, [loadResources]);

  useEffect(() => {
    setList({ kind: "loading" });
    void loadList();
  }, [loadList]);

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    setQ(typed.trim());
    setOffset(0);
    setSelectedId(null);
  }

  if (resources.kind === "loading") return <p className={styles.muted}>화면 구성을 불러오는 중…</p>;
  if (resources.kind !== "ok") {
    return (
      <CmsFailureBox
        text={describeCmsFailure(resources, "화면 구성")}
        onRetry={() => {
          setResources({ kind: "loading" });
          void loadResources();
        }}
      />
    );
  }
  const capabilities = resources.data.capabilities;
  // 스킬 목록 선언 — 읽기 전용 리소스(`audit_type` 없음). 없으면 스킬 찾기 도우미만 빠진다.
  const skillMeta =
    resources.data.resources.find((meta) => meta.key === "skill_node") ?? null;

  return (
    <section className={styles.root}>
      <h2 className={styles.title}>{MODE_TITLE[mode]}</h2>

      <div className={styles.columns}>
        <div className={styles.listPane}>
          <form className={styles.searchRow} onSubmit={submitSearch} role="search">
            <label className={styles.srOnly} htmlFor="wm-cms-concept-q">
              개념 검색
            </label>
            <input
              id="wm-cms-concept-q"
              className={styles.input}
              type="search"
              value={typed}
              maxLength={100}
              placeholder="개념 코드 또는 이름"
              onChange={(event) => setTyped(event.target.value)}
            />
            <button className={styles.secondaryButton} type="submit">
              검색
            </button>
          </form>

          <ConceptList
            list={list}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onPage={setOffset}
            onRetry={() => {
              setList({ kind: "loading" });
              void loadList();
            }}
          />
        </div>

        <div className={styles.detailPane}>
          {selectedId === null ? (
            <p className={styles.muted}>목록에서 개념을 선택하세요.</p>
          ) : (
            <ConceptPane
              key={selectedId}
              mode={mode}
              token={token}
              note={note}
              conceptId={selectedId}
              capabilities={capabilities}
              skillMeta={skillMeta}
              onListChanged={() => void loadList()}
            />
          )}
        </div>
      </div>
    </section>
  );
}

function ConceptList(props: {
  list: ListState;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onPage: (offset: number) => void;
  onRetry: () => void;
}) {
  const { list } = props;
  if (list.kind === "loading") return <p className={styles.muted}>목록을 불러오는 중…</p>;
  if (list.kind !== "ok") {
    return <CmsFailureBox text={describeCmsFailure(list, "개념 목록")} onRetry={props.onRetry} />;
  }
  const data = list.data;
  if (data.total === 0 && data.items.length === 0) {
    // 서버가 200으로 "0건"이라고 답한 경우만 여기 온다 — 실패와 문구·모양을 다르게 한다.
    return <p className={styles.emptyBox}>개념이 없습니다(서버 응답: 0건).</p>;
  }
  const from = data.offset + 1;
  const to = data.offset + data.items.length;
  return (
    <div>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <caption className={styles.srOnly}>개념 목록</caption>
          <thead>
            <tr>
              <th scope="col">코드</th>
              <th scope="col">이름</th>
              <th scope="col">계층</th>
              <th scope="col">발행본</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((row) => {
              const selected = row.concept_id === props.selectedId;
              return (
                <tr key={row.concept_id} className={selected ? styles.rowSelected : undefined}>
                  <th scope="row" className={styles.idCell}>
                    <button
                      className={styles.rowButton}
                      type="button"
                      aria-current={selected ? "true" : undefined}
                      onClick={() => props.onSelect(row.concept_id)}
                    >
                      {row.code}
                      <span className={styles.srOnly}> {row.name_ko} 열기</span>
                    </button>
                  </th>
                  <td>{row.name_ko}</td>
                  <td>{row.level}</td>
                  <td>{row.has_published_version ? "있음" : "없음"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <nav className={styles.pager} aria-label="개념 목록 페이지">
        <button
          className={styles.secondaryButton}
          type="button"
          disabled={data.offset <= 0}
          onClick={() => props.onPage(Math.max(0, data.offset - data.limit))}
        >
          이전
        </button>
        <span>
          전체 {data.total}건 중 {from}–{to}
        </span>
        <button
          className={styles.secondaryButton}
          type="button"
          disabled={data.offset + data.limit >= data.total}
          onClick={() => props.onPage(data.offset + data.limit)}
        >
          다음
        </button>
      </nav>
    </div>
  );
}

function ConceptPane(props: {
  mode: CmsWorkspaceMode;
  token: string;
  note: NoteResult;
  conceptId: string;
  capabilities: string[];
  skillMeta: CmsResources["resources"][number] | null;
  onListChanged: () => void;
}) {
  const { token, note, conceptId } = props;
  const [state, setState] = useState<DetailState>({ kind: "loading" });
  const seq = useRef(0);

  const load = useCallback(async () => {
    const mine = ++seq.current;
    const result = await fetchCmsConcept(token, conceptId);
    if (mine !== seq.current) return;
    note(result.kind);
    setState(result);
  }, [token, note, conceptId]);

  useEffect(() => {
    setState({ kind: "loading" });
    void load();
  }, [load]);

  if (state.kind === "loading") return <p className={styles.muted}>개념을 불러오는 중…</p>;
  if (state.kind !== "ok") {
    return (
      <CmsFailureBox
        text={describeCmsFailure(state, "개념 상세")}
        onRetry={() => {
          setState({ kind: "loading" });
          void load();
        }}
      />
    );
  }
  const detail = state.data;
  const nameKo = typeof detail.live.name_ko === "string" ? detail.live.name_ko : "";
  // 판·발행본이 바뀌면 개념 상세(발행 포인터)와 목록(발행본 유무)을 서버에서 다시 읽는다.
  const refresh = () => {
    void load();
    props.onListChanged();
  };

  return (
    <div>
      <h3 className={styles.detailTitle}>
        {detail.code} {nameKo}
      </h3>
      {props.mode === "studio" ? (
        <CmsConceptStudioPane
          token={token}
          note={note}
          detail={detail}
          skillMeta={props.skillMeta}
          onChanged={refresh}
        />
      ) : (
        <CmsVersionPane
          token={token}
          note={note}
          detail={detail}
          capabilities={props.capabilities}
          emphasis={props.mode === "deploy" ? "deploy" : "history"}
          onChanged={refresh}
        />
      )}
    </div>
  );
}
