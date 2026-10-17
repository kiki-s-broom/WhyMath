"use client";

import { usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { fetchCmsResources, type CmsResources, type CmsResult } from "../_lib/adminCmsApi";

import { CmsFailureBox, CmsSessionGate, describeCmsFailure, type NoteResult } from "./CmsCommon";
import { CmsResourcePanel } from "./CmsResourcePanel";

import styles from "./Cms.module.css";

/**
 * 개념 외 리소스 화면 — 교육과정·교수전략·오개념·콘텐츠 라이브러리(P3-12).
 *
 * **화면 코드에 리소스 이름도, 모듈 id도, 경로도 없다.** 서버가 리소스마다 "이 화면의 경로"(`route`)를
 * 내려 주고(레지스트리에서 파생), 이 컴포넌트는 **자기 경로와 같은 `route`의 리소스**를 그린다. 그래서
 * 네 화면이 같은 컴포넌트를 쓰고, 리소스가 한 화면에 늘거나 줄어도 이 파일은 바뀌지 않는다
 * (하드코딩 nav 금지 — 04 §2 원칙7 — 의 같은 정신).
 */

/** 끝 슬래시를 떼어 비교한다 — 정적 export는 `trailingSlash`라 경로가 `/…/`로 끝난다. */
function normalize(path: string): string {
  return path.replace(/\/+$/, "");
}

export function CmsResourceScreen() {
  return <CmsSessionGate>{(token, note) => <Body token={token} note={note} />}</CmsSessionGate>;
}

function Body({ token, note }: { token: string; note: NoteResult }) {
  const pathname = usePathname();
  const [state, setState] = useState<{ kind: "loading" } | CmsResult<CmsResources>>({ kind: "loading" });
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  const load = useCallback(async () => {
    const result = await fetchCmsResources(token);
    note(result.kind);
    setState(result);
  }, [token, note]);

  useEffect(() => {
    void load();
  }, [load]);

  if (state.kind === "loading") return <p className={styles.muted}>화면 구성을 불러오는 중…</p>;
  if (state.kind !== "ok") {
    return (
      <CmsFailureBox
        text={describeCmsFailure(state, "화면 구성")}
        onRetry={() => {
          setState({ kind: "loading" });
          void load();
        }}
      />
    );
  }

  const here = normalize(pathname ?? "");
  const metas = state.data.resources.filter((meta) => normalize(meta.route) === here);
  if (metas.length === 0) {
    return (
      <p className={styles.emptyBox}>
        이 화면({here || "경로 미확인"})에 연결된 리소스를 서버가 알려 주지 않았습니다.
      </p>
    );
  }
  const current = metas.find((meta) => meta.key === selectedKey) ?? metas[0];

  return (
    <section className={styles.root}>
      <h2 className={styles.title}>{metas.map((meta) => meta.label_ko).join(" · ")}</h2>

      {metas.length > 1 && (
        <div role="group" aria-label="리소스 선택" className={styles.tabs}>
          {metas.map((meta) => (
            <button
              key={meta.key}
              type="button"
              className={styles.tab}
              aria-pressed={meta.key === current.key}
              onClick={() => setSelectedKey(meta.key)}
            >
              {meta.label_ko}
            </button>
          ))}
        </div>
      )}

      <CmsResourcePanel key={current.key} token={token} note={note} meta={current} />
    </section>
  );
}
