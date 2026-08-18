-- Fixture-specific semantic expectations. These are deliberately stronger than row-count smoke.
.bail on
PRAGMA foreign_keys = ON;

CREATE TEMP TABLE fixture_result (
    case_name TEXT PRIMARY KEY,
    result INTEGER NOT NULL CHECK (result = 1)
) STRICT;

INSERT INTO fixture_result
SELECT 'same blob was acquired twice as two observations',
       COUNT(*) = 2
FROM observation
WHERE blob_id = '9a65e611501e08bd7a07c31649054a38c9542d3e0b2fa5f02a3eb7b6a7f4e163';

INSERT INTO fixture_result
SELECT 'redelivery retained two acquisition identities',
       COUNT(DISTINCT acquisition_id) = 2
FROM observation
WHERE blob_id = '9a65e611501e08bd7a07c31649054a38c9542d3e0b2fa5f02a3eb7b6a7f4e163';

INSERT INTO fixture_result
SELECT 'equal-valued events remain two source identities',
       COUNT(DISTINCT ase.source_event_id) = 2
FROM assertion AS a
JOIN assertion_source_event AS ase USING (assertion_id)
WHERE a.value_sha256 = 'bc60e6b05a12969bd3e13ca7a1ab7fda329647ca69bdac5707d3635b39aaebce';

INSERT INTO fixture_result
SELECT 'equal-valued events retain equal exact amounts',
       COUNT(*) = 4
FROM assertion_amount
WHERE assertion_id IN ('ast_trade_0_v1', 'ast_trade_1_v1')
  AND signed_atoms IN ('100', '25');

INSERT INTO fixture_result
SELECT 'duplicate delivery did not mint duplicate trade assertions',
       COUNT(*) = 2
FROM assertion
WHERE assertion_kind = 'protocol.trade' AND produced_commit_seq = 1;

INSERT INTO fixture_result
SELECT 'unknown variant remains raw and unsupported',
       COUNT(*) = 1
FROM observation AS o
JOIN blob AS b USING (blob_id)
WHERE o.observation_id = 'obs_unknown_variant'
  AND o.parse_disposition = 'unsupported_variant'
  AND b.storage_mode = 'external';

INSERT INTO fixture_result
SELECT 'unknown variant was not coerced into an assertion',
       COUNT(*) = 0
FROM assertion_observation_evidence
WHERE observation_id = 'obs_unknown_variant';

INSERT INTO fixture_result
SELECT 'gap is explicit and completely recovered',
       COUNT(*) = 1
FROM coverage_gap AS g
WHERE g.gap_id = 'gap_fixture_101_102'
  AND EXISTS (
      SELECT 1 FROM coverage_gap_recovery AS r
      WHERE r.gap_id = g.gap_id AND r.recovery_status = 'partial'
  )
  AND EXISTS (
      SELECT 1 FROM coverage_gap_recovery AS r
      WHERE r.gap_id = g.gap_id AND r.recovery_status = 'complete'
        AND r.recovered_through_locator = 'slot:102'
  );

INSERT INTO fixture_result
SELECT 'cursor reaches recovered slot only with exact evidence',
       cursor_value = '102' AND evidence_count = 1
FROM latest_source_cursor
WHERE source_id = 'src_fixture_chain'
  AND scope_kind = 'program'
  AND scope_key = 'fixture-program'
  AND cursor_kind = 'slot';

INSERT INTO fixture_result
WITH candidates AS (
    SELECT * FROM assertion
    WHERE semantic_key = 'fixture:trade:sig-equal:0'
      AND produced_commit_seq <= 7
), effective AS (
    SELECT older.assertion_id
    FROM candidates AS older
    WHERE NOT EXISTS (
        SELECT 1 FROM candidates AS newer
        WHERE newer.supersedes_assertion_id = older.assertion_id
    )
)
SELECT 'knowledge cutoff keeps pre-correction assertion',
       COUNT(*) = 1 AND MIN(assertion_id) = 'ast_trade_0_v1'
FROM effective;

INSERT INTO fixture_result
WITH candidates AS (
    SELECT * FROM assertion
    WHERE semantic_key = 'fixture:trade:sig-equal:0'
      AND produced_commit_seq <= 11
), effective AS (
    SELECT older.assertion_id
    FROM candidates AS older
    WHERE NOT EXISTS (
        SELECT 1 FROM candidates AS newer
        WHERE newer.supersedes_assertion_id = older.assertion_id
    )
)
SELECT 'retrospective cutoff includes correction',
       COUNT(*) = 1 AND MIN(assertion_id) = 'ast_trade_0_v2'
FROM effective;

INSERT INTO fixture_result
SELECT 'correction has old event time and late knowledge time',
       valid_lower_us = 1000000 AND produced_commit_seq = 8
       AND supersedes_assertion_id = 'ast_trade_0_v1'
FROM assertion
WHERE assertion_id = 'ast_trade_0_v2';

INSERT INTO fixture_result
SELECT 'witnessed and retrospective scenes are distinct',
       COUNT(*) = 2 AND COUNT(DISTINCT scene_mode) = 2
       AND COUNT(DISTINCT view_sha256) = 2
FROM scene
WHERE scene_id IN ('scn_fixture_witnessed', 'scn_fixture_retrospective');

INSERT INTO fixture_result
SELECT 'witnessed cutoff excludes later correction',
       knowledge_cutoff_commit_seq = 6
       AND outcome_cutoff_commit_seq IS NULL
       AND s.view_blob_id =
           'a336d1fe5cf40b171fd365df00b5b4e93aae8db2d891c23cbf0eac9d4130921f'
FROM scene AS s
WHERE s.scene_id = 'scn_fixture_witnessed';

-- External fixture bytes are verified by validate.sh. The catalog-level scene assertion checks the
-- cutoff and distinct view digests without pretending SQLite loaded the external body.

INSERT INTO fixture_result
SELECT 'runner flat-watch and reentry commands remain ordered and distinct',
       group_concat(command_kind, '|') =
           'reduce_requested|exit_all_requested|watch_started|reentry_requested'
FROM (
    SELECT command_kind FROM command
    WHERE subject_key = 'episode-fixture'
    ORDER BY committed_commit_seq
);

INSERT INTO fixture_result
SELECT 'flat and reentry use distinct inventory epochs',
       json_extract(flat.value_json, '$.inventory_epoch_id') = 'epoch-a'
       AND json_extract(reentry.value_json, '$.inventory_epoch_id') = 'epoch-b'
FROM assertion AS flat, assertion AS reentry
WHERE flat.assertion_id = 'ast_exact_flat'
  AND reentry.assertion_id = 'ast_reentry';

INSERT INTO fixture_result
SELECT 'watching flat remains inside the same episode',
       json_extract(value_json, '$.episode_id') = 'episode-fixture'
       AND json_extract(value_json, '$.transition') = 'watching_flat'
FROM assertion
WHERE assertion_id = 'ast_watching_flat';

INSERT INTO fixture_result
SELECT 'amounts cross boundaries as text',
       COUNT(*) = 9 AND MIN(typeof(signed_atoms)) = 'text' AND MAX(typeof(signed_atoms)) = 'text'
FROM assertion_amount;

INSERT INTO fixture_result
SELECT 'retried semantic command has one durable identity',
       COUNT(*) = 1
FROM command
WHERE client_session_id = 'client-fixture'
  AND idempotency_key = 'fixture-runner-retry-key';

INSERT INTO fixture_result
SELECT 'choice context keeps separate set memberships',
       COUNT(DISTINCT set_kind) = 5
FROM scene_choice_member
WHERE scene_id = 'scn_fixture_witnessed';

INSERT INTO fixture_result
SELECT 'export manifest names exact closed input range',
       from_commit_seq = 1 AND through_commit_seq = 11 AND created_commit_seq = 13
       AND format = 'fixture_opaque'
       AND file_sha256 = '92a6a5d1c027425d95c0ffd558861ecbe966a88007fc8bc2d69e10b44d303c96'
FROM export_manifest
WHERE export_manifest_id = 'exp_fixture_episode_01';

SELECT case_name, 'ok' AS status
FROM fixture_result
ORDER BY case_name;

DROP TABLE fixture_result;
