from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from backend.app.domain.membership_trial import TrialSnapshot

#: started=本次开通成功；already_used=这个账号用过试用；already_member=眼下是有效会员；
#: user_missing=账号不存在（注销与请求并发）。
TrialStartOutcome = Literal["started", "already_used", "already_member", "user_missing"]


@dataclass(frozen=True)
class TrialStartResult:
    outcome: TrialStartOutcome
    #: 开通后（或拒绝时）同一事务里看到的会员列与试用记录；user_missing 时为 None
    snapshot: TrialSnapshot | None


class MembershipTrialRepository(Protocol):
    def get_trial_snapshot(self, user_id: int) -> TrialSnapshot | None: ...

    def start_trial(self, *, user_id: int, now: datetime) -> TrialStartResult: ...
