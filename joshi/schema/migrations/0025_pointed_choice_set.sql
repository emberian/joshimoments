-- Widen the scene choice-set vocabulary with `pointed`.
--
-- The operator model this schema was written under said Ember was screen-reader, keyboard-only,
-- so the client-observed attention kinds were focus-shaped: `viewport` (reading reached the
-- row), `interacted`, `compared`.  She corrected that directly -- she is primarily visual and
-- uses a pointer DELIBERATELY as an attention marker ("scroll rectangle is good and so is my
-- pointer, i can be mindful to intentionally use the pointer to capture some aspect of my
-- attention").  A deliberate pointer entry is therefore its own honest observation, distinct
-- from the seen set it also feeds, and it gets its own kind rather than being blurred into
-- `viewport`: the selection instrument's denominator stays `viewport`-then-`rendered`, and
-- `pointed` arrives as an additional recorded signal, never a substitute.
--
-- SQLite cannot alter a CHECK constraint, so the table is rebuilt: create the successor with
-- the widened constraint, copy every row, drop the original, rename, and re-create the three
-- triggers exactly as 0003 and 0004 defined them.  The append-only guards are not being
-- circumvented: every row is carried into the successor first, and DROP TABLE removes the
-- table and its triggers wholesale rather than deleting rows through them (the same reasoning
-- 0024 recorded).  The table is a leaf -- nothing in the schema references it -- so the rebuild
-- needs no foreign-key suspension.

CREATE TABLE scene_choice_member_widened (
    scene_id TEXT NOT NULL REFERENCES scene(scene_id),
    set_kind TEXT NOT NULL CHECK (
        set_kind IN ('eligible', 'surfaced', 'rendered', 'viewport', 'interacted', 'compared', 'pointed')
    ),
    subject_kind TEXT NOT NULL CHECK (subject_kind <> ''),
    subject_key TEXT NOT NULL CHECK (subject_key <> ''),
    source_rank INTEGER CHECK (source_rank IS NULL OR source_rank >= 0),
    rendered_ordinal INTEGER CHECK (rendered_ordinal IS NULL OR rendered_ordinal >= 0),
    evidence_assertion_id TEXT REFERENCES assertion(assertion_id),
    PRIMARY KEY (scene_id, set_kind, subject_kind, subject_key)
) STRICT, WITHOUT ROWID;

INSERT INTO scene_choice_member_widened
SELECT scene_id, set_kind, subject_kind, subject_key, source_rank, rendered_ordinal,
       evidence_assertion_id
FROM scene_choice_member;

DROP TABLE scene_choice_member;

ALTER TABLE scene_choice_member_widened RENAME TO scene_choice_member;

-- The three triggers 0003/0004 defined on the original table, re-created verbatim.

CREATE TRIGGER witnessed_choice_has_no_future_assertion
BEFORE INSERT ON scene_choice_member
WHEN NEW.evidence_assertion_id IS NOT NULL
BEGIN
    SELECT CASE
        WHEN (SELECT scene_mode FROM scene WHERE scene_id = NEW.scene_id) = 'witnessed'
             AND (SELECT produced_commit_seq FROM assertion
                  WHERE assertion_id = NEW.evidence_assertion_id) >
                 (SELECT knowledge_cutoff_commit_seq FROM scene WHERE scene_id = NEW.scene_id)
        THEN RAISE(ABORT, 'witnessed choice assertion exceeds knowledge cutoff')
    END;
END;

CREATE TRIGGER no_update_scene_choice_member BEFORE UPDATE ON scene_choice_member
BEGIN SELECT RAISE(ABORT, 'scene_choice_member is append-only'); END;
CREATE TRIGGER no_delete_scene_choice_member BEFORE DELETE ON scene_choice_member
BEGIN SELECT RAISE(ABORT, 'scene_choice_member is append-only'); END;
