import { defineConfig } from "wxt";

export default defineConfig({
  manifestVersion: 3,
  vite: () => ({
    resolve: {
      alias: { punycode: "punycode/" },
    },
  }),
  manifest: {
    name: "Joshi Pump Companion",
    description:
      "Accessibility-first, origin-scoped capture of allowlisted observations already delivered to Ember's Pump session.",
    version: "0.1.0",
    minimum_chrome_version: "120",
    permissions: ["alarms", "storage"],
    host_permissions: ["https://pump.fun/*", "http://127.0.0.1:43119/*"],
    action: {
      default_title: "Joshi Pump Companion — paused",
    },
    web_accessible_resources: [
      {
        resources: ["pump-main-world.js"],
        matches: ["https://pump.fun/*"],
      },
    ],
    browser_specific_settings: {
      gecko: {
        id: "pump-companion@joshi.local",
        strict_min_version: "140.0",
        data_collection_permissions: {
          required: [
            "personalCommunications",
            "personallyIdentifyingInfo",
            "websiteActivity",
            "websiteContent",
          ],
        },
      },
    },
  },
});
