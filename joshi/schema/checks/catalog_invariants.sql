-- Executable whole-catalog invariants. A failed assertion aborts on CHECK(result = 1).
.bail on
PRAGMA foreign_keys = ON;

CREATE TEMP TABLE invariant_result (
    invariant_name TEXT PRIMARY KEY,
    result INTEGER NOT NULL CHECK (result = 1)
) STRICT;

INSERT INTO invariant_result VALUES
    ('foreign keys close', NOT EXISTS (SELECT 1 FROM pragma_foreign_key_check));

INSERT INTO invariant_result
SELECT 'migration ledger matches user_version',
       CASE WHEN COUNT(*) = (SELECT user_version FROM pragma_user_version)
                 AND COALESCE(MAX(migration_id), 0) = (SELECT user_version FROM pragma_user_version)
            THEN 1 ELSE 0 END
FROM schema_migration;

INSERT INTO invariant_result
SELECT 'commit digest chain is intact', NOT EXISTS (
    SELECT 1
    FROM (
        SELECT commit_seq, prior_commit_digest,
               lag(commit_digest) OVER (ORDER BY commit_seq) AS expected_prior,
               row_number() OVER (ORDER BY commit_seq) AS ordinal
        FROM ingest_commit
    )
    WHERE (ordinal = 1 AND prior_commit_digest IS NOT NULL)
       OR (ordinal > 1 AND prior_commit_digest IS NOT expected_prior)
);

INSERT INTO invariant_result
SELECT 'acquisition completion follows registration', NOT EXISTS (
    SELECT 1
    FROM acquisition_end AS ae
    JOIN acquisition AS a USING (acquisition_id)
    WHERE ae.ended_commit_seq < a.registered_commit_seq
);

INSERT INTO invariant_result
SELECT 'acquisition monotonic clock is a complete optional pair', NOT EXISTS (
    SELECT 1 FROM acquisition
    WHERE (local_clock_id IS NULL) <> (started_mono_ns IS NULL)
);

INSERT INTO invariant_result
SELECT 'blob metadata precedes every observation reference', NOT EXISTS (
    SELECT 1
    FROM observation AS o
    JOIN blob AS b USING (blob_id)
    WHERE b.created_commit_seq > o.commit_seq
);

INSERT INTO invariant_result
SELECT 'source-event identity is not known from the future', NOT EXISTS (
    SELECT 1
    FROM observation_source_event AS ose
    JOIN observation AS o USING (observation_id)
    JOIN source_event AS se USING (source_event_id)
    WHERE se.identified_commit_seq > o.commit_seq
      AND ose.relation = 'contains'
);

INSERT INTO invariant_result
SELECT 'accepted assertions have evidence', NOT EXISTS (
    SELECT 1
    FROM assertion AS a
    WHERE a.assertion_status = 'accepted'
      AND NOT EXISTS (
          SELECT 1 FROM assertion_observation_evidence AS e
          WHERE e.assertion_id = a.assertion_id
      )
      AND NOT EXISTS (
          SELECT 1 FROM assertion_source_event AS e
          WHERE e.assertion_id = a.assertion_id
      )
      AND NOT EXISTS (
          SELECT 1 FROM assertion_command_evidence AS e
          WHERE e.assertion_id = a.assertion_id
      )
);

INSERT INTO invariant_result
SELECT 'supersession preserves key and advances knowledge', NOT EXISTS (
    SELECT 1
    FROM assertion AS newer
    JOIN assertion AS older
      ON older.assertion_id = newer.supersedes_assertion_id
    WHERE newer.semantic_key <> older.semantic_key
       OR newer.produced_commit_seq <= older.produced_commit_seq
);

INSERT INTO invariant_result
SELECT 'cursor evidence cardinality is exact', NOT EXISTS (
    SELECT 1
    FROM source_cursor AS c
    LEFT JOIN source_cursor_evidence AS e USING (cursor_id)
    GROUP BY c.cursor_id, c.evidence_count
    HAVING COUNT(e.observation_id) <> c.evidence_count
);

INSERT INTO invariant_result
SELECT 'cursor primary evidence is linked', NOT EXISTS (
    SELECT 1
    FROM source_cursor AS c
    WHERE NOT EXISTS (
        SELECT 1 FROM source_cursor_evidence AS e
        WHERE e.cursor_id = c.cursor_id
          AND e.observation_id = c.primary_evidence_observation_id
    )
);

INSERT INTO invariant_result
SELECT 'cursor predecessor stays in scope and moves forward', NOT EXISTS (
    SELECT 1
    FROM source_cursor AS newer
    JOIN source_cursor AS older ON older.cursor_id = newer.predecessor_cursor_id
    WHERE older.source_id <> newer.source_id
       OR older.scope_kind <> newer.scope_kind
       OR older.scope_key <> newer.scope_key
       OR older.cursor_kind <> newer.cursor_kind
       OR older.advanced_commit_seq >= newer.advanced_commit_seq
);

INSERT INTO invariant_result
SELECT 'gap recovery advances knowledge', NOT EXISTS (
    SELECT 1
    FROM coverage_gap_recovery AS r
    JOIN coverage_gap AS g USING (gap_id)
    WHERE r.commit_seq <= g.detected_commit_seq
);

INSERT INTO invariant_result
SELECT 'scene delivery watermarks respect replay boundary', NOT EXISTS (
    SELECT 1
    FROM scene_watermark AS w
    JOIN scene AS s USING (scene_id)
    WHERE (s.scene_mode IN ('witnessed', 'knowledge_cutoff')
           AND w.delivered_commit_seq > s.knowledge_cutoff_commit_seq)
       OR (s.scene_mode = 'retrospective'
           AND w.delivered_commit_seq > s.outcome_cutoff_commit_seq)
);

INSERT INTO invariant_result
SELECT 'witnessed choices contain no future assertions', NOT EXISTS (
    SELECT 1
    FROM scene_choice_member AS m
    JOIN scene AS s USING (scene_id)
    JOIN assertion AS a ON a.assertion_id = m.evidence_assertion_id
    WHERE s.scene_mode = 'witnessed'
      AND a.produced_commit_seq > s.knowledge_cutoff_commit_seq
);

INSERT INTO invariant_result
SELECT 'command is not committed before its scene', NOT EXISTS (
    SELECT 1
    FROM command AS c
    JOIN scene AS s USING (scene_id)
    WHERE c.committed_commit_seq < s.captured_commit_seq
);

INSERT INTO invariant_result
SELECT 'all commands are evidence-only', NOT EXISTS (
    SELECT 1 FROM command
    WHERE effect_ceiling <> 'observe_only' OR authority_class <> 'evidence_only'
);

INSERT INTO invariant_result
SELECT 'outbox has no economic or network effect class', NOT EXISTS (
    SELECT 1 FROM outbox_item
    WHERE effect_class NOT IN ('projection', 'export', 'thumbnail', 'analysis')
);

INSERT INTO invariant_result
SELECT 'operational artifacts cannot acquire economic authority',
    NOT EXISTS (SELECT 1 FROM source_fact_artifact
                WHERE authority <> 'read_only_no_execution')
    AND NOT EXISTS (SELECT 1 FROM projection_publication
                    WHERE authority <> 'read_only_no_execution')
    AND NOT EXISTS (SELECT 1 FROM cockpit_publication
                    WHERE authority <> 'read_only_no_execution')
    AND NOT EXISTS (SELECT 1 FROM derived_analysis_artifact
                    WHERE authority <> 'read_only_no_execution')
    AND NOT EXISTS (SELECT 1 FROM presentation_scene_v1
                    WHERE authority_class <> 'evidence_only' OR effect_ceiling <> 'observe_only')
    AND NOT EXISTS (SELECT 1 FROM presentation_event_v1
                    WHERE authority_class <> 'evidence_only' OR effect_ceiling <> 'observe_only');

INSERT INTO invariant_result
SELECT 'projection and derived artifacts consume only prior knowledge',
    NOT EXISTS (SELECT 1 FROM projection_publication
                WHERE through_commit_seq >= created_commit_seq)
    AND NOT EXISTS (SELECT 1 FROM derived_analysis_artifact
                    WHERE fit_through_commit_seq >= created_commit_seq);

INSERT INTO invariant_result
SELECT 'presentation events close an earlier exact presentation', NOT EXISTS (
    SELECT 1 FROM presentation_event_v1 e
    LEFT JOIN presentation_scene_v1 p
      ON p.presentation_id=e.presentation_id
     AND p.presentation_sha256=e.presentation_sha256
     AND p.scene_id=e.scene_id
     AND p.view_sha256=e.view_sha256
    WHERE p.presentation_id IS NULL OR p.created_commit_seq >= e.created_commit_seq
);

INSERT INTO invariant_result
SELECT 'analysis imports cannot mutate their truth fingerprint', NOT EXISTS (
    SELECT 1 FROM derived_analysis_artifact
    WHERE truth_fingerprint_before <> truth_fingerprint_after
);

INSERT INTO invariant_result
SELECT 'projection checkpoints only consume prior commits', NOT EXISTS (
    SELECT 1 FROM projection_checkpoint
    WHERE through_commit_seq > created_commit_seq
);

INSERT INTO invariant_result
SELECT 'exports are closed before manifest commit', NOT EXISTS (
    SELECT 1 FROM export_manifest
    WHERE from_commit_seq > through_commit_seq
       OR through_commit_seq > created_commit_seq
);

INSERT INTO invariant_result
SELECT 'v5 lossless sidecars close every typed parent',
    NOT EXISTS (
        SELECT 1 FROM acquisition a LEFT JOIN acquisition_contract d USING(acquisition_id)
        WHERE d.acquisition_id IS NULL
    )
    AND NOT EXISTS (
        SELECT 1 FROM observation o LEFT JOIN observation_contract d USING(observation_id)
        WHERE d.observation_id IS NULL
    )
    AND NOT EXISTS (
        SELECT 1 FROM observation o LEFT JOIN observation_blob_contract d USING(observation_id)
        WHERE d.observation_id IS NULL
    )
    AND NOT EXISTS (
        SELECT 1 FROM source_event e LEFT JOIN source_event_contract d USING(source_event_id)
        WHERE d.source_event_id IS NULL
    )
    AND NOT EXISTS (
        SELECT 1 FROM assertion a LEFT JOIN assertion_contract d USING(assertion_id)
        WHERE d.assertion_id IS NULL
    )
    AND NOT EXISTS (
        SELECT 1 FROM coverage_window w LEFT JOIN coverage_window_contract d USING(coverage_id)
        WHERE d.coverage_id IS NULL
    )
    AND NOT EXISTS (
        SELECT 1 FROM coverage_gap g LEFT JOIN coverage_gap_contract d USING(gap_id)
        WHERE d.gap_id IS NULL
    )
    AND NOT EXISTS (
        SELECT 1 FROM coverage_gap_recovery r
        LEFT JOIN coverage_recovery_contract d USING(recovery_id)
        WHERE d.recovery_id IS NULL
    )
    AND NOT EXISTS (
        SELECT 1 FROM source_cursor c LEFT JOIN source_cursor_contract d USING(cursor_id)
        WHERE d.cursor_id IS NULL
    )
    AND NOT EXISTS (
        SELECT 1 FROM observation_source_event e
        LEFT JOIN observation_source_event_contract d
          USING(observation_id, source_event_id, relation)
        WHERE d.observation_id IS NULL
    )
    AND NOT EXISTS (
        SELECT 1 FROM assertion_observation_evidence e
        LEFT JOIN assertion_observation_evidence_contract d
          USING(assertion_id, observation_id, evidence_role)
        WHERE d.assertion_id IS NULL
    )
    AND NOT EXISTS (
        SELECT 1 FROM assertion_source_event e
        LEFT JOIN assertion_source_event_contract d
          USING(assertion_id, source_event_id, relation)
        WHERE d.assertion_id IS NULL
    )
    AND NOT EXISTS (
        SELECT 1 FROM assertion_command_evidence e
        LEFT JOIN assertion_command_evidence_contract d
          USING(assertion_id, command_id, evidence_role)
        WHERE d.assertion_id IS NULL
    );

INSERT INTO invariant_result
SELECT 'physical blob policy is reference-local', NOT EXISTS (
    SELECT 1 FROM observation_blob_contract r
    LEFT JOIN blob_object o
      ON o.blob_id = r.blob_id AND o.storage_domain = r.storage_domain
    WHERE o.blob_id IS NULL
);

INSERT INTO invariant_result
SELECT 'scene and command artifacts name a protection domain',
    NOT EXISTS (
        SELECT 1 FROM scene s LEFT JOIN scene_artifact_contract a
          ON a.scene_id=s.scene_id AND a.artifact_role='view'
        WHERE a.scene_id IS NULL
    )
    AND NOT EXISTS (
        SELECT 1 FROM command c LEFT JOIN command_payload_contract p USING(command_id)
        WHERE p.command_id IS NULL
    );

INSERT INTO invariant_result
SELECT 'every export part belongs to an immutable snapshot manifest', NOT EXISTS (
    SELECT 1 FROM export_manifest p
    LEFT JOIN export_snapshot_part l USING(export_manifest_id)
    WHERE l.export_manifest_id IS NULL
);

INSERT INTO invariant_result
SELECT 'durable watermark uses observation knowledge and justified cursor', NOT EXISTS (
    SELECT 1 FROM durable_source_watermark w
    WHERE w.delivered_through_commit_seq < (
        SELECT MAX(o.commit_seq) FROM observation o WHERE o.source_id = w.source_id
    )
       OR (w.justified_cursor_value IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM source_cursor c
            WHERE c.source_id = w.source_id
              AND c.cursor_value = w.justified_cursor_value
              AND c.advanced_commit_seq <= w.delivered_through_commit_seq
       ))
);

INSERT INTO invariant_result
SELECT 'tagged coverage boundaries use compact canonical JSON',
    NOT EXISTS (
        SELECT 1 FROM coverage_window_contract
        WHERE json(lower_boundary_json) <> lower_boundary_json
           OR (upper_boundary_json IS NOT NULL
               AND json(upper_boundary_json) <> upper_boundary_json)
    )
    AND NOT EXISTS (
        SELECT 1 FROM coverage_gap_contract
        WHERE json(lower_boundary_json) <> lower_boundary_json
           OR (upper_boundary_json IS NOT NULL
               AND json(upper_boundary_json) <> upper_boundary_json)
    )
    AND NOT EXISTS (
        SELECT 1 FROM coverage_recovery_contract
        WHERE recovered_through_json IS NOT NULL
          AND json(recovered_through_json) <> recovered_through_json
    );

SELECT invariant_name, 'ok' AS status
FROM invariant_result
ORDER BY invariant_name;

DROP TABLE invariant_result;
