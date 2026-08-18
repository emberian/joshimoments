# Engineering lane 16 — Product shell and UI technology

Status: engineering option assessment, not an implementation plan or transaction
authorization.

Evidence checked: 2026-08-16. Platform APIs and support levels are temporally unstable; links
below are official project, browser-vendor, Apple, or standards sources and should be
rechecked at the decision point.

## 1. Decision summary

Use a **TypeScript/React browser application served by the local core as the first product
shell**. Keep the renderer deployable unchanged in an ordinary browser, an installed web
app, and a later desktop wrapper. Add a **thin WebExtension companion** only for observing
and augmenting an already-authenticated Pump tab. Do not make the extension, an embedded
remote Pump page, or any native wrapper the system of record.

Evaluate **Tauri 2 as the first optional desktop wrapper**, after the browser spike proves
the product loop and only if desktop capabilities earn their cost. Prefer **Electron** over
Tauri only if a bundled, known Chromium version, first-class page capture, or Chromium
`WebContents` isolation is demonstrably necessary and WKWebView fails the measured workload.
Do not begin with Avalonia or an all-native SwiftUI/AppKit shell.

The reversible shape is:

    immutable local services and event log
                  |
         authenticated local API
       WebSocket/SSE + query endpoints
                  |
        shell-neutral web renderer
          /         |          \
    browser/PWA  extension UI  Tauri later
                               Electron only if falsified

This is not a recommendation to reuse `joshibot` wholesale. Its React 19/Vite 8,
Lightweight Charts 5.2, Radix, Tailwind, and roughly 9.4k lines of TS/TSX are useful spike
compost. The renderer contract and workload tests, not inheritance, decide what survives.

## 2. The shell decision is two decisions

### 2.1 Companion mode

In companion mode Ember is still using Pump, Padre, or another reference application. The
value of our software is that it can:

- observe the actual signed-in page and its viewport;
- capture choice sets, rank, scroll position, opened coin, and navigation;
- show operator gestures and episode context beside the reference page;
- transmit structured observations to the local evidence store;
- avoid changing the speed or semantics of the reference workflow.

A normal web app cannot inspect another origin's tab or DOM. A browser extension with
explicit host permission can run a content script in the actual page; Chrome content scripts
share the DOM while using an isolated JavaScript world, and Chrome's side-panel API can keep
a companion surface beside a page. [Chrome content scripts](https://developer.chrome.com/docs/extensions/develop/concepts/content-scripts),
[Chrome side panel](https://developer.chrome.com/docs/extensions/reference/api/sidePanel)

The companion is consequently a WebExtension problem, not a reason to turn the entire
cockpit into an embedded browser.

### 2.2 Replacement mode

In replacement mode our collectors, tapes, social graph, quotes, accounting, and episode
model supply the information surface. The shell owns feed rendering, charting, gestures,
replay, and interviews. It does not need Pump's browser profile or cookies.

This is an ordinary high-rate local web application problem. The first shell should run in a
browser because that is the smallest environment that exercises the real chart, DOM,
virtualization, accessibility, touch, and keyboard stack. A desktop wrapper can be added
around the same renderer after native requirements are measured.

### 2.3 Hybrid operation

The likely transition is hybrid:

1. extension observes the reference page;
2. cockpit renders our richer workbench and records scenes;
3. parity gaps become explicit;
4. replacement surfaces become good enough to displace reference surfaces one at a time;
5. the extension shrinks to a parity-audit and fallback instrument.

The extension must never be the only source of market truth. Reference pages virtualize
lists, alter DOM structure, run experiments, and may never put the full denominator in the
document. The market census remains a collector responsibility.

## 3. Product-shell requirements

The shell choice must support the product contract in
`docs/research/lanes/08_product_glass.md`:

- continuously updating, stable virtualized discovery feeds;
- one or more hot charts with real-time market, fill, gesture, and social overlays;
- synchronized social threads and media;
- a persistent episode/exposure rail and one-step target-specific exit gesture;
- exact viewport, disclosure, choice-set, chart-range, and gesture capture;
- deterministic replay and outcome-hidden interviews;
- keyboard, pointer, touch, and accessible semantic alternatives;
- clear missing, stale, conflicting, attested, derived, and inferred states;
- local service connectivity without putting durable collectors or evidence in the UI
  process;
- future mobile or authenticated remote observation;
- crash recovery that cannot lose the authoritative event stream.

The UI does **not** require a native toolkit merely because it is latency-sensitive. Canvas
financial charts support streaming updates and custom drawing primitives in browsers, while
virtualization libraries render only the visible portion of long feeds. Current Lightweight
Charts supports real-time `series.update`, panes, plugins, and drawing primitives; TanStack
Virtual exposes stable item keys, measurement snapshots, and scroll restoration.
[Lightweight Charts real-time updates](https://tradingview.github.io/lightweight-charts/tutorials/demos/realtime-updates),
[Lightweight Charts plugins](https://tradingview.github.io/lightweight-charts/docs/5.1/plugins/intro),
[TanStack Virtual](https://tanstack.com/virtual/latest/docs/api/virtualizer)

Whether those particular libraries meet our workload is a spike result, not an assumption.

## 4. Ground truth on the target machine

Current machine facts supplied for this lane:

- Apple arm64 macOS;
- 96 GiB memory;
- .NET 10, Node 26, Rust nightly, and OCaml/opam installed;
- `joshibot` already includes React 19, Vite 8, Lightweight Charts 5.2, Radix, Tailwind,
  and a nontrivial TS/TSX prototype.

This removes setup cost as a discriminator among browser, Tauri, Electron, and Avalonia.
Memory also makes Electron's footprint less personally harmful than it would be on a small
machine, but shipping a Chromium runtime still creates update and security obligations.
The installed Rust is nightly; Tauri should build against its documented supported stable
toolchain in a real project rather than relying on “Rust exists.”

The project is personal and currently macOS-first. Cross-platform capability is an option
value, not permission to weaken the Mac experience.

## 5. Candidate comparison

Ratings are specific to this project and the first research cockpit.

| Approach | Strongest fit | Principal weakness | Reversibility | Initial verdict |
|---|---|---|---|---|
| Browser app / optional PWA | replacement shell, replay, remote/mobile | no access to another tab; focused shortcuts only; browser lifecycle | highest | **start here** |
| WebExtension + side panel | companion in real Pump session | brittle reference DOM; permissions; ephemeral worker | high if thin | **companion adapter** |
| Tauri 2 | later packaged desktop shell with web UI and scoped native powers | system WKWebView variability; Rust/native boundary; embedded session separate | high if frontend remains pure | **first wrapper candidate** |
| Electron | deterministic Chromium, page capture, mature browser/process controls | large runtime and patch surface; no mobile; dangerous remote-content boundary | medium-high | **fallback if Tauri/browser falsified** |
| Avalonia/.NET | native cross-platform desktop/mobile; C# domain | duplicates web UI work or embeds a WebView anyway; weaker continuity with chart/feed prototype | medium-low | **do not start** |
| SwiftUI/AppKit | best macOS integration and ScreenCaptureKit | macOS-only shell; bespoke market chart/drawing work; least renderer reuse | low | **native helper only if earned** |

## 6. Browser application / PWA

### 6.1 Strengths

A browser renderer is the shortest path to the actual product questions:

- canvas/WebGL chart and overlay ecosystems;
- WebSocket, workers, typed arrays, IndexedDB, responsive layouts, touch, keyboard, and
  browser developer profiling;
- virtualized semantic feed rows;
- normal component and screenshot testing;
- one codebase for desktop, mobile browser, and authenticated remote observation;
- easiest outcome-hidden replay because historic state can render through the same
  components as live state.

Safari supports Mac web apps added to the Dock, including manifests, service workers, push,
and badging. This makes an installed web-app presentation available without committing to a
native wrapper. It does not grant general native powers.
[WebKit: web apps on Mac](https://webkit.org/blog/14445/webkit-features-in-safari-17-0/)

The shell should be served by the local core on one loopback origin during the personal
phase. Loopback origins are “potentially trustworthy” under the Secure Contexts standard.
[W3C Secure Contexts](https://www.w3.org/TR/secure-contexts/)

Serving the renderer and API on the same local origin also avoids making a public HTTPS page
reach back into localhost. Chrome introduced a Local Network Access prompt for public pages
connecting to local or loopback services in Chrome 142. That is another reason not to make a
cloud-hosted UI plus localhost API the default.
[Chrome Local Network Access](https://developer.chrome.com/blog/local-network-access)

### 6.2 Limits

- It cannot observe Pump's DOM, cookies, selected mint, or scroll state across origins.
- Standard web keyboard events work only while the app is focused, and browser/OS shortcuts
  reserve combinations.
- The browser may throttle or suspend background tabs, timers, and workers. Stream truth
  must live in the core, and reconnect by cursor; the UI cannot be a collector.
- A PWA does not become a process supervisor or trusted signer.
- Browser display capture is deliberately interactive: the Screen Capture standard requires
  transient activation, user choice every time, and forbids persisting a `granted`
  permission. It is unsuitable for silent continuous capture of a different app.
  [W3C Screen Capture](https://www.w3.org/TR/screen-capture/)
- Installed web-app behavior and browser engine capabilities differ. Chrome, Safari, and
  Safari's Mac web-app container require separate tests.

### 6.3 Suitability

Excellent for replacement, replay, interviews, and responsive remote/mobile views. It is
insufficient by itself for companion-mode observation.

“PWA” should remain a packaging affordance, not an architectural layer. The browser URL
must continue to work even if Add to Dock proves awkward.

## 7. WebExtension companion

### 7.1 Strengths

A WebExtension runs where Ember's reference session already exists. With narrowly scoped
Pump host permission it can:

- observe rendered cards and the actual viewport;
- detect SPA navigation and selected coin;
- capture DOM-visible social and chart context;
- add a side panel or small page-local affordance;
- send structured observations to the local core;
- avoid a second Pump login or an embedded wallet environment.

Chrome documents that side panels can persist beside navigation and be scoped to particular
sites. Content scripts run in an isolated world but can inspect the shared DOM.
[Chrome side-panel API](https://developer.chrome.com/docs/extensions/reference/api/sidePanel),
[Chrome content-script isolation](https://developer.chrome.com/docs/extensions/develop/concepts/content-scripts)

Safari Web Extensions use HTML, CSS, JavaScript, and common WebExtension formats, can read
and modify pages after user permission, and can communicate with a containing native app.
Apple provides conversion/packaging paths for existing extensions.
[Apple Safari Web Extensions](https://developer.apple.com/documentation/safariservices/safari-web-extensions),
[Safari extension overview](https://developer.apple.com/safari/extensions/)

### 7.2 Limits

- Persistent whole-site capture requires an understandable host permission. `activeTab` is
  narrower but ends when the operator changes context.
- Pump DOM and internal routes are an unstable, unversioned interface. Mutation observers
  can measure what was rendered, not guarantee the complete board universe.
- A canvas chart is pixels, not a semantic DOM time series. The extension may preserve its
  visible bounds or a screenshot, but exact prices, trades, and quotes must come from our
  own tape or an explicitly validated public interface; scraping private page state would
  be a separate, brittle capability.
- Main-world injection to reach private page variables increases coupling and attack
  surface; the default should remain isolated-world DOM observation.
- Manifest V3 service workers are ephemeral and may terminate timers; Chrome explicitly
  tells extensions to persist state rather than rely on globals.
  [Chrome extension service-worker migration](https://developer.chrome.com/docs/extensions/develop/migrate/to-service-workers)
- Extension-to-local-service communication needs a tested boundary. Extension pages can
  make cross-origin requests with declared host permissions; Chrome also supports native
  messaging to a separately registered local process.
  [Chrome extension network requests](https://developer.chrome.com/docs/extensions/develop/concepts/network-requests),
  [Chrome native messaging](https://developer.chrome.com/docs/apps/nativeMessaging)
- Chrome and Safari APIs overlap but are not identical; Safari distribution adds Apple
  packaging and permission UX.
- Page modification could accidentally change Ember's visual sensorium. Companion capture
  should initially be observational, with our controls in a side panel rather than injected
  into the trade card.

### 7.3 Suitability

Best companion adapter, poor standalone architecture. Build it only after an actual browser
choice and a parity observation protocol are known.

## 8. Tauri 2

### 8.1 Strengths

Tauri can wrap the same static TypeScript renderer and expose explicitly scoped native
commands. On macOS it uses the system WKWebView rather than bundling Chromium; its capability
model grants commands per window/webview, and dangerous plugin actions are disabled until
allowed. Tauri also has official global-shortcut and sidecar mechanisms.
[Tauri webview versions](https://v2.tauri.app/reference/webview-versions/),
[Tauri capabilities](https://v2.tauri.app/security/capabilities/),
[Tauri global shortcut](https://v2.tauri.app/plugin/global-shortcut/),
[Tauri sidecars](https://v2.tauri.app/develop/sidecar/)

Potential earned benefits:

- app window, Dock identity, always-on-top/focus control, tray or launch-at-login;
- OS-global shortcuts if the product later justifies them;
- bundled local frontend independent of a browser tab;
- narrow native screenshot/window APIs through a reviewed command;
- notification and filesystem integration;
- a path to iOS/Android using the same web renderer, though plugin support and UX remain
  separate work.

Tauri can package a macOS app or DMG. Direct distribution requires Apple code signing and
notarization.
[Tauri distribution](https://v2.tauri.app/distribute/)

### 8.2 Limits and unknowns

- Tauri does not bundle its webview. On macOS it inherits the installed WKWebView/WebKit
  version, updated with the OS. That reduces package size but makes browser-feature and
  performance behavior depend on the target OS.
- Lightweight Charts, large virtualized feeds, workers, storage, clipboard, VoiceOver, and
  high-frequency streaming must all be tested in WKWebView. “Works in Safari” is helpful,
  not proof of identical embedded behavior.
- macOS automation used to be a Tauri weakness; current Tauri documentation recommends a
  WebdriverIO embedded driver for macOS, so wrapper E2E is now plausible, but it adds
  wrapper-specific test machinery.
  [Tauri WebDriver testing](https://v2.tauri.app/develop/tests/webdriver/)
- Tauri can load a remote URL, but granting remote content any native capability expands a
  severe trust boundary. Official guidance recommends restrictive CSP and avoiding remote
  scripts.
  [Tauri CSP](https://v2.tauri.app/security/csp/)
- A WKWebView has its own persistent website data store. Persistence does **not** establish
  that it shares Safari or Chrome's active Pump cookies, wallet extensions, passkeys, or
  anti-bot state. Apple exposes cookie stores per `WKWebsiteDataStore`; cross-application
  session sharing must be treated as unproven.
  [Apple WKWebsiteDataStore](https://developer.apple.com/documentation/webkit/wkwebsitedatastore)
- Bundling collectors as sidecars is possible but should not make the GUI their lifecycle
  owner. A shell crash must not stop evidence capture.

### 8.3 Suitability

Best first native wrapper if native needs emerge. Not needed for the first renderer and not
a reliable path to the operator's existing Pump browser session.

## 9. Electron

### 9.1 Strengths

Electron bundles Chromium and Node, giving one known rendering engine across supported
desktop platforms. Its Chromium-derived multi-process model separates main and renderer
processes; utility processes can isolate additional work. `webContents.capturePage` captures
a visible page, and persistent session partitions explicitly manage cookies/cache for pages
inside the app.
[Electron process model](https://www.electronjs.org/docs/latest/tutorial/process-model),
[Electron page capture](https://www.electronjs.org/docs/latest/api/web-contents/),
[Electron sessions](https://www.electronjs.org/docs/latest/api/session)

It offers:

- predictable Chromium chart/Canvas behavior;
- strong DevTools and performance profiling;
- multiple isolated renderer/web-content views;
- mature page capture;
- global shortcuts, menus, tray, auto-update, and native Node integration;
- direct reuse of the TypeScript renderer.

If exact Chromium parity and remote-page embedding become non-negotiable, Electron is the
stronger desktop browser container.

### 9.2 Limits

- Shipping Chromium and Node creates a materially larger artifact and a recurring security
  update obligation.
- Electron's own security guide warns that loading untrusted remote content is dangerous,
  requires sandboxing and context isolation, and must never expose Node APIs. A Pump
  `WebContentsView` would need no native bridge and a separate capability boundary.
  [Electron security checklist](https://www.electronjs.org/docs/latest/tutorial/security)
- Electron persistent sessions are Electron sessions, not Chrome's current profile.
  Re-authentication is expected.
- Electron explicitly supports only a subset of Chrome Extension APIs and says arbitrary
  Chrome Web Store extensions are not supported. An embedded Pump page therefore must not
  assume Phantom or another wallet extension will work as it does in Chrome.
  [Electron Chrome Extension Support](https://www.electronjs.org/docs/latest/api/extensions-api)
- Electron has no credible mobile target.
- macOS distribution still needs packaging, signing, and notarization.
  [Electron code signing](https://www.electronjs.org/docs/latest/tutorial/code-signing)

### 9.3 Suitability

A defensible fallback if the browser/Tauri renderer fails or embedded Chromium is proven
necessary. The machine can afford it; the project should not accept its security and update
surface without a measured benefit.

## 10. Avalonia/.NET

### 10.1 Strengths

Avalonia is a serious native cross-platform option. Current official support includes
Windows, macOS, Linux, iOS, Android, and WebAssembly, with support tiers varying by platform.
The target machine already has .NET 10.
[Avalonia supported platforms](https://docs.avaloniaui.net/docs/supported-platforms)

It could provide:

- a C#/XAML UI with native window, menu, input, and process integration;
- Skia-rendered custom controls;
- shared .NET domain/client code;
- mobile and desktop targets from one ecosystem.

Avalonia also has a `NativeWebView` backed by WKWebView on macOS/iOS and WebView2 on Windows.
[Avalonia NativeWebView](https://docs.avaloniaui.net/controls/web/nativewebview)

### 10.2 Limits

For this product, either path forfeits much of the advantage:

- A fully native feed/chart requires selecting or writing a high-frequency financial chart,
  drawing tools, virtualized social UI, browser-like rich text/media, and replay renderer in
  C#/Skia.
- Embedding the TypeScript chart in `NativeWebView` recovers the web ecosystem but adds a
  C#/JavaScript bridge and gives essentially the same macOS WKWebView engine as Tauri.
- The existing prototype, chart integration, and likely browser-extension companion are
  TypeScript. A separate XAML renderer doubles semantic and visual replay work.
- WebAssembly/mobile checkboxes do not prove equivalent accessibility, latency, packaging,
  or plugin behavior.

### 10.3 Suitability

Technically credible, strategically unmotivated unless a future .NET service/domain layer
becomes dominant or a native accessibility/performance spike proves a web renderer
inadequate. Do not include it in the first UI spike.

## 11. Native SwiftUI/AppKit

Native Apple UI offers the best integration with macOS focus, menus, windowing, VoiceOver,
and ScreenCaptureKit. Apple describes ScreenCaptureKit as a high-performance, fine-grained
capture API with a system source picker, and Swift Charts includes built-in localization
and accessibility support.
[Apple ScreenCaptureKit](https://developer.apple.com/documentation/screencapturekit),
[Apple Swift Charts](https://developer.apple.com/documentation/Charts)

It is nevertheless a poor first whole shell:

- Swift Charts is not evidence that the required sub-second trading chart, custom overlay,
  drawing, and huge event history are available without substantial custom work.
- Pump-parity feeds, rich social threads, responsive remote/mobile browser views, and the
  WebExtension companion remain web-shaped.
- A native renderer creates a second representation for deterministic replay.
- It is Apple-only.

A narrow native helper could later earn a role for operator-approved window screenshots,
global system integration, or a Safari containing app. Apple explicitly supports Safari Web
Extensions communicating with a native app. That is not a reason to write the cockpit in
SwiftUI.
[Apple Safari extension/native app integration](https://developer.apple.com/safari/extensions/)

## 12. Cross-cutting UI choices

### 12.1 Renderer

Recommendation: React + TypeScript + Vite for the spike and first shell.

This is project-specific, not a declaration that React is universally fastest:

- the compost already speaks these technologies;
- chart and virtualization libraries have direct TS/React integrations;
- semantic HTML, responsive CSS, WebExtension pages, browser app, Tauri, and Electron can
  share components;
- browser DevTools and automated DOM/screenshot inspection shorten human- and AI-assisted
  iteration;
- the product's hard problems are event semantics, stable identity, replay, and interaction
  latency, not server-side rendering.

Keep business state and scene capture outside component-local state. The shell should
consume a versioned projection and emit semantic gestures. Do not port old components until
the spike proves they satisfy the new contracts.

### 12.2 Chart

Use Lightweight Charts 5.2 as the baseline spike because it already exists locally and
supports real-time updates and custom primitives. It is not yet selected for production.

The spike must test:

- raw trade/event points and legitimate OHLC aggregation;
- multiple panes and overlays;
- exact fill, quote, gesture, social, LP-bin, and migration markers;
- free pointing/drawing stored in data coordinates;
- zoom/scroll at full episode history;
- rapid update conflation without losing raw source events;
- resize and high-DPI behavior in Chrome, Safari, and WKWebView.

Canvas itself is not accessible. Lightweight Charts states that accessibility attributes
and behavior are not built in. The product must provide keyboard control, focus semantics,
a synchronized textual data view, descriptive state, and non-color status cues.
[Lightweight Charts accessibility](https://tradingview.github.io/lightweight-charts/tutorials/a11y/intro)

### 12.3 Feeds and social streams

Use windowed virtualization with stable candidate/event IDs. Never tie the authoritative
choice set to DOM children; virtualization intentionally removes off-screen DOM. Record the
server-provided full list epoch separately, and record intersection/viewport events for what
was actually visible.

Parsing, aggregation, image decoding policy, and historical backfill should not block the UI
thread. Candidate calculations can move to Web Workers, but the local core remains the
authoritative stream and replay source.

### 12.4 Stream and crash containment

The shell is disposable:

- every stream item has a sequence/cursor;
- renderer reconnect requests the missing interval;
- gestures are acknowledged only after the local core durably records them;
- render reload, browser tab suspension, Tauri renderer crash, or Electron renderer crash
  cannot lose the market/social tape;
- collectors, wallet observation, and later execution are independent processes;
- the shell reports its own lag and missing range.

This design makes browser background throttling an inconvenience rather than corrupted
evidence.

### 12.5 Viewport and screenshot capture

Primary evidence is structured:

- list epoch and candidate order;
- exact rendered projection versions;
- viewport bounds and intersection;
- chart logical time/price ranges and enabled overlays;
- disclosure/focus state;
- gesture geometry;
- client and stylesheet/build version.

For the cockpit's own window, structured state plus deterministic replay is more useful than
continuous pixels. A screenshot at decisive gestures can be a checksum.

Runtime capture choices:

- browser: own DOM/canvas snapshot tooling is possible, but capturing another app requires
  user-mediated `getDisplayMedia` every session;
- extension: can capture DOM-visible Pump semantics and, with additional browser permission,
  may capture the tab; semantic capture remains less privacy-invasive;
- Tauri/WKWebView: Apple WKWebView offers an asynchronous page snapshot API, but exposing it
  through Tauri requires wrapper/native work;
  [Apple WKWebView snapshot](https://developer.apple.com/documentation/webkit/wkwebview)
- Electron: `webContents.capturePage` is first class;
- native helper: ScreenCaptureKit is the strongest route for approved window-level capture.

No shell should record arbitrary screens by default. The product lane's privacy boundary
still applies.

### 12.6 Keyboard and gesture latency

Focused browser shortcuts are sufficient for the first slice. The hot path needs stable
targets, immediate visual feedback, and durable local receipts more than OS-global keys.

If an OS-global emergency/focus shortcut becomes a measured requirement, Tauri and Electron
can provide it. Global hooks must emit the same semantic command as pointer/touch controls;
they must not bypass target identity, staleness display, or authorization.

Touch and pointer behavior must be tested on real hardware. Desktop hover is never the only
way to reach provenance or an action.

### 12.7 Accessibility

A web shell has the best chance of one semantic model across browser, wrapper, extension,
and mobile, but only if we build it:

- real buttons, lists, headings, status regions, and focus order;
- a non-canvas textual chart/event representation;
- keyboard-operable chart range and marker navigation;
- reduced-motion, contrast, zoom, and large-text behavior;
- no hover-only evidence;
- VoiceOver testing in Safari and Chrome, then again in Tauri WKWebView or Electron;
- announcements rate-limited so a high-frequency feed does not overwhelm assistive tech.

Native does not automatically solve a custom Canvas/Skia chart's semantics.

### 12.8 AI-assisted iteration

The web renderer is unusually inspectable:

- the live DOM and accessibility tree expose state;
- browser performance traces identify long tasks and layout churn;
- screenshots and deterministic fixtures make visual regressions reviewable;
- TypeScript contracts connect served projections to rendered states;
- the old React UI offers examples and scars without forcing an architecture.

Tauri preserves most of this for the renderer but adds Rust IPC and wrapper packaging.
Electron preserves Chromium tooling but adds main/preload/security review. Avalonia/native
would require parallel XAML/Swift-specific iteration and less reuse of the browser companion.
AI convenience is a multiplier after testability and evidence semantics, not a reason to
accept an unsafe shell.

## 13. Embedded Pump is not the shortcut it appears to be

A Tauri or Electron window can load remote web content, but “the page renders” does not mean
“the operator's Pump environment moved into our app.”

Open questions include:

- separate cookies and login;
- OAuth/passkey popup behavior;
- wallet extension availability;
- anti-bot and embedded-webview detection;
- clipboard, notifications, downloads, new windows, media, and deep links;
- Pump CSP/frame policy and terms;
- whether remote navigation can be isolated from local native capabilities;
- whether the embedded surface remains functionally identical after Pump releases.

Electron gives better controls and a bundled Chromium, but it explicitly does not support
arbitrary Chrome Web Store extensions. Tauri's WKWebView has a separate website data store.
Neither is evidence that the existing wallet/session will work.

Therefore:

- companion mode uses the real browser plus WebExtension;
- replacement mode uses our own renderer and data;
- embedded Pump is an optional, isolated research spike, never the initial architecture;
- no remote Pump webview receives local process, filesystem, signer, or execution capability.

## 14. Recommended reversible first shell

### 14.1 Components

1. **Local shell server** — serves static renderer assets and the authenticated read/query
   API from the same loopback origin.
2. **React/TypeScript renderer** — capability-neutral; no direct Tauri, Electron, extension,
   key, or filesystem calls.
3. **Shell adapter interface** — reports optional abilities such as global shortcut, window
   focus, screenshot, notification, or native messaging. Absence is normal.
4. **Thin Chromium WebExtension spike** — observes the real Pump tab and writes structured
   companion events to the local core. A Safari port is evaluated only after confirming
   Ember's browser needs.
5. **No desktop wrapper initially.**
6. **Tauri wrapper experiment** — wraps the same built assets after the renderer spike, not
   before it.
7. **Electron comparison wrapper** — used only in the falsifying spike, not adopted by
   default.

### 14.2 Security boundary

- Browser, extension, and wrapper are untrusted presentation clients.
- Durable evidence and collectors survive shell exit.
- No secrets live in frontend storage.
- The extension gets only Pump and explicit loopback/native-messaging permission.
- Remote pages never share a webview capability set with local privileged UI.
- The research phase remains read-only and submits no transactions.

### 14.3 Remote and mobile path

The same renderer can later expose a responsive, authenticated, initially read-only remote
view over HTTPS. That is a separate deployment/security decision; do not expose the loopback
service directly.

A Tauri mobile checkbox is not the mobile plan. First prove the responsive browser
workbench, touch target stability, action-tray semantics, and background/reconnect behavior.
A native/mobile wrapper can follow only if push, biometric, or offline capabilities require
it.

## 15. Falsifying UI spike

The spike exists to make the recommendation fail quickly if it is wrong. It is not the
first production milestone.

### 15.1 One renderer, four hosts

Build one deliberately ugly but semantically complete screen in React/Vite and run it in:

1. current Chrome;
2. current Safari and a Safari Add-to-Dock web app;
3. a minimal Tauri 2 WKWebView wrapper;
4. a minimal Electron wrapper.

Add a separate Chromium Manifest V3 companion prototype on the current Pump site. Do not
build Avalonia or SwiftUI versions unless the web variants fail for a reason those toolkits
directly address.

### 15.2 Workload

The screen must include:

- a virtualized market board with stable keyed cards, live rank changes, freeze/pending
  reorder, selection, and exact scroll restoration;
- a selected-coin chart using the existing Lightweight Charts version with price/trade
  history, several overlay classes, drawing/pointing, zoom, and live bursts;
- a virtualized social thread with text and representative media;
- an episode rail with exposed, watching-flat, unresolved, partial, runner, zap, and re-entry
  states;
- focused keyboard and pointer/touch gestures;
- structured scene capture and deterministic replay;
- a local durable gesture receipt and reconnect-by-cursor stream.

Load comes from a recorded or realistically synthesized trace parameterized from observed
market rates. Test sustained observed p99 plus a 5–10× burst, not an invented “average”
request rate. Preserve raw events even if rendering is conflated.

### 15.3 Measurements

Measure, do not eyeball:

- stream-receipt-to-visible-update p50/p95/p99;
- input-event-to-pressed-feedback and input-to-durable-receipt;
- main-thread long tasks and animation-frame misses during scroll, zoom, burst, and media
  decode;
- memory at load, after one hour, and after repeated coin switching;
- missed/duplicated sequence IDs across reload, renderer crash, network break, sleep/wake,
  background tab, and wrapper restart;
- selected-card identity while ranks update under pointer/touch;
- exact list scroll, chart range, overlay, focus, and disclosure replay;
- screenshot difference for stable replay regions;
- keyboard conflicts and chart drawing precision;
- VoiceOver traversal and availability of equivalent textual chart/event information;
- Chrome/Safari/Tauri behavioral differences;
- extension CPU/memory impact, SPA-route detection, viewport-card coverage, DOM-change
  recovery, and whether login/wallet behavior remains untouched.

Provisional interaction gates on the target machine:

- pressed feedback by the next two display frames at p95;
- local durable gesture receipt within 50 ms p95 when the core is healthy;
- zero mis-targeted gestures during adversarial rank updates;
- zero unrecoverable event gaps or duplicate gesture records;
- no main-thread task over 100 ms on the hot path at the burst workload;
- semantic replay state byte-identical after excluding explicitly nondeterministic clocks,
  with visual differences reviewed rather than silently thresholded;
- full keyboard reachability and a usable VoiceOver path for every capital/episode gesture.

These are UI integrity gates, not claims about market latency. Revise them only from measured
human/product constraints, not because a framework misses them.

### 15.4 Companion tests

In the real Pump tab, verify:

- the extension sees the card Ember actually clicks;
- exact viewport order and scroll survive virtualized DOM recycling;
- SPA navigation and new feed variants do not silently stop capture;
- isolated-world observation is sufficient;
- page updates do not move a target because of our injection;
- the local bridge survives Manifest V3 worker termination;
- host permissions are narrow and comprehensible;
- no cookies, wallet secrets, or unrelated browsing data are collected;
- the side panel remains fast enough not to distort Pump use.

The extension spike should record its own extraction coverage and unknown fields. It may
fail even while the replacement shell succeeds.

## 16. Explicit falsifiers and resulting decisions

| Observation | Decision |
|---|---|
| Chrome/Safari browser meets workload and interaction gates | ship browser shell first; defer wrapper |
| Focus/window/global shortcut friction materially changes use, while Tauri meets all gates | add Tauri wrapper |
| WKWebView fails chart, worker, storage, a11y, or burst tests and Electron passes | choose Electron wrapper |
| Both wrappers fail but browser passes | remain browser/PWA; native shell is not helping |
| All web renderers fail at the same measured hotspot | isolate/rewrite that chart/feed hotspot before changing the whole shell |
| Exact runtime page screenshots become essential and Electron capture passes while structured/browser capture does not | reconsider Electron or narrow native capture helper |
| WebExtension cannot robustly observe Pump DOM/viewport | use it only for manual parity sessions; rely on collectors and operator gestures |
| Embedded Pump requires unavailable wallet extensions or session sharing | reject embedded mode; retain real-browser companion |
| Responsive browser works on mobile | defer mobile wrapper |
| VoiceOver cannot use the web chart despite semantic companion view | evaluate a native chart/accessibility component, not automatically a native whole app |
| Local browser lifecycle loses evidence | fix core cursor/durability boundary; a wrapper is not a substitute |
| React update scheduling causes hot-path jank after worker/virtualization discipline | spike a narrower renderer/library change with the same contracts |

## 17. Unknowns to resolve before commitment

- Which browser Ember actually uses for Pump, and whether the companion must support more
  than one immediately.
- Whether Pump's current DOM has stable semantic identifiers or accessible labels sufficient
  for isolated-world extraction.
- Whether the reference site permits/technically tolerates extension observation and whether
  its terms constrain automation.
- Real sustained and burst rates for board changes, trades, social events, images, and hot
  coins.
- Required number of simultaneously live charts and hot mints.
- Whether “capture the viewport” requires exact pixels or whether structured reconstruction
  plus decisive screenshots is sufficient.
- Whether any OS-global shortcut is actually needed; focused hotkeys may be safer.
- Whether Safari Add-to-Dock works cleanly for a loopback-served personal app on the target
  macOS version.
- Tauri WKWebView behavior with the chosen chart, Web Workers, IndexedDB, clipboard,
  WebSocket reconnect, and VoiceOver on the actual machine.
- Whether a wrapper should discover an already-running core or start a supervisor. It should
  not own collector durability either way.
- Remote/mobile threat model, especially whether any capital action is ever exposed away
  from loopback.
- Code-signing and update expectations for a one-person tool versus later distribution.

## 18. Recommendation

Begin with the browser because it is the common, inspectable renderer substrate, not because
native concerns are unimportant. Pair it with a thin extension when the actual Pump session
must be observed. Keep native powers behind an optional shell adapter and the evidence core
outside every GUI process.

The decision sequence should be:

    browser renderer proves product loop
       -> extension proves companion capture
       -> Tauri proves or fails earned desktop capabilities
       -> Electron considered only against a concrete WKWebView/browser failure
       -> native/Avalonia reconsidered only for a measured unsolved requirement

This preserves the one asset that matters most at this stage: the ability to change our mind
about packaging without changing the meaning of an episode, a gesture, a viewport, or a
replay.
