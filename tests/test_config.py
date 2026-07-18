"""환경 설정(.env) 로더 테스트."""

import os

from onjeon.config import load_env


class TestLoadEnv:
    def test_reads_env_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ONJEON_TEST_VAR", raising=False)
        env_file = tmp_path / ".env"
        env_file.write_text("ONJEON_TEST_VAR=hello\n", encoding="utf-8")
        assert load_env(env_file) is True
        assert os.environ.get("ONJEON_TEST_VAR") == "hello"
        monkeypatch.delenv("ONJEON_TEST_VAR", raising=False)

    def test_missing_file_returns_false_without_crash(self, tmp_path):
        assert load_env(tmp_path / "no-such.env") is False

    def test_does_not_override_existing_env(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ONJEON_TEST_VAR", "original")
        env_file = tmp_path / ".env"
        env_file.write_text("ONJEON_TEST_VAR=overwritten\n", encoding="utf-8")
        load_env(env_file)
        assert os.environ["ONJEON_TEST_VAR"] == "original"
