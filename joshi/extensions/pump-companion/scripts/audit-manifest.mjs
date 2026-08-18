import { readFile } from "node:fs/promises";

const manifestUrl = new URL("../.output/chrome-mv3/manifest.json", import.meta.url);
const manifest = JSON.parse(await readFile(manifestUrl, "utf8"));

const exact = (actual, expected, label) => {
  const left = JSON.stringify([...actual].sort());
  const right = JSON.stringify([...expected].sort());
  if (left !== right) {
    throw new Error(`${label} mismatch: ${left} != ${right}`);
  }
};

if (manifest.manifest_version !== 3) {
  throw new Error("companion must build as Manifest V3");
}
exact(manifest.permissions ?? [], ["alarms", "storage"], "permissions");
exact(
  manifest.host_permissions ?? [],
  ["https://pump.fun/*", "http://127.0.0.1:43119/*"],
  "host permissions",
);

const forbidden = [
  "activeTab",
  "bookmarks",
  "browsingData",
  "cookies",
  "debugger",
  "declarativeNetRequest",
  "downloads",
  "history",
  "identity",
  "nativeMessaging",
  "privacy",
  "proxy",
  "scripting",
  "tabs",
  "webNavigation",
  "webRequest",
  "webRequestBlocking",
];
const present = forbidden.filter((permission) => (manifest.permissions ?? []).includes(permission));
if (present.length > 0) {
  throw new Error(`forbidden permissions present: ${present.join(", ")}`);
}

const contentMatches = (manifest.content_scripts ?? []).flatMap((entry) => entry.matches ?? []);
exact(contentMatches, ["https://pump.fun/*"], "content-script matches");

const resources = (manifest.web_accessible_resources ?? []).flatMap(
  (entry) => entry.resources ?? [],
);
if (!resources.includes("pump-main-world.js")) {
  throw new Error("main-world observer is not an explicit web-accessible resource");
}

process.stdout.write(
  "manifest audit passed: exact Pump + loopback scope, no broad/session permissions\n",
);
