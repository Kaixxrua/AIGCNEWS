"""黄金语料 pytest 入口（PR 2.1）。

- 默认（verify）：逐案重放并与 ``corpus/*.jsonl`` 比对，任一漂移即红；
- ``PARITY_RECORD=1``：重录全部语料 + fixtures.json + recording_context.json。

必须经 pytest 运行：conftest.py 把 MCP_TOOL_CALL_METRICS_PATH 重定向到临时
目录，确保录制/回放绝不写生产计数文件。
"""

from __future__ import annotations

import pytest

from backend.tests.parity import recorder

requires_record_mode = pytest.mark.skipif(
    not recorder.RECORD_MODE, reason="仅 PARITY_RECORD=1 时重录语料"
)
requires_verify_mode = pytest.mark.skipif(
    recorder.RECORD_MODE, reason="PARITY_RECORD=1 录制态跳过逐案校验"
)


@requires_record_mode
def test_record_corpus() -> None:
    recorder.record_all()


@requires_verify_mode
@pytest.mark.parametrize("case", recorder.CASES, ids=[c.name for c in recorder.CASES])
def test_corpus_parity(case: recorder.ParityCase) -> None:
    recorder.verify_case(case)


@requires_verify_mode
def test_generated_files_fresh() -> None:
    recorder.verify_generated_files_fresh()
