"""真实只读契约测试入口；默认不会在普通 pytest 中访问 B 站。"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("BILI_RUN_LIVE_READ_TESTS") != "I_UNDERSTAND",
    reason="live contract tests require explicit opt-in",
)


def test_live_read_contracts_are_manual_only():
    pytest.skip("run this test with the dedicated authenticated browser harness")

