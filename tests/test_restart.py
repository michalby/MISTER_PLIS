"""Restarting the server on each system (docs/PREP_PLAN.md R2), and waiting for the port at start."""

import socket
import threading
import time

import pytest

from mister_plis import updater
from mister_plis.__main__ import wait_for_port


class Exited(Exception):
    pass


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def _exit(code):
        seen.append(("exit", code))
        raise Exited  # os._exit would end the test run

    monkeypatch.setattr(updater.os, "_exit", _exit)
    monkeypatch.setattr(updater.os, "execv", lambda exe, argv: seen.append(("execv", argv)))
    monkeypatch.setattr(updater.os, "chdir", lambda p: None)
    monkeypatch.setattr(updater.subprocess, "Popen", lambda argv, **kw: seen.append(("popen", argv)))
    monkeypatch.delenv("MISTER_PLIS_SUPERVISED", raising=False)
    return seen


def test_a_supervised_server_exits_for_its_supervisor(monkeypatch, calls):
    monkeypatch.setenv("MISTER_PLIS_SUPERVISED", "1")
    with pytest.raises(Exited):
        updater._restart_now()
    assert calls == [("exit", updater.RESTART_EXIT_CODE)] and updater.RESTART_EXIT_CODE == 75


def test_on_windows_a_new_process_is_started(monkeypatch, calls):
    monkeypatch.setattr(updater, "_on_windows", lambda: True)
    with pytest.raises(Exited):
        updater._restart_now()
    assert [c[0] for c in calls] == ["popen", "exit"]
    assert calls[0][1][1:3] == ["-m", "mister_plis"] and calls[1] == ("exit", 0)


def test_elsewhere_the_process_is_replaced(monkeypatch, calls):
    monkeypatch.setattr(updater, "_on_windows", lambda: False)
    updater._restart_now()
    assert len(calls) == 1 and calls[0][0] == "execv" and calls[0][1][1:3] == ["-m", "mister_plis"]


def test_schedule_restart(monkeypatch):
    done = threading.Event()
    monkeypatch.setattr(updater, "_restart_now", done.set)
    monkeypatch.setenv("MISTER_PLIS_DEV_RELOAD", "1")
    assert updater.schedule_restart(0) is False  # the dev server reloads itself
    monkeypatch.delenv("MISTER_PLIS_DEV_RELOAD")
    assert updater.schedule_restart(0) is True and done.wait(5)


def _listening() -> tuple[socket.socket, int]:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    s.listen()
    return s, s.getsockname()[1]


def test_wait_for_port():
    s, port = _listening()
    try:
        t = time.monotonic()
        assert wait_for_port("127.0.0.1", port, seconds=0.5) is False  # still taken
        assert time.monotonic() - t >= 0.5
    finally:
        s.close()
    assert wait_for_port("127.0.0.1", port, seconds=5) is True


def test_wait_for_port_waits_for_the_old_server():
    s, port = _listening()
    threading.Timer(0.5, s.close).start()
    assert wait_for_port("127.0.0.1", port, seconds=10) is True
