-- Retire the Wave 5 C1 activation ledger.
--
-- Migration 0023 created two append-only tables and six triggers for a staged canary ceremony:
-- an inert activation document, and a one-shot claim that consumed it before a transport could
-- receive an in-process capability.  Every consumer of those tables has been deleted -- the
-- `joshi-wave5-c1-activation` crate, `joshi-store::wave5_c1`, the supervisor's disabled C1
-- admission and its C1 runtime -- and no code path in this tree can insert into, read, or
-- reference either table any more.
--
-- 0023 is left exactly as it was applied.  A migration that has run is a historical fact, and
-- rewriting one is refused by `schema/validate.sh` on its recorded source checksum; this is the
-- forward migration that undoes its effect instead.
--
-- The two `DROP TABLE` statements also drop the triggers defined on those tables, including the
-- append-only `BEFORE DELETE` guards.  That is the whole reason a forward migration can do this at
-- all: `DROP TABLE` removes a table and its triggers rather than deleting rows through them, so the
-- append-only guard is not being circumvented row by row.  The claim table is dropped first
-- because it holds the foreign key into the activation table.
--
-- What is lost: any activation or claim row a catalog happens to hold.  Nothing else in the schema
-- references either table, so no other row, digest, or commit closure changes.  A catalog that
-- never ran the ceremony -- which is every catalog in this tree, because nothing ever wrote one
-- outside a test -- loses nothing at all.

DROP TABLE IF EXISTS wave5_c1_activation_claim_v1;
DROP TABLE IF EXISTS wave5_c1_activation_v1;
