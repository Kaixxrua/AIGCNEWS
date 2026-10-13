"""Free access policy: billing history never grants identity or admin privileges."""

from copy import deepcopy

import pytest

from backend.app.domain.membership import resolve_access_tier
from backend.app.domain.tracking import rule_limit
from backend.app.services.mcp.inbound.context import McpAuthorizationContext


@pytest.mark.parametrize("user", [
    {"user_id": 42, "membership_tier": "free", "role": "user"},
    {"id": 42, "membership_tier": "member", "membership_expires_at": "2020-01-01T00:00:00Z"},
    {"sub": "42"},
])
def test_all_active_accounts_have_full_access_without_mutating_billing(user):
    original = deepcopy(user)
    assert resolve_access_tier(user) == "member"
    assert rule_limit(user) == 10
    assert user == original


@pytest.mark.parametrize("user", [
    None, {}, {"role": "admin"}, {"membership_tier": "member"},
    {"user_id": 0}, {"user_id": -1}, {"user_id": "invalid"},
    {"user_id": True}, {"user_id": 42, "disabled": True},
])
def test_missing_or_disabled_identity_never_receives_account_access(user):
    assert resolve_access_tier(user) == "free"


def test_mcp_free_access_does_not_add_scopes_or_admin_role():
    user = {"user_id": 42, "role": "user", "membership_tier": "free", "scopes": ["tracking:read"]}
    context = McpAuthorizationContext(user)
    assert context.membership_tier == "member"
    assert context.has_scope("tracking:read")
    assert not context.has_scope("projects:favorites:read")
    assert user["role"] == "user"
    assert McpAuthorizationContext(None).membership_tier == "free"
