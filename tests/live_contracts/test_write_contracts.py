"""写接口只做安全门测试，不包含任何真实写请求。"""

import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("BILI_LIVE_WRITE_TEST") != "I_UNDERSTAND",
    reason="write contract tests require explicit opt-in",
)


def test_write_contracts_require_allowlist():
    pytest.skip("a separately reviewed allowlist harness is required")

