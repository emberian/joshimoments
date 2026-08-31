"use strict";
/* The portal sign-in ceremony.
 *
 * Loaded by dregg_portal.render.page_signin, AFTER the wallet crypto that
 * dregg_portal.signerjs lifts verbatim out of dregg_gate/signer/index.html — this file
 * uses b58encode/b58decode/dlSharedSecret/dlEncryptPayload/dlDecryptPayload/nacl from
 * there and defines none of them, so there is exactly one copy of that code in the tree.
 *
 * It is a FILE and not a Python string on purpose: three hundred lines of JavaScript
 * inside an f-string means every brace is doubled, every quote is a hazard, and no editor
 * or linter can see it as JavaScript. The three deployment-dependent values arrive as
 * __PLACEHOLDER__ tokens, substituted at render time; a page still carrying one is a
 * refusal, the same way edge/ refuses a config with a placeholder left in it.
 *
 * WHAT THIS SENDS, AND WHERE. Two POSTs to this origin: /api/nonce (a wallet address) and
 * /api/session (a wallet, a nonce, a signature). Nothing else leaves, and no transaction
 * is ever built, requested, or accepted — signMessage only.
 */
var PAGE_URL = "__PORTAL_PAGE_URL__";
var APP_URL  = "__PORTAL_APP_URL__";
var BASE     = "__PORTAL_BASE__";
var PHANTOM_UL  = "https://phantom.app/ul/v1/";
var SOLFLARE_UL = "https://solflare.com/ul/v1/";
var STORE_KEY = "dregg-portal-signin-v1";
var DL_TTL_MS = 30 * 60 * 1000;

function $(id){ return document.getElementById(id); }
function setStatus(el, text, cls){ el.textContent = text || ""; el.className = "status" + (cls ? " " + cls : ""); }
function walletLabel(n){ return n === "solflare" ? "Solflare" : "Phantom"; }
function shortKey(t){ return t && t.length > 14 ? t.slice(0,6) + "\\u2026" + t.slice(-6) : t; }

var challenge = null;     /* { nonce, message, wallet } */
var connected = null;

function ulBase(p){ return p === "solflare" ? SOLFLARE_UL : PHANTOM_UL; }
function dlSave(s){ try { localStorage.setItem(STORE_KEY, JSON.stringify(s)); return true; } catch (_e) { return false; } }
function dlLoad(){
  try {
    var raw = localStorage.getItem(STORE_KEY);
    if (!raw) return null;
    var s = JSON.parse(raw);
    if (!s || s.v !== 1 || typeof s.sk !== "string") return null;
    if (!s.t || (Date.now() - s.t) > DL_TTL_MS) { dlClear(); return null; }
    return s;
  } catch (_e) { return null; }
}
function dlClear(){ try { localStorage.removeItem(STORE_KEY); } catch (_e) { /* nothing to clear */ } }
function scrubUrl(){ try { history.replaceState(null, "", location.pathname); } catch (_e) { /* cosmetic */ } }

function post(path, body){
  return fetch(BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(body)
  }).then(function(r){
    return r.json().catch(function(){ return { error: "the server answered something that was not JSON" }; })
      .then(function(j){ return { ok: r.ok, body: j }; });
  });
}

function walletValue(){ return ($("wallet").value || "").trim(); }

function requestNonce(){
  var w = walletValue();
  if (!w) { setStatus($("noncestatus"), "Put your address in the box above first.", "warn"); return Promise.resolve(false); }
  setStatus($("noncestatus"), "Asking for a fresh line\\u2026");
  return post("/api/nonce", { wallet: w }).then(function(res){
    if (!res.ok || !res.body || !res.body.message) {
      setStatus($("noncestatus"), (res.body && res.body.error) || "Could not get a sign-in line.", "err");
      return false;
    }
    challenge = { nonce: res.body.nonce, message: res.body.message, wallet: w };
    $("challenge").textContent = res.body.message;
    $("challenge").style.display = "block";
    setStatus($("noncestatus"), "This is the exact text your wallet will show you. Nothing else is signed.", "ok");
    updateSignButton();
    return true;
  });
}

function submitSignature(sigB58, wallet){
  setStatus($("signstatus"), "Checking the signature\\u2026");
  return post("/api/session", { wallet: wallet, nonce: challenge.nonce, signature: sigB58 })
    .then(function(res){
      if (res.ok && res.body && res.body.entitled) { location.href = BASE + "/"; return; }
      if (res.ok && res.body) { location.href = BASE + "/me"; return; }
      setStatus($("signstatus"), (res.body && res.body.error) || "The signature was not accepted.", "err");
      challenge = null;
      $("challenge").style.display = "none";
      updateSignButton();
    });
}

/* ---- in-browser wallets (wallet-standard first, window.* probes fill gaps) ---- */
var wsWallets = [];
function wsAdapter(wallet){
  var conn = wallet.features["standard:connect"];
  var sgn = wallet.features["solana:signMessage"];
  var adapter = {
    connect: function(){
      return Promise.resolve(conn.connect()).then(function(res){
        var accounts = (res && res.accounts) || wallet.accounts || [];
        if (!accounts.length) throw new Error("The wallet connected but reported no accounts.");
        adapter._account = accounts[0];
        return { publicKey: accounts[0].address };
      });
    },
    signMessage: function(bytes){
      return Promise.resolve(sgn.signMessage({ account: adapter._account, message: bytes }))
        .then(function(out){
          var first = out && out[0];
          if (!first || !first.signature) throw new Error("The wallet returned no signature.");
          return { signature: first.signature, publicKey: adapter._account.address };
        });
    }
  };
  return adapter;
}
function wsAdd(wallet){
  try {
    if (!wallet || !wallet.features || !wallet.name) return;
    var conn = wallet.features["standard:connect"];
    var sgn = wallet.features["solana:signMessage"];
    if (!conn || typeof conn.connect !== "function") return;
    if (!sgn || typeof sgn.signMessage !== "function") return;
    for (var i = 0; i < wsWallets.length; i++) if (wsWallets[i].name === wallet.name) return;
    wsWallets.push({ name: String(wallet.name), provider: wsAdapter(wallet) });
    renderProviders();
  } catch (_e) { /* a broken wallet must not blank the page */ }
}
function wsRegisterApi(){
  return { register: function(){
    for (var i = 0; i < arguments.length; i++) wsAdd(arguments[i]);
    return function(){};
  } };
}
function wsListen(){
  try {
    window.addEventListener("wallet-standard:register-wallet", function(ev){
      try { if (ev && typeof ev.detail === "function") ev.detail(wsRegisterApi()); }
      catch (_e) { /* hostile event detail */ }
    });
    window.dispatchEvent(new CustomEvent("wallet-standard:app-ready", { detail: wsRegisterApi() }));
  } catch (_e) { /* environment without CustomEvent */ }
}
function detectProviders(){
  var found = [], seen = [];
  function add(name, p){
    if (!p || typeof p.connect !== "function" || typeof p.signMessage !== "function") return;
    if (seen.indexOf(p) !== -1) return;
    seen.push(p); found.push({ name: name, provider: p });
  }
  try {
    if (window.phantom && window.phantom.solana && window.phantom.solana.isPhantom) add("Phantom", window.phantom.solana);
    if (window.solana && window.solana.isPhantom) add("Phantom", window.solana);
    if (window.solflare && window.solflare.isSolflare) add("Solflare", window.solflare);
    if (window.backpack && window.backpack.isBackpack) add("Backpack", window.backpack);
    if (window.solana) add(window.solana.isSolflare ? "Solflare" : window.solana.isBackpack ? "Backpack" : "Wallet", window.solana);
  } catch (_e) { /* a hostile injection must not blank the page */ }
  return found;
}
function pubkeyString(pk){
  if (!pk) return null;
  try {
    if (typeof pk.toBase58 === "function") return pk.toBase58();
    var s = String(pk);
    return s && s !== "[object Object]" ? s : null;
  } catch (_e) { return null; }
}
function renderProviders(){
  var list = wsWallets.slice();
  var probed = detectProviders();
  for (var j = 0; j < probed.length; j++) {
    var dup = false;
    for (var i = 0; i < list.length; i++)
      if (list[i].name.toLowerCase() === probed[j].name.toLowerCase()) { dup = true; break; }
    if (!dup) list.push(probed[j]);
  }
  var box = $("providers");
  box.textContent = "";
  $("nowallet").style.display = list.length ? "none" : "block";
  list.forEach(function(entry){
    var btn = document.createElement("button");
    btn.type = "button"; btn.className = "btn ghost";
    btn.textContent = "Connect " + entry.name;
    btn.addEventListener("click", function(){ connect(entry); });
    box.appendChild(btn);
  });
}
function connect(entry){
  setStatus($("connstatus"), "Waiting for " + entry.name + "\\u2026");
  Promise.resolve().then(function(){ return entry.provider.connect(); }).then(function(resp){
    var pkText = pubkeyString((resp && resp.publicKey) || entry.provider.publicKey);
    if (!pkText) throw new Error("The wallet connected but reported no address.");
    connected = { name: entry.name, provider: entry.provider, pubkey: pkText };
    $("wallet").value = pkText;
    setStatus($("connstatus"), "Connected via " + entry.name + ".", "ok");
    updateSignButton();
  }).catch(function(err){
    connected = null;
    var msg = (err && (err.message || String(err))) || "";
    setStatus($("connstatus"),
      (err && err.code === 4001) || /reject|declin|denied|cancel/i.test(msg)
        ? "Connection was declined in the wallet." : ("Wallet error: " + (msg || "unknown")), "err");
    updateSignButton();
  });
}
function updateSignButton(){
  $("signbrowser").disabled = !(connected && challenge && challenge.message);
}
function toBytes(x){
  if (x instanceof Uint8Array) return x;
  if (x && x.signature) return toBytes(x.signature);
  if (x && typeof x.length === "number") return new Uint8Array(x);
  if (x && x.data && typeof x.data.length === "number") return new Uint8Array(x.data);
  return null;
}
function signInBrowser(){
  if (!connected || !challenge) return;
  setStatus($("signstatus"), "Approve the message in " + connected.name + "\\u2026");
  var bytes = new TextEncoder().encode(challenge.message);
  Promise.resolve().then(function(){ return connected.provider.signMessage(bytes, "utf8"); })
    .then(function(out){
      var sig = toBytes(out);
      if (!sig || sig.length !== 64) throw new Error("The wallet returned no usable signature.");
      return submitSignature(b58encode(sig), connected.pubkey);
    })
    .catch(function(err){
      var msg = (err && (err.message || String(err))) || "";
      setStatus($("signstatus"),
        (err && err.code === 4001) || /reject|declin|denied|cancel/i.test(msg)
          ? "You declined the signature. Nothing was sent." : ("Wallet error: " + (msg || "unknown")), "err");
    });
}

/* ---- phone: Phantom / Solflare universal-link round trip ---- */
function startDeeplink(provider){
  var run = challenge ? Promise.resolve(true) : requestNonce();
  run.then(function(ready){
    if (!ready || !challenge) return;
    var pair = nacl.box.keyPair();
    var state = {
      v: 1, provider: provider, awaiting: "connect",
      sk: b58encode(pair.secretKey), pk: b58encode(pair.publicKey),
      message: challenge.message, nonce: challenge.nonce, wallet: challenge.wallet, t: Date.now()
    };
    if (!dlSave(state) || !dlLoad()) {
      setStatus($("signstatus"), "This browser will not let the page remember the keys it needs for " +
        "the round trip. Open the portal in your regular browser and try there.", "err");
      return;
    }
    var q = new URLSearchParams();
    q.set("app_url", APP_URL);
    q.set("dapp_encryption_public_key", state.pk);
    q.set("redirect_link", PAGE_URL);
    q.set("cluster", "mainnet-beta");
    setStatus($("signstatus"), "Opening " + walletLabel(provider) + "\\u2026 approve the connection there.");
    location.href = ulBase(provider) + "connect?" + q.toString();
  });
}
function buildSignUrl(state){
  var secret = b58decode(state.sk);
  var shared = secret ? dlSharedSecret(state.peer, secret) : null;
  if (!shared) return null;
  var sealed = dlEncryptPayload(
    { message: b58encode(new TextEncoder().encode(state.message)), session: state.session, display: "utf8" },
    shared);
  if (!sealed) return null;
  var q = new URLSearchParams();
  q.set("dapp_encryption_public_key", state.pk);
  q.set("nonce", sealed.nonce);
  q.set("redirect_link", PAGE_URL);
  q.set("payload", sealed.payload);
  return ulBase(state.provider) + "signMessage?" + q.toString();
}
function continueDeeplink(){
  var state = dlLoad();
  if (!state || state.awaiting !== "sign" || !state.peer || !state.session) {
    setStatus($("signstatus"), "The connection expired \\u2014 tap a wallet button to start again.", "err");
    $("dlcontinue").style.display = "none"; dlClear(); return;
  }
  state.t = Date.now(); dlSave(state);
  var url = buildSignUrl(state);
  if (!url) { setStatus($("signstatus"), "Could not rebuild the encrypted request \\u2014 start over.", "err"); return; }
  setStatus($("signstatus"), "Opening " + walletLabel(state.provider) + "\\u2026 approve the signature there.");
  location.href = url;
}
function handleDeeplinkReturn(){
  var q;
  try { q = new URLSearchParams(location.search); } catch (_e) { return; }
  var errorCode = q.get("errorCode"), data = q.get("data"), nonce = q.get("nonce");
  var peer = q.get("phantom_encryption_public_key") || q.get("solflare_encryption_public_key");
  if (errorCode === null && (data === null || nonce === null)) return;
  scrubUrl();
  var state = dlLoad();
  if (errorCode !== null) {
    dlClear(); $("dlcontinue").style.display = "none";
    setStatus($("signstatus"), "The wallet declined or could not complete the request (" +
      (q.get("errorMessage") || ("code " + errorCode)) + "). Nothing was signed.", "err");
    return;
  }
  if (!state) {
    setStatus($("signstatus"), "Your wallet answered into a different browser than the one that " +
      "started (Telegram opens links in its own little browser; wallets come back to your main " +
      "one). No harm done \\u2014 start the sign-in again here.", "warn");
    return;
  }
  var secret = b58decode(state.sk);
  if (peer && state.awaiting === "connect") {
    var shared = secret ? dlSharedSecret(peer, secret) : null;
    var reply = shared ? dlDecryptPayload(data, nonce, shared) : null;
    if (!reply || !reply.session || !reply.public_key) {
      dlClear();
      setStatus($("signstatus"), "Could not decrypt the wallet reply \\u2014 the attempt went stale.", "err");
      return;
    }
    state.awaiting = "sign"; state.peer = peer;
    state.session = String(reply.session); state.walletKey = String(reply.public_key);
    state.t = Date.now(); dlSave(state);
    $("wallet").value = state.walletKey;
    challenge = { nonce: state.nonce, message: state.message, wallet: state.walletKey };
    $("challenge").textContent = state.message; $("challenge").style.display = "block";
    $("dlcontinue").style.display = "inline-block";
    setStatus($("signstatus"), "Connected as " + shortKey(state.walletKey) +
      ". One more hop: approve the signature.", "ok");
    return;
  }
  if (!peer && state.awaiting === "sign" && state.peer) {
    var sharedSign = secret ? dlSharedSecret(state.peer, secret) : null;
    var signReply = sharedSign ? dlDecryptPayload(data, nonce, sharedSign) : null;
    if (!signReply || !signReply.signature) {
      $("dlcontinue").style.display = "inline-block";
      setStatus($("signstatus"), "Could not decrypt the signature reply \\u2014 tap continue to ask again.", "err");
      return;
    }
    challenge = { nonce: state.nonce, message: state.message, wallet: state.walletKey };
    dlClear(); $("dlcontinue").style.display = "none";
    submitSignature(String(signReply.signature), state.walletKey);
    return;
  }
  dlClear(); $("dlcontinue").style.display = "none";
  setStatus($("signstatus"), "The wallet reply did not match where we were \\u2014 start again.", "err");
}

(function boot(){
  wsListen();
  renderProviders();
  $("getnonce").addEventListener("click", function(){ requestNonce(); });
  $("signbrowser").addEventListener("click", signInBrowser);
  $("dlphantom").addEventListener("click", function(){ startDeeplink("phantom"); });
  $("dlsolflare").addEventListener("click", function(){ startDeeplink("solflare"); });
  $("dlcontinue").addEventListener("click", continueDeeplink);
  $("dlreset").addEventListener("click", function(){
    dlClear(); challenge = null;
    $("challenge").style.display = "none"; $("dlcontinue").style.display = "none";
    setStatus($("signstatus"), "Cleared. Start again whenever you like.");
    updateSignButton();
  });
  $("wallet").addEventListener("input", function(){
    challenge = null; $("challenge").style.display = "none"; updateSignButton();
  });
  handleDeeplinkReturn();
  var resume = dlLoad();
  if (resume && resume.awaiting === "sign") $("dlcontinue").style.display = "inline-block";
})();
