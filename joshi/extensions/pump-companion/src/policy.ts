import { PARITY_REQUEST_FINGERPRINT_CONTRACT, REQUEST_FINGERPRINT_CONTRACT } from "./constants";
import type { CaptureConfig, OriginId, RouteId } from "./contracts";
import { sha256Id, sha256Utf8 } from "./hash";

export interface CaptureRoute {
  id: RouteId;
  parityRouteId: string;
  paginationKind: string;
  originId: OriginId;
  origin: string;
  path: RegExp;
  normalizer: "coin" | "callouts" | "following" | "community" | "messages" | "feed";
}

const MINT_OR_ID = "[^/?#]{20,128}";

export const CAPTURE_ROUTES: readonly CaptureRoute[] = [
  {
    id: "coin-v2",
    parityRouteId: "coin_exact",
    paginationKind: "none",
    originId: "pump-frontend",
    origin: "https://frontend-api-v3.pump.fun",
    path: new RegExp(`^/coins-v2/${MINT_OR_ID}/?$`),
    normalizer: "coin",
  },
  {
    id: "callout-recent",
    parityRouteId: "callout_recent",
    paginationKind: "page_token",
    originId: "pump-frontend",
    origin: "https://frontend-api-v3.pump.fun",
    path: /^\/callout\/recent\/?$/,
    normalizer: "callouts",
  },
  {
    id: "callout-mint",
    parityRouteId: "callout_by_mint",
    paginationKind: "page_token",
    originId: "pump-frontend",
    origin: "https://frontend-api-v3.pump.fun",
    path: new RegExp(`^/callout/(?:top|list)/${MINT_OR_ID}/?$`),
    normalizer: "callouts",
  },
  {
    id: "following",
    parityRouteId: "following",
    paginationKind: "cursor",
    originId: "pump-frontend",
    origin: "https://frontend-api-v3.pump.fun",
    path: new RegExp(`^/following/${MINT_OR_ID}/?$`),
    normalizer: "following",
  },
  {
    id: "community",
    parityRouteId: "community_messages",
    paginationKind: "none",
    originId: "coin-communities",
    origin: "https://api.coin-communities.xyz",
    path: new RegExp(`^/api/v1/communities/${MINT_OR_ID}/?$`),
    normalizer: "community",
  },
  {
    id: "community-messages",
    parityRouteId: "community_messages",
    paginationKind: "cursor",
    originId: "coin-communities",
    origin: "https://api.coin-communities.xyz",
    path: new RegExp(`^/api/v1/communities/${MINT_OR_ID}/messages/public/?$`),
    normalizer: "messages",
  },
  {
    id: "community-callouts",
    parityRouteId: "community_callouts",
    paginationKind: "cursor",
    originId: "coin-communities",
    origin: "https://api.coin-communities.xyz",
    path: new RegExp(
      `^/api/v1/communities/${MINT_OR_ID}/callouts(?:/${MINT_OR_ID}(?:/replies)?)?/public/?$`,
    ),
    normalizer: "callouts",
  },
  {
    id: "community-feed",
    parityRouteId: "community_messages",
    paginationKind: "cursor",
    originId: "coin-communities",
    origin: "https://api.coin-communities.xyz",
    path: /^\/api\/v1\/(?:feed\/public|communities\/top)\/?$/,
    normalizer: "feed",
  },
  {
    id: "profile-community",
    parityRouteId: "community_messages",
    paginationKind: "cursor",
    originId: "pump-profile",
    origin: "https://profile-api.pump.fun",
    path: new RegExp(
      `^/api/v1/communities/${MINT_OR_ID}/(?:messages|callouts)(?:/${MINT_OR_ID}(?:/replies)?)?/?$`,
    ),
    normalizer: "messages",
  },
] as const;

export function matchCaptureRoute(input: string | URL, config: CaptureConfig): CaptureRoute | null {
  let url: URL;
  try {
    url = input instanceof URL ? input : new URL(input);
  } catch {
    return null;
  }

  if (url.protocol !== "https:") {
    return null;
  }

  return (
    CAPTURE_ROUTES.find(
      (route) =>
        config.origins[route.originId] &&
        url.origin === route.origin &&
        route.path.test(url.pathname),
    ) ?? null
  );
}

export function isPumpPage(url: string | undefined): boolean {
  if (url === undefined) {
    return false;
  }
  try {
    const parsed = new URL(url);
    return parsed.protocol === "https:" && parsed.hostname === "pump.fun";
  } catch {
    return false;
  }
}

const COVERAGE_QUERY_KEYS = new Set([
  "after",
  "before",
  "cursor",
  "includeReplies",
  "limit",
  "offset",
  "order",
  "page",
  "pageToken",
  "sort",
  "timeframe",
]);

export interface RequestProjection {
  canonical: string;
  completeness: "complete" | "partial-query";
}

/** The canonical string is transient input to a digest and must never be exported or persisted. */
export function projectRequestForFingerprint(url: URL, route: CaptureRoute): RequestProjection {
  const admitted: Array<[string, string]> = [];
  let omitted = 0;
  for (const [key, value] of url.searchParams.entries()) {
    if (COVERAGE_QUERY_KEYS.has(key) && value.length <= 1_024) admitted.push([key, value]);
    else omitted += 1;
  }
  admitted.sort(([leftKey, leftValue], [rightKey, rightValue]) =>
    leftKey === rightKey ? leftValue.localeCompare(rightValue) : leftKey.localeCompare(rightKey),
  );
  return {
    canonical: JSON.stringify({
      contract: REQUEST_FINGERPRINT_CONTRACT,
      method: "GET",
      routeId: route.id,
      origin: url.origin,
      path: url.pathname,
      query: admitted,
    }),
    completeness: omitted === 0 ? "complete" : "partial-query",
  };
}

const PAGINATION_STATE_KEYS = new Set([
  "after",
  "before",
  "beforeId",
  "cursor",
  "offset",
  "page",
  "pageToken",
]);
const PAGE_SIZE_KEYS = new Set(["limit", "size"]);

export interface ParityRequestProjection {
  requestFingerprint: string;
  requestFingerprintContract: typeof PARITY_REQUEST_FINGERPRINT_CONTRACT;
  visibleFilterFingerprint: string;
  cursorInFingerprint: string | null;
  paginationKind: string;
  pageOrdinal: string;
  completeness: "complete" | "partial-query";
}

/**
 * Digest-only request-state projection shared with the direct client. Raw path/query values exist
 * only in this main-world call and are never posted to the extension or sink.
 */
export async function projectRequestForParity(
  url: URL,
  route: CaptureRoute,
): Promise<ParityRequestProjection> {
  const requestLines = [
    `contract=${PARITY_REQUEST_FINGERPRINT_CONTRACT}`,
    "method=GET",
    `routeId=${route.parityRouteId}`,
    `origin=${url.origin}`,
    `path.sha256=${await sha256Utf8(url.pathname)}`,
  ];
  const filterLines = [`routeId=${route.parityRouteId}`];
  const cursorLines = [`routeId=${route.parityRouteId}`];
  const query = [...url.searchParams.entries()].sort(
    ([leftName, leftValue], [rightName, rightValue]) =>
      leftName === rightName
        ? leftValue.localeCompare(rightValue)
        : leftName.localeCompare(rightName),
  );
  let omitted = 0;
  let hasCursor = false;
  for (const [name, value] of query) {
    if (name.length > 128 || value.length > 1_024) {
      omitted += 1;
      continue;
    }
    const line = `query.${name}.sha256=${await sha256Utf8(value)}`;
    requestLines.push(line);
    if (PAGINATION_STATE_KEYS.has(name)) {
      hasCursor = true;
      cursorLines.push(line);
    } else if (!PAGE_SIZE_KEYS.has(name)) {
      filterLines.push(line);
    }
  }
  const page = url.searchParams.get("page");
  const offset = url.searchParams.get("offset");
  const size = url.searchParams.get("limit") ?? url.searchParams.get("size");
  let pageOrdinal = "0";
  if (page !== null && /^(?:0|[1-9][0-9]*)$/.test(page)) {
    pageOrdinal = page;
  } else if (
    offset !== null &&
    size !== null &&
    /^(?:0|[1-9][0-9]*)$/.test(offset) &&
    /^[1-9][0-9]*$/.test(size)
  ) {
    pageOrdinal = (BigInt(offset) / BigInt(size)).toString();
  }
  return {
    requestFingerprint: await sha256Utf8(requestLines.join("\n")),
    requestFingerprintContract: PARITY_REQUEST_FINGERPRINT_CONTRACT,
    visibleFilterFingerprint: await sha256Utf8(filterLines.join("\n")),
    cursorInFingerprint: hasCursor
      ? await sha256Id(new TextEncoder().encode(cursorLines.join("\n")))
      : null,
    paginationKind: route.paginationKind,
    pageOrdinal,
    completeness: omitted === 0 ? "complete" : "partial-query",
  };
}
