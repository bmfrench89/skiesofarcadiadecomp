"""A pytest plugin under which a skipped test fails the run.

    PYTHONPATH=tools/citest python -m pytest -p noskip <modules>

CI's clang-cl leg (portability.md L4a) runs test_toolchain_fp.py and
test_gxr_fastpath.py, which skip, rightly, on a machine with no clang-cl, no
llvm-objdump or no SSE4.1. In that leg a skip would be a green tick for a
check that never ran, so the leg loads this, and each skip is named with its
reason and fails the run. Collection skips count as well as test skips.
"""

from __future__ import annotations

import pytest

_skipped: list[pytest.TestReport | pytest.CollectReport] = []


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if report.skipped:
        _skipped.append(report)


def pytest_collectreport(report: pytest.CollectReport) -> None:
    if report.skipped:
        _skipped.append(report)


def _reason(report: pytest.TestReport | pytest.CollectReport) -> str:
    longrepr = report.longrepr
    # A skip's longrepr is (path, line, "Skipped: why").
    return longrepr[2] if isinstance(longrepr, tuple) else str(longrepr)


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session) -> None:
    if not _skipped:
        return
    tr = session.config.pluginmanager.get_plugin("terminalreporter")
    if tr is not None:
        tr.write_line("")  # under -q the progress line is still open
    for report in _skipped:
        line = f"noskip: {report.nodeid}: {_reason(report)}"
        if tr is not None:
            tr.write_line(line, red=True)
        else:
            print(line)
    if tr is not None:
        tr.write_line(f"noskip: {len(_skipped)} skipped, and a skip fails this run", red=True)
    if session.exitstatus == pytest.ExitCode.OK:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
