-- Private, forward-only combat completion constraint. Never rewrite 0070.
-- No row, reward, membership, progress or old rules snapshot is changed.
-- The normal runner validates the complete prior filename/checksum ledger.
-- Every existing row is validated by the new constraint in this transaction.
ALTER TABLE camp_rounds DROP CONSTRAINT camp_rounds_check;
ALTER TABLE camp_rounds ADD CONSTRAINT camp_rounds_check CHECK (
    (status='active' AND completed_at IS NULL AND reward_day IS NULL)
    OR
    (status='completed' AND completed_at IS NOT NULL AND reward_day IS NOT NULL
     AND CASE
         WHEN NOT (rules ? 'combat') THEN elapsed_ms=600000
         WHEN rules->'combat'->>'version'='skills_v1' THEN elapsed_ms=261430
         ELSE FALSE
     END)
);
