-- Private contact-camp persistence. Existing contact, users and payment schemas stay intact.
-- 0070 follows the current source's 0067 tracking, 0068 UI library and 0069 read cursor.
-- The former private-only 0067 camp prototype must not replace an existing ledger entry.
CREATE TABLE camp_config (
    id SMALLINT PRIMARY KEY CHECK (id=1),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version>0),
    config JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_by BIGINT REFERENCES users(id) ON DELETE SET NULL
);
INSERT INTO camp_config(id) VALUES (1);

CREATE TABLE camp_catalog (
    id VARCHAR(64) PRIMARY KEY,
    kind VARCHAR(8) NOT NULL CHECK (kind IN ('hero','pet')),
    display_name VARCHAR(50) NOT NULL,
    asset_key VARCHAR(100) NOT NULL,
    summon_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    rarity VARCHAR(3) CHECK (rarity IN ('R','SR','SSR','UR')),
    variant VARCHAR(10) NOT NULL DEFAULT 'standard' CHECK (variant IN ('standard','unique')),
    -- Version one explicitly has no rarity/unique differentiation.
    CONSTRAINT camp_catalog_v1_uniform CHECK (rarity IS NULL AND variant='standard')
);
INSERT INTO camp_catalog(id,kind,display_name,asset_key) VALUES
 ('hero_ranger','hero','游侠','hero_ranger'),
 ('hero_knight','hero','骑士','hero_knight'),
 ('hero_mage','hero','旅法师','hero_mage'),
 ('hero_bard','hero','吟游诗人','hero_bard'),
 ('hero_alchemist','hero','炼金师','hero_alchemist'),
 ('hero_astrologer','hero','星象学徒','hero_astrologer'),
 ('pet_deer','pet','小鹿','pet_deer'),
 ('pet_fox','pet','狐狸','pet_fox'),
 ('pet_rabbit','pet','兔子','pet_rabbit'),
 ('pet_owl','pet','猫头鹰','pet_owl'),
 ('pet_finch','pet','团雀','pet_finch'),
 ('pet_dragon','pet','幼龙','pet_dragon');

CREATE TABLE camp_players (
    user_id BIGINT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    first_seen_at TIMESTAMPTZ NOT NULL,
    bucket SMALLINT NOT NULL CHECK (bucket>=0 AND bucket<100),
    started_at TIMESTAMPTZ,
    paused BOOLEAN NOT NULL DEFAULT FALSE,
    preferences JSONB NOT NULL DEFAULT '{}'::jsonb,
    hero_id VARCHAR(64) REFERENCES camp_catalog(id),
    pet_id VARCHAR(64) REFERENCES camp_catalog(id),
    fragments BIGINT NOT NULL DEFAULT 0 CHECK (fragments>=0),
    cooldown_ends_at TIMESTAMPTZ,
    session_id UUID,
    last_sequence BIGINT NOT NULL DEFAULT -1,
    last_heartbeat_at TIMESTAMPTZ,
    last_page_category VARCHAR(10) CHECK (last_page_category IN ('camp','content','other'))
);
CREATE TABLE camp_daily (
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    day DATE NOT NULL,
    rounds_completed SMALLINT NOT NULL DEFAULT 0 CHECK (rounds_completed BETWEEN 0 AND 3),
    vip_wins SMALLINT NOT NULL DEFAULT 0 CHECK (vip_wins BETWEEN 0 AND 1),
    summon_member_bonus SMALLINT NOT NULL DEFAULT 0 CHECK (summon_member_bonus IN (0,2)),
    summons_used SMALLINT NOT NULL DEFAULT 0 CHECK (summons_used>=0 AND summons_used<=1+summon_member_bonus),
    content_ms BIGINT NOT NULL DEFAULT 0 CHECK (content_ms>=0),
    camp_ms BIGINT NOT NULL DEFAULT 0 CHECK (camp_ms>=0),
    other_ms BIGINT NOT NULL DEFAULT 0 CHECK (other_ms>=0),
    PRIMARY KEY (user_id,day)
);
CREATE INDEX camp_daily_day ON camp_daily(day);
CREATE TABLE camp_collection (
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    item_id VARCHAR(64) NOT NULL REFERENCES camp_catalog(id),
    acquired_at TIMESTAMPTZ NOT NULL,
    source VARCHAR(10) NOT NULL CHECK (source IN ('starter','summon','redeem')),
    PRIMARY KEY(user_id,item_id)
);
CREATE TABLE camp_rounds (
    id UUID PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    boss_key VARCHAR(64) NOT NULL,
    status VARCHAR(12) NOT NULL DEFAULT 'active' CHECK (status IN ('active','completed')),
    rule_version INTEGER NOT NULL,
    rules JSONB NOT NULL,
    reward_eligible BOOLEAN NOT NULL,
    elapsed_ms INTEGER NOT NULL DEFAULT 0 CHECK (elapsed_ms BETWEEN 0 AND 600000),
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    reward_day DATE,
    CHECK ((status='active' AND completed_at IS NULL AND reward_day IS NULL)
       OR (status='completed' AND completed_at IS NOT NULL AND reward_day IS NOT NULL AND elapsed_ms=600000))
);
CREATE UNIQUE INDEX camp_one_active_round ON camp_rounds(user_id) WHERE status='active';
CREATE INDEX camp_rounds_user_history ON camp_rounds(user_id,started_at DESC);
CREATE TABLE camp_rewards (
    id BIGSERIAL PRIMARY KEY,
    round_id UUID NOT NULL UNIQUE REFERENCES camp_rounds(id) ON DELETE CASCADE,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reward_day DATE NOT NULL,
    rule_version INTEGER NOT NULL,
    vip_won BOOLEAN NOT NULL,
    status VARCHAR(10) NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','granted')),
    vip_hours INTEGER NOT NULL DEFAULT 0 CHECK (vip_hours IN (0,72)),
    fragments INTEGER NOT NULL DEFAULT 0 CHECK (fragments IN (0,1,11)),
    permanent_member_replacement BOOLEAN NOT NULL DEFAULT FALSE,
    membership_before JSONB,
    membership_expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL,
    granted_at TIMESTAMPTZ,
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts>=0),
    last_error_code VARCHAR(80),
    next_retry_at TIMESTAMPTZ,
    CHECK ((status='pending' AND granted_at IS NULL) OR (status='granted' AND granted_at IS NOT NULL))
);
CREATE UNIQUE INDEX camp_one_vip_per_day ON camp_rewards(user_id,reward_day) WHERE vip_won;
CREATE INDEX camp_reward_retry ON camp_rewards(next_retry_at,id) WHERE status='pending';
CREATE INDEX camp_reward_history ON camp_rewards(user_id,id DESC);
CREATE INDEX camp_reward_day ON camp_rewards(reward_day);
CREATE INDEX camp_reward_issued_at ON camp_rewards(granted_at) WHERE status='granted';
CREATE TABLE camp_operations (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    request_id UUID NOT NULL,
    operation VARCHAR(10) NOT NULL CHECK (operation IN ('summon','redeem')),
    fingerprint VARCHAR(64) NOT NULL,
    result JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    UNIQUE (user_id,request_id)
);
CREATE INDEX camp_operation_history ON camp_operations(user_id,id DESC);
CREATE TABLE camp_events (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id) ON DELETE CASCADE,
    kind VARCHAR(40) NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX camp_event_history ON camp_events(user_id,id DESC);
CREATE INDEX camp_event_kind_time ON camp_events(kind,created_at);
CREATE TABLE camp_admin_audit (
    id BIGSERIAL PRIMARY KEY,
    actor_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    action VARCHAR(40) NOT NULL,
    reason VARCHAR(300) NOT NULL,
    before_value JSONB,
    after_value JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
