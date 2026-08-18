import { isLosslessNumber } from "lossless-json";

import { MAX_RECORDS_PER_RESPONSE } from "./constants";
import type { FieldValue, NormalizedRecord } from "./contracts";
import type { CaptureRoute } from "./policy";

type JsonObject = Record<string, unknown>;

const COMMON_FIELDS = [
  "id",
  "mint",
  "coinMint",
  "tokenAddress",
  "name",
  "symbol",
  "username",
  "userName",
  "displayName",
  "userId",
  "walletAddress",
  "address",
  "xUsername",
  "twitterId",
  "thesis",
  "content",
  "description",
  "createdAt",
  "created_timestamp",
  "timestamp",
  "last_trade_timestamp",
  "latestPostAt",
  "computedAt",
  "complete",
  "isSpam",
  "isHarmful",
  "isDeleted",
  "replyCount",
  "reply_count",
  "commentCount",
  "likeCount",
  "likes",
  "memberCount",
  "member_count",
  "postCount",
  "post_count",
  "totalLikes",
  "followers",
  "nativeFollowerCount",
  "parentMessageId",
  "parentCalloutId",
  "calloutPrice",
  "calloutMarketCap",
  "marketCap",
  "market_cap",
  "usd_market_cap",
  "pump_swap_pool",
  "metadata_uri",
  "image_uri",
  "creator",
  "mentions",
] as const;

const FUTURE_OUTCOME_FIELDS = new Set([
  "multiple",
  "multiplier",
  "maxMultiplier",
  "maxPriceSol",
  "maxMultiplierAt",
  "peakTimestamp",
]);

function asObject(value: unknown): JsonObject | null {
  return value !== null &&
    typeof value === "object" &&
    !Array.isArray(value) &&
    !isLosslessNumber(value)
    ? (value as JsonObject)
    : null;
}

function asRows(value: unknown, keys: readonly string[]): JsonObject[] {
  if (Array.isArray(value)) {
    return value.map(asObject).filter((row): row is JsonObject => row !== null);
  }
  const object = asObject(value);
  if (object === null) return [];
  for (const key of keys) {
    const child = object[key];
    if (Array.isArray(child)) {
      return child.map(asObject).filter((row): row is JsonObject => row !== null);
    }
  }
  const nestedData = asObject(object.data);
  if (nestedData !== null) {
    for (const key of keys) {
      const child = nestedData[key];
      if (Array.isArray(child)) {
        return child.map(asObject).filter((row): row is JsonObject => row !== null);
      }
    }
  }
  return [];
}

function toFieldValue(value: unknown): FieldValue | undefined {
  if (value === null) return { encoding: "null", value: null };
  if (typeof value === "boolean") return { encoding: "boolean", value };
  if (typeof value === "string") return { encoding: "utf8", value };
  if (isLosslessNumber(value)) {
    return { encoding: "json-number-lexeme", value: value.value };
  }
  if (typeof value === "number" || typeof value === "bigint") {
    throw new TypeError("numeric values must enter normalization through the lossless JSON parser");
  }
  if (Array.isArray(value)) {
    const strings = value
      .slice(0, 100)
      .map((item) => {
        if (typeof item === "string") return item;
        const object = asObject(item);
        if (object !== null) {
          return typeof object.username === "string"
            ? object.username
            : typeof object.id === "string"
              ? object.id
              : undefined;
        }
        return undefined;
      })
      .filter((item): item is string => item !== undefined);
    return { encoding: "utf8-list", value: strings };
  }
  return undefined;
}

function project(row: JsonObject): Record<string, FieldValue> {
  const fields: Record<string, FieldValue> = {};
  for (const key of COMMON_FIELDS) {
    if (FUTURE_OUTCOME_FIELDS.has(key)) continue;
    const value = toFieldValue(row[key]);
    if (value !== undefined) fields[key] = value;
  }
  return fields;
}

function contextId(path: string): string | null {
  const parts = path.split("/").filter(Boolean);
  const communitiesIndex = parts.indexOf("communities");
  if (communitiesIndex >= 0) return parts[communitiesIndex + 1] ?? null;
  return parts.at(-1) ?? null;
}

function firstString(row: JsonObject, keys: readonly string[]): string | null {
  for (const key of keys) {
    const value = row[key];
    if (typeof value === "string") return value;
    if (isLosslessNumber(value)) return value.value;
  }
  return null;
}

function makeRecord(
  kind: string,
  route: CaptureRoute,
  path: string,
  row: JsonObject,
  index: number,
): NormalizedRecord {
  const fields = project(row);
  const context = contextId(path);
  if (context !== null && fields.contextId === undefined) {
    fields.contextId = { encoding: "utf8", value: context };
  }
  const rowKey = firstString(row, [
    "id",
    "calloutId",
    "messageId",
    "mint",
    "coinMint",
    "tokenAddress",
    "address",
    "timestamp",
    "createdAt",
  ]);
  return {
    ordinal: String(index),
    kind,
    naturalKey: `${route.id}:${context ?? "none"}:${rowKey ?? index}`,
    fields,
  };
}

export interface NormalizationResult {
  records: NormalizedRecord[];
  sourceRecordCount: number;
  omittedRecordCount: number;
}

export function normalizeResponse(
  route: CaptureRoute,
  path: string,
  value: unknown,
): NormalizationResult {
  let rows: JsonObject[];
  let kind: string;
  switch (route.normalizer) {
    case "coin": {
      const row = asObject(value);
      rows = row === null ? [] : [row];
      kind = "coin-current";
      break;
    }
    case "callouts":
      rows = asRows(value, ["callouts", "replies", "items"]);
      kind = route.id === "callout-recent" ? "callout-feed-item" : "callout";
      break;
    case "following":
      rows = asRows(value, ["following", "items", "users"]);
      kind = "following-edge-current";
      break;
    case "community": {
      const row = asObject(value);
      rows = row === null ? [] : [row];
      kind = "community-current";
      break;
    }
    case "messages":
      rows = asRows(value, ["messages", "replies", "items"]);
      kind = route.id === "profile-community" ? "authenticated-social-item" : "community-message";
      break;
    case "feed":
      rows = asRows(value, ["messages", "communities", "items", "feed"]);
      kind = "community-feed-item";
      break;
  }
  const records = rows
    .slice(0, MAX_RECORDS_PER_RESPONSE)
    .map((row, index) => makeRecord(kind, route, path, row, index));
  return {
    records,
    sourceRecordCount: rows.length,
    omittedRecordCount: Math.max(0, rows.length - records.length),
  };
}

export const normalizedFieldAllowlist = COMMON_FIELDS.filter(
  (key) => !FUTURE_OUTCOME_FIELDS.has(key),
);
