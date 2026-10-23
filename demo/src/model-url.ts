/** Build-time content versions prevent cached models outliving their release. */
declare const __MODEL_REVISIONS__: Record<string, string>;

export function modelUrl(name: string): string {
  const version = __MODEL_REVISIONS__[name];
  return `${import.meta.env.BASE_URL}models/${name}${version ? `?v=${version}` : ""}`;
}
