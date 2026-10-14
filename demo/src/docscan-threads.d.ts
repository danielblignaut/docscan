// The multithreaded build of docscan (see vite.config.ts): the same API, plus
// `initThreadPool`, which starts the Web Workers rayon runs on.
declare module "docscan-threads" {
  export * from "docscan";
  export { default } from "docscan";
  export function initThreadPool(threads: number): Promise<void>;
}
