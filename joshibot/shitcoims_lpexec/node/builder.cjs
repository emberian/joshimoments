/*
 * The untrusted builder.
 *
 * This process turns a plan into unsigned transaction bytes using Meteora's own
 * @meteora-ag/dlmm SDK, and it is deliberately the LEAST trusted part of the system:
 *
 *   - it never receives, reads, derives or holds a private key;
 *   - it never sends anything (it has an RPC url for READS, and returns bytes on stdout);
 *   - everything it emits is decoded and re-checked in Python by shitcoims_lpexec/guard.py
 *     against an instruction allowlist it cannot influence.
 *
 * So the worst a bug, a supply-chain compromise or a version drift in this file can do is
 * produce bytes that get refused. That is the whole reason the SDK is allowed to be a real
 * dependency rather than a hand-rolled reimplementation: 8,000 lines of bin math, PDA
 * derivation and bin-array coverage logic are exactly the kind of thing you should not
 * rewrite, and putting them behind a validator makes trusting them unnecessary.
 *
 * CommonJS on purpose: @meteora-ag/dlmm@1.9.14 ships an ESM bundle that cannot be imported
 * on Node >= 22 (it does a directory import of @coral-xyz/anchor/dist/cjs/utils/bytes, which
 * ERR_UNSUPPORTED_DIR_IMPORT rejects). The CJS entry point works and module.exports IS the
 * DLMM class itself, not a namespace with a .default -- both facts were established by
 * probing the installed package, not by reading its README.
 *
 * PROTOCOL: one JSON request object on stdin, one JSON response object on stdout. No
 * streaming, no daemon, no port. Errors come back as {"ok": false, "error": "..."} with a
 * zero exit code so the Python side always gets structured output.
 */

"use strict";

const DLMM = require("@meteora-ag/dlmm");
const BN = require("bn.js");
const {
  Connection,
  PublicKey,
  TransactionMessage,
  VersionedTransaction,
  ComputeBudgetProgram,
} = require("@solana/web3.js");

const DLMM_PROGRAM = "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo";

function readStdin() {
  return new Promise((resolve, reject) => {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => (data += chunk));
    process.stdin.on("end", () => resolve(data));
    process.stdin.on("error", reject);
  });
}

/* Collect the instructions out of whatever shape the SDK handed back. The SDK returns a
 * legacy Transaction, or an array of them, depending on the call and on how many bins are
 * involved; normalising here keeps that variation out of Python. */
function instructionsOf(result) {
  const list = Array.isArray(result) ? result : [result];
  return list.map((tx) => tx.instructions);
}

/* Compile to a v0 message with OUR compute budget, not the SDK's.
 *
 * Any SetComputeUnitLimit / SetComputeUnitPrice the SDK added is dropped and replaced. The
 * landing policy in studies/RESULT_execution_landing.md sets those two numbers from a
 * simulation and a per-pool bid distribution; letting a library's default ride would silently
 * override a measured policy with a constant. Python decides both values and passes them in.
 */
function compile(instructions, payer, blockhash, cuLimit, cuPrice) {
  const budget = [];
  if (cuLimit) budget.push(ComputeBudgetProgram.setComputeUnitLimit({ units: cuLimit }));
  if (cuPrice) budget.push(ComputeBudgetProgram.setComputeUnitPrice({ microLamports: cuPrice }));
  const kept = instructions.filter(
    (ix) => ix.programId.toBase58() !== ComputeBudgetProgram.programId.toBase58()
  );
  const message = new TransactionMessage({
    payerKey: payer,
    recentBlockhash: blockhash,
    instructions: [...budget, ...kept],
  }).compileToV0Message();
  const tx = new VersionedTransaction(message);
  return Buffer.from(tx.serialize()).toString("base64");
}

async function loadPool(connection, poolAddress) {
  return DLMM.create(connection, new PublicKey(poolAddress), { cluster: "mainnet-beta" });
}

async function opPoolState(connection, req) {
  const pool = await loadPool(connection, req.pool);
  const active = await pool.getActiveBin();
  return {
    pool: req.pool,
    bin_step: pool.lbPair.binStep,
    active_bin_id: active.binId,
    active_price_per_lamport: active.price,
    active_price_ui: pool.fromPricePerLamport(Number(active.price)),
    token_x_mint: pool.lbPair.tokenXMint.toBase58(),
    token_y_mint: pool.lbPair.tokenYMint.toBase58(),
    token_x_decimals: pool.tokenX.mint.decimals,
    token_y_decimals: pool.tokenY.mint.decimals,
    reserve_x: pool.tokenX.amount.toString(),
    reserve_y: pool.tokenY.amount.toString(),
  };
}

async function opPositions(connection, req) {
  const pool = await loadPool(connection, req.pool);
  const { userPositions } = await pool.getPositionsByUserAndLbPair(new PublicKey(req.user));
  return {
    pool: req.pool,
    positions: userPositions.map((p) => ({
      address: p.publicKey.toBase58(),
      lower_bin_id: p.positionData.lowerBinId,
      upper_bin_id: p.positionData.upperBinId,
      total_x: p.positionData.totalXAmount.toString(),
      total_y: p.positionData.totalYAmount.toString(),
      fee_x: p.positionData.feeX.toString(),
      fee_y: p.positionData.feeY.toString(),
      /* Per-bin, so the planner can pick a bin range by inventory rather than by guessing
       * a uniform distribution across the position's range. */
      bins: p.positionData.positionBinData.map((b) => ({
        bin_id: b.binId,
        price: b.price,
        price_per_token: b.pricePerToken,
        x: b.positionXAmount,
        y: b.positionYAmount,
        liquidity: b.positionLiquidity,
      })),
    })),
  };
}

async function opRemoveLiquidity(connection, req) {
  const pool = await loadPool(connection, req.pool);
  const { userPositions } = await pool.getPositionsByUserAndLbPair(new PublicKey(req.user));
  const position = userPositions.find((p) => p.publicKey.toBase58() === req.position);
  if (!position) throw new Error(`position ${req.position} not found in pool ${req.pool}`);

  const result = await pool.removeLiquidity({
    position: position.publicKey,
    user: new PublicKey(req.user),
    fromBinId: req.from_bin_id,
    toBinId: req.to_bin_id,
    bps: new BN(req.bps),
    shouldClaimAndClose: Boolean(req.claim_and_close),
  });

  const { blockhash } = await connection.getLatestBlockhash("confirmed");
  const payer = new PublicKey(req.user);
  const groups = instructionsOf(result);
  return {
    pool: req.pool,
    position: req.position,
    transactions: groups.map((ixs) => compile(ixs, payer, blockhash, req.cu_limit, req.cu_price)),
    blockhash,
  };
}

/* The ask ladder.
 *
 * One-sided liquidity ABOVE the active bin holds only token X, so depositing X there is an
 * ask ladder: arbitrageurs buy from it as price rises and we end up holding Y. We never sign
 * a sale -- other people's flow does the converting, which is the whole point of a package
 * that cannot swap.
 *
 * `strategyType` Spot spreads uniformly across the range; that is the shape a ladder wants,
 * because Curve/BidAsk concentrate and a concentrated ask is a worse fill schedule.
 */
async function opAddOneSided(connection, req) {
  const pool = await loadPool(connection, req.pool);
  const payer = new PublicKey(req.user);
  const positionKey = new PublicKey(req.position);

  const strategy = {
    minBinId: req.min_bin_id,
    maxBinId: req.max_bin_id,
    strategyType: DLMM.StrategyType.Spot,
  };

  const result = await pool.initializePositionAndAddLiquidityByStrategy({
    positionPubKey: positionKey,
    user: payer,
    totalXAmount: new BN(req.total_x || "0"),
    totalYAmount: new BN(req.total_y || "0"),
    strategy,
    slippage: req.slippage_pct,
  });

  const { blockhash } = await connection.getLatestBlockhash("confirmed");
  const groups = instructionsOf(result);
  return {
    pool: req.pool,
    position: req.position,
    transactions: groups.map((ixs) => compile(ixs, payer, blockhash, req.cu_limit, req.cu_price)),
    blockhash,
  };
}

/* The SDK's own rent quote, used as an INDEPENDENT check on binmath.quote_rent.
 *
 * Two derivations of the same number that agree is evidence; one derivation is a hope. When
 * they disagree the dry-run says so and refuses rather than picking a winner. */
async function opQuoteRent(connection, req) {
  const pool = await loadPool(connection, req.pool);
  const quote = await pool.quoteCreatePosition({
    strategy: {
      minBinId: req.min_bin_id,
      maxBinId: req.max_bin_id,
      strategyType: DLMM.StrategyType.Spot,
    },
  });
  return {
    pool: req.pool,
    bin_arrays_to_create: quote.binArraysCount,
    bin_array_cost_sol: quote.binArrayCost,
    position_count: quote.positionCount,
    position_cost_sol: quote.positionCost,
  };
}

const OPS = {
  pool_state: opPoolState,
  positions: opPositions,
  remove_liquidity: opRemoveLiquidity,
  add_one_sided: opAddOneSided,
  quote_rent: opQuoteRent,
};

async function main() {
  let request;
  try {
    request = JSON.parse(await readStdin());
  } catch (err) {
    process.stdout.write(JSON.stringify({ ok: false, error: `bad request json: ${err.message}` }));
    return;
  }
  const handler = OPS[request.op];
  if (!handler) {
    process.stdout.write(
      JSON.stringify({ ok: false, error: `unknown op ${request.op}; known: ${Object.keys(OPS).join(", ")}` })
    );
    return;
  }
  if (!request.rpc_url) {
    process.stdout.write(JSON.stringify({ ok: false, error: "rpc_url is required" }));
    return;
  }
  try {
    const connection = new Connection(request.rpc_url, "confirmed");
    const result = await handler(connection, request);
    process.stdout.write(JSON.stringify({ ok: true, program: DLMM_PROGRAM, result }));
  } catch (err) {
    process.stdout.write(JSON.stringify({ ok: false, error: String((err && err.message) || err) }));
  }
}

main();
