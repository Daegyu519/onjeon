from onjeon.device import resolve_device


def test_returns_cpu_when_torch_absent(monkeypatch):
    # torch import를 막아 미설치 환경을 모사
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "torch":
            raise ImportError("no torch")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert resolve_device() == "cpu"


def test_returns_mps_when_available(monkeypatch):
    import types
    torch = types.SimpleNamespace(
        backends=types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: True))
    )
    monkeypatch.setitem(__import__("sys").modules, "torch", torch)
    assert resolve_device() == "mps"
