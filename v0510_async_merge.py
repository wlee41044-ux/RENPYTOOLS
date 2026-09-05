#!/usr/bin/env python3
import threading
import time
from pathlib import Path


def run_async(owner, work, done, *, name="renpytools-merge"):
    """Run heavy merge/patch work off Tk's main thread, then marshal result back."""
    def worker():
        try:
            result = work()
            error = None
        except Exception as exc:
            result = None
            error = exc
        try:
            owner.after(0, lambda: done(result, error))
        except Exception:
            pass

    thread = threading.Thread(target=worker, daemon=True, name=name)
    thread.start()
    return thread


def distribution_hint(exe_path):
    exe = Path(exe_path)
    return (
        f"배포용 파일: {exe.name}\n"
        "이 EXE를 게임 폴더(game 폴더가 들어있는 위치)에 두고 실행하면 자동으로 패치됩니다.\n"
        "다른 위치에서 실행하면 Ren'Py 게임 폴더를 한 번 선택하면 됩니다."
    )


def run_v0510_self_test():
    try:
        called = {"worker_thread": None, "done": False}
        event = threading.Event()
        main_ident = threading.get_ident()

        class FakeOwner:
            def after(self, _delay, callback):
                callback()

        def work():
            called["worker_thread"] = threading.get_ident()
            time.sleep(0.01)
            return 123

        def done(result, error):
            assert error is None
            assert result == 123
            called["done"] = True
            event.set()

        thread = run_async(FakeOwner(), work, done)
        thread.join(2)
        assert event.wait(1)
        assert called["done"]
        assert called["worker_thread"] != main_ident
        hint = distribution_hint("TreeTL.exe")
        assert "TreeTL.exe" in hint and "실행하면 자동으로 패치" in hint
        return 0
    except Exception as exc:
        try:
            Path("RenPyTools-v0510-selftest-error.txt").write_text(repr(exc), encoding="utf-8")
        except Exception:
            pass
        return 1
