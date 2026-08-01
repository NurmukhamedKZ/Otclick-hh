const DEV = import.meta.env.DEV;

export const debug = (...a: unknown[]) => {
  if (DEV) console.log("[otclick]", ...a);
};
export const warn = (...a: unknown[]) => {
  if (DEV) console.warn("[otclick]", ...a);
};
export const error = (...a: unknown[]) => {
  console.error("[otclick]", ...a);
};
