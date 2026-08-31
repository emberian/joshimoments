import { createContext, use, type ReactNode } from "react";

/**
 * The wall clock, supplied from the top of the tree.
 *
 * Relative ages ("4s ago") are a rendering of the difference between a stamp and
 * now, so `now` has to be a value the tree agrees on rather than something each
 * component reads for itself. Reading `Date.now()` inside a component would make
 * two figures on the same screen disagree about the present depending on when
 * they happened to re-render.
 */
const NowContext = createContext<number>(0);

export function NowProvider({ value, children }: { value: number; children: ReactNode }) {
  return <NowContext value={value}>{children}</NowContext>;
}

export function useNow(): number {
  return use(NowContext);
}
