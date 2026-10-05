import re

# 路径里独立成段的 trial / trials（industrial 之类的词不算）
_TRIAL_SEGMENT = re.compile(r"(?:^|[/_-])trials?(?:$|[/_-])")


def test_membership_trial_is_not_mounted():
    # 会员试用已撤下：不提供会员试用，任何试用领取入口都不得挂到 API 上。
    from backend.app.main import app

    paths = set(app.openapi()["paths"])
    assert "/api/membership/trial" not in paths
    assert not [path for path in paths if _TRIAL_SEGMENT.search(path.lower())]
