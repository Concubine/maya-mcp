"""Test-wide fixtures.

The only one so far exists because the suite was writing into the user's real
log directory: `test_plugin_e2e` starts real plugin servers, and every
`start_server()` calls `_setup_logging()`.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def _logs_go_to_a_temp_dir(tmp_path_factory):
    """Point MAYA_MCP_LOG_DIR at a temp directory for the whole session.

    Before #650 every test process appended to one shared `~/.maya-mcp/logs/
    plugin.log`, so a test run was indistinguishable from a Maya session in the
    file you read to debug Maya. Per-process files made that worse rather than
    better: each pytest process would leave its own `plugin-<pid>.log`, and
    since `logsetup.configure` prunes to the newest few sessions, running the
    suite a handful of times would evict the logs of the real Maya sessions
    somebody was trying to diagnose. Tests get their own directory.
    """
    previous = os.environ.get("MAYA_MCP_LOG_DIR")
    os.environ["MAYA_MCP_LOG_DIR"] = str(tmp_path_factory.mktemp("maya_mcp_logs"))
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("MAYA_MCP_LOG_DIR", None)
        else:
            os.environ["MAYA_MCP_LOG_DIR"] = previous
