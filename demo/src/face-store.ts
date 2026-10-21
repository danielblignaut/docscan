// Demo storage for Face ID enrolments: face templates kept in this browser's
// IndexedDB and nowhere else. A template is biometric data (POPIA s.26
// special personal information); this demo never sends it anywhere, and
// "Forget" deletes it. A real deployment needs consent, a retention rule and
// encryption at rest, which this demo does not provide.

export interface Enrolment {
  id: string;
  label: string;
  template: number[];
  model: string;
  createdAt: string;
}

const DB = "docscan-demo-face-id";
const STORE = "enrolments";

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: "id" });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function tx<T>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await open();
  return new Promise((resolve, reject) => {
    const t = db.transaction(STORE, mode);
    const r = fn(t.objectStore(STORE));
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
    t.oncomplete = () => db.close();
  });
}

export const listEnrolments = () => tx<Enrolment[]>("readonly", (s) => s.getAll() as IDBRequest<Enrolment[]>);
export const saveEnrolment = (e: Enrolment) => tx("readwrite", (s) => s.put(e));
export const forgetEnrolment = (id: string) => tx("readwrite", (s) => s.delete(id));
export const forgetAll = () => tx("readwrite", (s) => s.clear());
