-- ===========================================================================
-- WhyMath prod DB (docker "whymath-pg", host port 5433) schema revision probe
-- ===========================================================================
-- READ-ONLY. No DDL, no DML, no writes. Safe to run on prod at any time.
--
-- WHY: whymath-pg records alembic_version = 'd6e7f8a9b0c1', a revision that
-- does NOT exist in this repo's migration chain, so `alembic current` and
-- `alembic upgrade head` both abort with "Can't locate revision" (exit 255).
-- Before stamping, the ACTUAL schema position must be established from the
-- schema itself, not from the version table (CLAUDE.md: an indirect signal is
-- never a verdict). This probe checks, for each revision in the tail of the
-- chain, one object that revision creates. The last contiguously-present
-- revision is the true stamp target.
--
-- ASCII ONLY - the file is piped through psql on a Korean Windows host
-- (cp949 locale). Korean documentation lives in the gate notes, not here.
--
-- Usage (Windows PowerShell, repo root):
--   Get-Content scripts\ops\probe_prod_schema_revision.sql | `
--     docker exec -i whymath-pg psql -U whymath -d whymath -v ON_ERROR_STOP=1 -f -
--   echo "EXIT=$LASTEXITCODE"
--
-- Discriminators are derived from src/backend/alembic/versions/*.py upgrade()
-- bodies (create_table / add_column / drop_column / alter_column). seq =
-- position in the linear chain (length 99, head = 3f5c83f51246).
--
-- KIND. What the probe looks at for a row:
--   'object'  - existence. obj_column = '' means "check the table", otherwise
--               "check the column". This covers create_table / add_column /
--               drop_column revisions (the original vocabulary).
--   'default' - the column's DEFAULT clause (column_default IS NOT NULL). This
--               covers a revision that only changes an ATTRIBUTE of a column
--               that already exists, where existence proves nothing.
-- Why 'default' had to exist (SEC-33, 2026-09-08): revision 19149e92d368 only
-- runs `ALTER COLUMN problem_attempt.ingested_at SET DEFAULT now()`. The column
-- itself has existed since c9bc2555282e (seq 86), so an 'object' row for it
-- would report present = true on a database that has NOT applied 19149e92d368.
-- The stamp target would then jump past it, pending_count would read 0, and
-- `upgrade head` would never run the SET DEFAULT -- the same silent-skip failure
-- the drop-only note below describes. Measured, not assumed: injecting that
-- naive row passed all 18 guards in tests/infra/test_prod_schema_probe.py.
--
-- POLARITY. Most rows are '+': the object EXISTS once the revision is applied.
-- A revision that only DROPS something needs '-': the object's ABSENCE is what
-- the revision leaves behind. The two directions carry different weight:
--   '+' present  => applied (proof).      '+' absent  => not applied (proof).
--   '-' present  => NOT applied (proof).  '-' absent  => inconclusive, since a
--       database that never had the column looks identical to one that dropped
--       it. So '-' is a one-way BRAKE: it can stop the stamp target from moving
--       past the drop, but it can never push it forward on its own.
-- Skipping a drop-only revision entirely (the first version of this probe did)
-- is unsafe: with the column still present, the probe would name a stamp target
-- AFTER the drop and report present_after_gap = 0, and stamping there tells
-- alembic the drop is done -- `upgrade head` then never runs it, leaving the
-- column forever. Reported on PR #929 review.
-- ===========================================================================

\echo '== recorded alembic_version (indirect signal - NOT the verdict) =='
SELECT version_num FROM alembic_version;

\echo ''
\echo '== per-revision presence (the verdict) =='

CREATE TEMP VIEW probe AS
WITH expected(seq, revision, obj_table, obj_column, polarity, obj_kind) AS (
    VALUES
        (63, 'd5e6f0a1b2c3', 'unit_spec',              '',                          '+', 'object'),
        (64, 'e6f1a2b3c4d5', 'evidence_event',         '',                          '+', 'object'),
        -- drop-only revision: the column's PRESENCE proves this is not applied.
        (65, 'f1a2b3c4d5e7', 'concept',                'embedding_id',              '-', 'object'),
        (66, 'a2b3c4d5e6f1', 'dialogue_turn',          'image_uri_encrypted',       '+', 'object'),
        (67, 'a9b8c7d6e5f4', 'concept_visual_style',   '',                          '+', 'object'),
        (68, 'b4c5d6e7f0a2', 'formula_node',           'constraints',               '+', 'object'),
        (69, 'c5d6e7f0a2b3', 'user_profile',           'role',                      '+', 'object'),
        (70, '3702d8671074', 'privacy_audit',          '',                          '+', 'object'),
        (71, 'd6e7f0a2b3c4', 'refresh_token_session',  'platform',                  '+', 'object'),
        (72, 'db8ae6d2d91c', 'defect_report',          '',                          '+', 'object'),
        (73, '090d254a5d43', 'problem',                'identity_id',               '+', 'object'),
        (74, 'c6d7e8f1a2b4', 'solution_paths',         '',                          '+', 'object'),
        (75, '374fb620de9e', 'misconception_relation', '',                          '+', 'object'),
        (76, 'd1e2f3c4b5a6', 'dialogue',               'review_turns_remaining',    '+', 'object'),
        (77, 'e07b1324d1d4', 'content_rights',         '',                          '+', 'object'),
        (78, 'b8e76fe238d0', 'achievement_standard',   'official_statement',        '+', 'object'),
        (79, 'fcfdfc277348', 'achievement_standard',   'evaluation_criteria_codes', '+', 'object'),
        (80, '899ae0efbb8b', 'curriculum_framework',   '',                          '+', 'object'),
        (81, 'fad7f750090d', 'concept_edge',           'required_strength',         '+', 'object'),
        (82, 'd7e8f1a2b4c6', 'solution_paths',         'gen_meta',                  '+', 'object'),
        (83, '8f0b8e906362', 'answer_submission',      '',                          '+', 'object'),
        (84, '0e148995e6e9', 'hint_usage',             '',                          '+', 'object'),
        (85, 'a926d39f126a', 'student_solution_step',  '',                          '+', 'object'),
        (86, 'c9bc2555282e', 'attempt_event',          'event_time',                '+', 'object'),
        (87, '84c782415837', 'review_timer_event',     '',                          '+', 'object'),
        (88, 'f4b2d8c1a3e5', 'generation_log',         'prompt_version',            '+', 'object'),
        (89, 'd4a71c0f9b32', 'attempt_event',          'skill_ids',                 '+', 'object'),
        (90, 'e7c3b9a15f24', 'problem',                'quarantine_reason',         '+', 'object'),
        (91, 'b8d3f6a91c24', 'generation_log',         'run_id',                    '+', 'object'),
        (92, 'c1a5e07b4d38', 'generation_log',         'cache_read_input_tokens',   '+', 'object'),
        (93, 'd2f4a68b91e7', 'misconception_hypothesis', 'deactivated_reason',      '+', 'object'),
        (94, 'e3b5c79d02f8', 'evidence_links',         'provenance',                '+', 'object'),
        -- attribute-only revision: the column predates it, so only its DEFAULT
        -- separates "applied" from "not applied" (see KIND note in the header).
        (95, '19149e92d368', 'problem_attempt',        'ingested_at',               '+', 'default'),
        (96, 'f2662166a661', 'job_ownership',          '',                          '+', 'object'),
        (97, '4c6dfb1527a9', 'privacy_audit',          'resource_type',             '+', 'object'),
        (98, '3f5c83f51246', 'problem_attempt',        'student_answer_encrypted',  '+', 'object'),
        (99, '67cf48ad3bce', 'concept_version',        '',                          '+', 'object'),
        (100, 'a7d41c9e0b52', 'learner_state',        '',                          '+', 'object'),
        (101, '5a7c31d9e0b4', 'learning_state_transition', '',                    '+', 'object'),
        (102, 'c1f5a8b2d740', 'concept_mastery_history', 'attempt_id',           '+', 'object'),
        (103, 'd2a9e4b71c35', 'generation_log',      'served_model',             '+', 'object'),
        (104, '5b3e9c27a1f6', 'problem_attempt',     'selected_choice_index',    '+', 'object'),
        (105, '8e4c2a7f1b93', 'learning_session',    'last_activity_at',         '+', 'object'),
        (106, '8c19e8a611e4', 'privacy_audit',       'token_expires_at',         '+', 'object')
)
SELECT
    e.seq,
    e.revision,
    e.obj_table AS checked_table,
    -- the suffix matters to the operator reading this: an attribute row is NOT
    -- answering "does the column exist" (it does), so label what was asked.
    CASE
        WHEN e.obj_kind = 'default' THEN e.obj_column || ' (default)'
        WHEN e.obj_column = '' THEN '(table)'
        ELSE e.obj_column
    END AS checked_object,
    e.polarity,
    -- "applied" for this row: '+' rows want the object to exist, '-' rows want
    -- it gone. The XOR-style flip keeps one contiguity rule for both kinds.
    (
        CASE
            -- attribute check: the column exists either way, so ask whether it
            -- carries a DEFAULT. Ordered first so it wins over the column branch.
            WHEN e.obj_kind = 'default' THEN EXISTS (
                SELECT 1 FROM information_schema.columns c
                WHERE c.table_schema = 'public'
                  AND c.table_name = e.obj_table
                  AND c.column_name = e.obj_column
                  AND c.column_default IS NOT NULL)
            WHEN e.obj_column = '' THEN EXISTS (
                SELECT 1 FROM information_schema.tables t
                WHERE t.table_schema = 'public' AND t.table_name = e.obj_table)
            ELSE EXISTS (
                SELECT 1 FROM information_schema.columns c
                WHERE c.table_schema = 'public'
                  AND c.table_name = e.obj_table
                  AND c.column_name = e.obj_column)
        END
    ) = (e.polarity = '+') AS present
FROM expected e;

SELECT seq, revision, checked_table, checked_object, polarity, present
FROM probe ORDER BY seq;

\echo ''
\echo '== verdict =='
-- stamp_target      : last revision whose object is present with no gap before it.
-- pending_count     : revisions after that target (what `upgrade head` would apply).
-- present_after_gap : MUST be 0. Anything else means the schema is interleaved
--                     (some later revision applied while an earlier one was not),
--                     and stamping would make alembic skip or re-create objects.
SELECT
    (SELECT p.revision FROM probe p
      WHERE p.present
        AND NOT EXISTS (SELECT 1 FROM probe q WHERE q.seq <= p.seq AND NOT q.present)
      ORDER BY p.seq DESC LIMIT 1)                       AS stamp_target,
    (SELECT count(*) FROM probe p WHERE NOT p.present)   AS pending_count,
    (SELECT count(*) FROM probe p
      WHERE p.present
        AND EXISTS (SELECT 1 FROM probe q WHERE q.seq < p.seq AND NOT q.present))
                                                         AS present_after_gap;
