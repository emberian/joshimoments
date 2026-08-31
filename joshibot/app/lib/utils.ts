/**
 * Kept as the import site the shadcn primitives already use (`@/lib/utils`).
 * The implementations live in `format.ts` so there is exactly one `cn` and one
 * set of formatters in the bundle.
 */
export {
  BASE58_ADDRESS,
  cn,
  compact,
  decimals,
  formatSpan,
  NO_DATA,
  parseDecimal,
  relativeAge,
  shortAddress,
  stampUtc,
  timeOnly,
} from "./format";
