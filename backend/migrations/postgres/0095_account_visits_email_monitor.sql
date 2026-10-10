-- Account/day facts are independent of anonymous browser IDs and Redis.
CREATE TABLE account_visit_tracking (
    id SMALLINT PRIMARY KEY CHECK (id = 1),
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO account_visit_tracking (id) VALUES (1);

CREATE TABLE account_visit_days (
    day DATE NOT NULL,
    user_id BIGINT NOT NULL,
    is_returning BOOLEAN NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (day, user_id)
);
-- Deliberately no cascading FK: deleting an account must not rewrite historical
-- aggregates. No email, IP, token or profile is copied into these facts.

CREATE TABLE email_send_events (
    id BIGSERIAL PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    kind TEXT NOT NULL CHECK (kind IN ('otp', 'briefing')),
    outcome TEXT NOT NULL CHECK (outcome IN ('accepted', 'failed')),
    error_type TEXT
);
CREATE INDEX email_send_events_occurred_idx ON email_send_events (occurred_at);

CREATE TABLE email_monitor_state (
    id SMALLINT PRIMARY KEY CHECK (id = 1),
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    state JSONB NOT NULL DEFAULT '{}',
    lease_token UUID,
    lease_until TIMESTAMPTZ,
    next_check_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT INTO email_monitor_state (id) VALUES (1);
