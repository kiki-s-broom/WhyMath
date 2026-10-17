"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { fetchCmsList, type CmsList, type CmsResourceMeta, type CmsResult } from "../_lib/adminCmsApi";

import { CmsFailureBox, cellText, describeCmsFailure, type NoteResult } from "./CmsCommon";
import { CmsResourceDetail } from "./CmsResourceDetail";

import styles from "./Cms.module.css";

/**
 * 리소스 1종의 목록(검색·페이지) + 상세 패널 (P3-12).
 *
 * 목록 컬럼·키 컬럼은 서버 선언(`meta`)을 그대로 따른다 — 화면이 "첫 컬럼이 키겠지"라고 추정하지
 * 않는다. 0건(200)과 불러오지 못함(실패 유니온)은 다른 화면으로 가른다.
 *
 * `onPickRow`가 있으면 **선택기 모드**다: 상세 패널 없이 행마다 "선택" 버튼만 둔다(개념 초안 폼의
 * 스킬 찾기가 이 모드로 같은 목록을 재사용한다).
 */

const PAGE_SIZE = 20;

type ListState = { kind: "loading" } | CmsResult<CmsList>;

interface Props {
  token: string;
  note: NoteResult;
  meta: CmsResourceMeta;
  onPickRow?: (row: Record<string, unknown>) => void;
  pickLabel?: string;
  pageSize?: number;
}

export function CmsResourcePanel({ token, note, meta, onPickRow, pickLabel, pageSize }: Props) {
  const size = pageSize ?? PAGE_SIZE;
  const [typed, setTyped] = useState("");
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const [list, setList] = useState<ListState>({ kind: "loading" });
  const [selectedPk, setSelectedPk] = useState<string | null>(null);
  // 늦게 도착한 낡은 응답이 최신 화면을 덮지 않게 하는 요청 번호
  const seq = useRef(0);

  const labelOf = useCallback(
    (column: string): string => meta.fields.find((f) => f.name === column)?.label_ko ?? column,
    [meta.fields],
  );

  const loadList = useCallback(async () => {
    const mine = ++seq.current;
    const result = await fetchCmsList(token, meta.key, q, size, offset);
    if (mine !== seq.current) return;
    note(result.kind);
    setList(result);
  }, [token, note, meta.key, q, size, offset]);

  useEffect(() => {
    setList({ kind: "loading" });
    void loadList();
  }, [loadList]);

  // 마지막 항목이 사라져 현재 페이지가 비면(총건수는 남음) 마지막 유효 페이지로 물러난다.
  useEffect(() => {
    if (list.kind !== "ok") return;
    if (list.data.items.length === 0 && list.data.total > 0 && offset > 0) {
      setOffset(Math.floor((list.data.total - 1) / size) * size);
    }
  }, [list, offset, size]);

  function submitSearch(event: FormEvent) {
    event.preventDefault();
    setQ(typed.trim());
    setOffset(0);
    setSelectedPk(null);
  }

  const picker = onPickRow !== undefined;

  return (
    <div className={picker ? undefined : styles.columns}>
      <div className={picker ? undefined : styles.listPane}>
        <form className={styles.searchRow} onSubmit={submitSearch} role="search">
          <label className={styles.srOnly} htmlFor={"wm-cms-q-" + meta.key}>
            {meta.label_ko} 검색
          </label>
          <input
            id={"wm-cms-q-" + meta.key}
            className={styles.input}
            type="search"
            value={typed}
            maxLength={100}
            placeholder={meta.label_ko + " 검색"}
            onChange={(event) => setTyped(event.target.value)}
          />
          <button className={styles.secondaryButton} type="submit">
            검색
          </button>
        </form>

        <ListBody
          list={list}
          meta={meta}
          labelOf={labelOf}
          selectedPk={selectedPk}
          pickLabel={pickLabel ?? "선택"}
          picker={picker}
          onOpen={(pk) => setSelectedPk(pk)}
          onPick={onPickRow}
          onPage={setOffset}
          onRetry={() => {
            setList({ kind: "loading" });
            void loadList();
          }}
        />
      </div>

      {!picker && (
        <div className={styles.detailPane}>
          {selectedPk === null ? (
            <p className={styles.muted}>목록에서 항목을 선택하세요.</p>
          ) : (
            <CmsResourceDetail
              key={meta.key + ":" + selectedPk}
              token={token}
              note={note}
              meta={meta}
              pk={selectedPk}
              onChanged={() => void loadList()}
            />
          )}
        </div>
      )}
    </div>
  );
}

function ListBody(props: {
  list: ListState;
  meta: CmsResourceMeta;
  labelOf: (column: string) => string;
  selectedPk: string | null;
  pickLabel: string;
  picker: boolean;
  onOpen: (pk: string) => void;
  onPick: ((row: Record<string, unknown>) => void) | undefined;
  onPage: (offset: number) => void;
  onRetry: () => void;
}) {
  const { list, meta } = props;
  if (list.kind === "loading") return <p className={styles.muted}>목록을 불러오는 중…</p>;
  if (list.kind !== "ok") {
    return <CmsFailureBox text={describeCmsFailure(list, "목록")} onRetry={props.onRetry} />;
  }
  const data = list.data;
  if (data.total === 0 && data.items.length === 0) {
    // 서버가 200으로 "0건"이라고 답한 경우만 여기 온다 — 실패와 문구·모양을 다르게 한다.
    return <p className={styles.emptyBox}>{meta.label_ko} 항목이 없습니다(서버 응답: 0건).</p>;
  }
  const from = data.offset + 1;
  const to = data.offset + data.items.length;
  return (
    <div>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <caption className={styles.srOnly}>{meta.label_ko} 목록</caption>
          <thead>
            <tr>
              {data.columns.map((column) => (
                <th key={column} scope="col">
                  {props.labelOf(column)}
                </th>
              ))}
              {props.picker && <th scope="col">선택</th>}
            </tr>
          </thead>
          <tbody>
            {data.items.map((row) => {
              const pk = cellText(row[meta.pk_column]);
              const selected = pk === props.selectedPk;
              return (
                <tr key={pk} className={selected ? styles.rowSelected : undefined}>
                  {data.columns.map((column) =>
                    column === meta.pk_column && !props.picker ? (
                      <th key={column} scope="row" className={styles.idCell}>
                        <button
                          className={styles.rowButton}
                          type="button"
                          aria-current={selected ? "true" : undefined}
                          title={pk}
                          onClick={() => props.onOpen(pk)}
                        >
                          {pk.length > 12 ? pk.slice(0, 8) + "…" : pk}
                          <span className={styles.srOnly}> {pk} 상세 열기</span>
                        </button>
                      </th>
                    ) : (
                      <td key={column}>{cellText(row[column])}</td>
                    ),
                  )}
                  {props.picker && (
                    <td>
                      <button
                        className={styles.secondaryButton}
                        type="button"
                        onClick={() => props.onPick?.(row)}
                      >
                        {props.pickLabel}
                      </button>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <nav className={styles.pager} aria-label={meta.label_ko + " 목록 페이지"}>
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
