/* 원자적 JSON 저장 (HARN-206) — 임시 파일에 쓰고 rename 한다.
   이 모듈이 앱 안에서 파일을 *쓰는* 유일한 곳이다. 작업공간의 backlog/ 경로를 여기로 넘기는
   호출이 없어야 한다(거버넌스 테스트 tests/unit/governance.test.ts가 소스를 스캔한다). */
import { mkdirSync, promises as fs, renameSync, unlinkSync, writeFileSync } from "node:fs";
import path from "node:path";

export async function readJson<T>(file: string): Promise<T | null> {
  try {
    const text = await fs.readFile(file, "utf8");
    return JSON.parse(text) as T;
  } catch (err) {
    const e = err as NodeJS.ErrnoException;
    if (e && e.code === "ENOENT") return null;
    // 손상된 파일은 조용히 null로 접지 않는다 — 호출자가 사유를 보게 예외 타입명을 붙여 던진다
    throw new Error(`${e?.name ?? "Error"}: ${file} 읽기 실패 — ${e?.message ?? String(err)}`);
  }
}

export async function atomicWriteJson(file: string, value: unknown): Promise<void> {
  await fs.mkdir(path.dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.${Date.now()}.tmp`;
  const text = JSON.stringify(value, null, 2) + "\n";
  try {
    await fs.writeFile(tmp, text, "utf8");
    await fs.rename(tmp, file);
  } catch (err) {
    try { await fs.unlink(tmp); } catch { /* 임시 파일이 없으면 그만 */ }
    throw err;
  }
}

/** 동기판 — 창을 닫는 순간(프로세스가 곧 끝난다)처럼 비동기 쓰기가 끝나기 전에 종료될 수 있는 자리 전용 (HARN-208) */
export function atomicWriteJsonSync(file: string, value: unknown): void {
  mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.${Date.now()}.tmp`;
  try {
    writeFileSync(tmp, JSON.stringify(value, null, 2) + "\n", "utf8");
    renameSync(tmp, file);
  } catch (err) {
    try { unlinkSync(tmp); } catch { /* 임시 파일이 없으면 그만 */ }
    throw err;
  }
}

export async function removeFile(file: string): Promise<boolean> {
  try {
    await fs.unlink(file);
    return true;
  } catch (err) {
    const e = err as NodeJS.ErrnoException;
    if (e && e.code === "ENOENT") return false;
    throw err;
  }
}
