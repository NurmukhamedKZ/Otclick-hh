/** Toolbar button namespace. This build targets Manifest V2, where the API is
 *  `browserAction`; MV3 renamed it to `action`. Touching the absent one throws
 *  while the background script is still registering its listeners, which takes
 *  down every listener with it — so resolve it defensively. */
export function toolbarButtonApi<T>(ns: { browserAction?: T; action?: T }): T {
  const api = ns.browserAction ?? ns.action;
  if (!api) throw new Error("no toolbar button API (neither browserAction nor action)");
  return api;
}
