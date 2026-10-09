from pathlib import Path

import pytest

from backend.build_wheel_cache import cached_requirements

HASH = "a" * 64
CACHED = f"cached-pkg==1.0 \\\n    --hash=sha256:{HASH} \\\n    --hash=sha256:{'b' * 64}\n"
REMOTE = f"remote-pkg==2.0 --hash=sha256:{HASH}\n"


def test_selects_compatible_locked_version_and_preserves_every_hash(tmp_path: Path) -> None:
    (tmp_path / "cached_pkg-1.0-py3-none-any.whl").write_bytes(b"candidate content")
    (tmp_path / "remote_pkg-1.0-py3-none-any.whl").write_bytes(b"older version")
    assert cached_requirements(CACHED + REMOTE, tmp_path, supported_tags={"py3-none-any"}) == CACHED


@pytest.mark.parametrize("filename", [
    "cached_pkg-0.9-py3-none-any.whl",
    "cached_pkg-1.0-cp311-cp311-win_amd64.whl",
    "cached_pkg-1.0.tar.gz",
    "invalid.whl",
])
def test_missing_compatible_wheel_stays_for_index_install(tmp_path: Path, filename: str) -> None:
    (tmp_path / filename).write_bytes(b"candidate")
    assert cached_requirements(CACHED, tmp_path, supported_tags={"py3-none-any"}) == ""


def test_empty_cache_is_supported(tmp_path: Path) -> None:
    assert cached_requirements(CACHED, tmp_path) == ""


def test_cache_contents_cannot_replace_expected_hashes(tmp_path: Path) -> None:
    (tmp_path / "cached_pkg-1.0-py3-none-any.whl").write_bytes(b"corrupt archive")
    # uv --require-hashes must reject these bytes; the selector cannot bless them.
    assert cached_requirements(CACHED, tmp_path, supported_tags={"py3-none-any"}) == CACHED


def test_symlink_is_not_a_cached_wheel(tmp_path: Path) -> None:
    target = tmp_path / "unrelated"
    target.write_bytes(b"candidate")
    (tmp_path / "cached_pkg-1.0-py3-none-any.whl").symlink_to(target)
    assert cached_requirements(CACHED, tmp_path, supported_tags={"py3-none-any"}) == ""


def test_rejects_missing_hashes_and_incomplete_manifest(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="index-provided hashes"):
        cached_requirements("cached-pkg==1.0\n", tmp_path)
    with pytest.raises(ValueError, match="unterminated"):
        cached_requirements("cached-pkg==1.0 \\\n", tmp_path)
