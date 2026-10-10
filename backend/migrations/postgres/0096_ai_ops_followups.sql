-- Observed recovery evidence survives the 30-day investigation log retention.
CREATE TABLE ai_ops_followups (
    id UUID PRIMARY KEY,
    run_id UUID NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('ingestion_orphan_close','x_translation_retry','briefing_regenerate','public_feed_retry')),
    target TEXT NOT NULL,
    baseline JSONB NOT NULL DEFAULT '{}',
    policy_version TEXT NOT NULL DEFAULT 'ai-ops-v2',
    runtime_sha TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','verified','not_recovered','inconclusive')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    next_check_at TIMESTAMPTZ NOT NULL DEFAULT now() + interval '2 minutes',
    deadline_at TIMESTAMPTZ NOT NULL DEFAULT now() + interval '2 hours',
    checked_at TIMESTAMPTZ,
    evidence JSONB NOT NULL DEFAULT '{}'
);
CREATE INDEX ai_ops_followups_due ON ai_ops_followups (next_check_at) WHERE status='pending';
CREATE INDEX ai_ops_followups_recent ON ai_ops_followups (created_at DESC);
CREATE INDEX ai_ops_followups_cases ON ai_ops_followups (checked_at DESC) WHERE status IN ('verified','not_recovered');
