import { browser } from "wxt/browser";
import { injectScript } from "wxt/utils/inject-script";

import { BRIDGE_PROTOCOL, CONFIG_STORAGE_KEY } from "../src/constants";
import {
  type CaptureConfig,
  captureConfigSchema,
  DEFAULT_CAPTURE_CONFIG,
  type PageConfigMessage,
  pageObservationSchema,
  type RuntimeRequest,
  type RuntimeResponse,
} from "../src/contracts";

const LEASE_MS = 45_000;
const LEASE_RENEWAL_MS = 15_000;

export default defineContentScript({
  matches: ["https://pump.fun/*"],
  runAt: "document_start",
  async main(ctx) {
    let config: CaptureConfig = DEFAULT_CAPTURE_CONFIG;

    const sendLease = (): void => {
      const message: PageConfigMessage = {
        protocol: BRIDGE_PROTOCOL,
        kind: "capture-config",
        config,
        leaseUntilEpochMs: Date.now() + LEASE_MS,
      };
      window.postMessage(message, location.origin);
    };

    ctx.addEventListener(window, "message", (event: MessageEvent<unknown>) => {
      if (event.source !== window || event.origin !== location.origin || !ctx.isValid) {
        return;
      }
      const parsed = pageObservationSchema.safeParse(event.data);
      if (!parsed.success) {
        return;
      }
      const request: RuntimeRequest = {
        kind: "ingest-page-observation",
        observation: parsed.data,
      };
      void browser.runtime.sendMessage<RuntimeRequest, RuntimeResponse>(request);
    });

    await injectScript("/pump-main-world.js", { keepInDom: true });

    try {
      const response = await browser.runtime.sendMessage<RuntimeRequest, RuntimeResponse>({
        kind: "get-config",
      });
      if (response.ok && response.config !== undefined) {
        config = response.config;
      }
    } catch {
      config = DEFAULT_CAPTURE_CONFIG;
    }
    sendLease();
    ctx.setInterval(sendLease, LEASE_RENEWAL_MS);

    browser.storage.onChanged.addListener((changes, areaName) => {
      if (areaName !== "local" || changes[CONFIG_STORAGE_KEY] === undefined) {
        return;
      }
      const candidate = changes[CONFIG_STORAGE_KEY]?.newValue;
      const parsed = captureConfigSchema.safeParse(candidate);
      if (parsed.success) {
        config = parsed.data;
        sendLease();
      }
    });
  },
});
