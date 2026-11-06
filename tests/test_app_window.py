"""앱 창 종료 판단: 브라우저 프로세스가 바로 끝나도(기존 프로세스에 창을 넘김) 화면 신호가 있으면 계속 실행."""
import threading
import time

from seomu.app import wait_for_window


class Proc:
    def __init__(self, alive: bool):
        self.alive = alive

    def poll(self):
        return None if self.alive else 0


def _run(proc, last_seen, **kw):
    done = threading.Event()
    t = threading.Thread(target=lambda: (wait_for_window(proc, last_seen, time.time(), tick=0.01, **kw), done.set()),
                         daemon=True)
    t.start()
    return done


def test_handoff_keeps_running_while_heartbeats_arrive():
    beat = [time.time()]
    done = _run(Proc(False), lambda: beat[0], first_wait=0.2, idle=0.3)
    for _ in range(10):                      # 1초 동안 신호가 계속 온다 → 서버 유지
        time.sleep(0.1)
        beat[0] = time.time()
        assert not done.is_set()
    assert done.wait(2)                      # 신호가 끊기면 종료


def test_waits_for_first_heartbeat_then_gives_up():
    done = _run(Proc(False), lambda: 0.0, first_wait=0.3, idle=0.3)
    assert not done.wait(0.15)               # 창이 뜨는 동안은 기다린다
    assert done.wait(2)                      # 끝내 신호가 없으면 종료


def test_alive_process_keeps_running():
    p = Proc(True)
    done = _run(p, lambda: 0.0, first_wait=0.1, idle=0.1)
    assert not done.wait(0.4)
    p.alive = False
    assert done.wait(2)


def test_api_heartbeat():
    from seomu.api import Api
    import tempfile
    a = Api(tempfile.mkdtemp())
    assert a.last_heartbeat() == 0.0 and a.heartbeat() and time.time() - a.last_heartbeat() < 1
    a.shutdown()
