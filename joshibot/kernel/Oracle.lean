/-
The oracle binary. Reads fill queries on stdin, writes answers on stdout.

This exists so the Python side can be checked against the artifact the theorems are about,
rather than against a second implementation of the same arithmetic that happens to agree
today. It is the in-process FFI's less elegant sibling — a pipe instead of a symbol — but it
buys the property that matters: `Fill.lean` is the reference, and any drift in the Python
executor's fill math shows up as a differential-test failure rather than as a wrong number in
a backtest nobody audits.

Protocol, one query per line, all values decimal integers:

    sell <tokenRaw> <solLamports> <amount>      -> lamports paid out
    accepts <tokenRaw> <solLamports> <amount> <floor>  -> 1 or 0

Malformed input is answered with `err`, never with a guess: a parse failure that silently
returned 0 would look exactly like a pool that pays nothing.
-/

import Joshi

open Joshi

def handle (line : String) : String :=
  let parts := line.trim.splitOn " " |>.filter (· ≠ "")
  match parts with
  | ["sell", t, s, a] =>
    match t.toNat?, s.toNat?, a.toNat? with
    | some t, some s, some a => toString ((Reserves.mk t s).sellOut a)
    | _, _, _ => "err"
  | ["accepts", t, s, a, f] =>
    match t.toNat?, s.toNat?, a.toNat?, f.toNat? with
    | some t, some s, some a, some f =>
      if f ≤ (Reserves.mk t s).sellOut a then "1" else "0"
    | _, _, _, _ => "err"
  | _ => "err"

partial def loop : IO Unit := do
  let stdin ← IO.getStdin
  let line ← stdin.getLine
  if line.isEmpty then
    pure ()
  else
    IO.println (handle line)
    (← IO.getStdout).flush
    loop

def main : IO Unit := loop
