"""Shared fixtures. Every test here is L0: no docker, no adb, no network."""

from pathlib import Path

import pytest

from slash.core.config import (
    AgentConfig,
    DevicesConfig,
    LLMConfig,
    ProviderConfig,
    ServerConfig,
    SlashConfig,
    StorageConfig,
    TakeoverConfig,
)
from slash.devices.backends.fake import FakeBackend
from slash.devices.fake_adb import FakeAdb
from slash.wiring import build_context


class FakeCerts:
    def __init__(self, fingerprint: str = "abcd") -> None:
        self.fingerprint_value = fingerprint
        self.calls = 0

    def fingerprint(self, apk: Path) -> str:
        self.calls += 1
        return self.fingerprint_value


def make_config(tmp_path: Path, *, actions: list[dict] | None = None, **kwargs) -> SlashConfig:
    script = actions if actions is not None else [{"type": "done", "success": True, "result": "ok"}]
    return SlashConfig(
        server=ServerConfig(
            bind="127.0.0.1:8787",
            public_base_url="http://127.0.0.1:8787",
            token="test-token",
            secret="test-secret",
        ),
        storage=StorageConfig(
            db_url=f"sqlite:///{tmp_path / 'slash.db'}",
            blob_dir=str(tmp_path / "blobs"),
            retention_days=7,
        ),
        devices=DevicesConfig(
            backend="fake",
            data_root=str(tmp_path / "devices"),
            idle_timeout_min=kwargs.get("idle_timeout_min", 30),
            boot_timeout_s=kwargs.get("boot_timeout_s", 5),
        ),
        agent=AgentConfig(
            planner="native",
            mode=kwargs.get("mode", "tree"),
            max_steps=kwargs.get("max_steps", 8),
            confirm_sensitive=kwargs.get("confirm_sensitive", True),
        ),
        llm=LLMConfig(
            default="fake",
            data_residency="any",
            max_cost_cny=kwargs.get("max_cost_cny"),
            providers={
                "fake": ProviderConfig(
                    kind="scripted",
                    region="local",
                    vision=kwargs.get("vision", False),
                    coord_space=kwargs.get("coord_space", "pixel"),
                    script=script,
                )
            },
        ),
        takeover=TakeoverConfig(ttl_s=kwargs.get("ttl_s", 300), record=kwargs.get("record", False)),
    )


@pytest.fixture
def world(tmp_path: Path):
    def _build(actions: list[dict] | None = None, adb: FakeAdb | None = None, **kwargs):
        adb = adb or FakeAdb()
        verifier = kwargs.pop("verifier", FakeCerts())
        config = make_config(tmp_path, actions=actions, **kwargs)
        ctx = build_context(
            config,
            backend=FakeBackend(),
            adb=adb,
            cert_verifier=verifier,
            inline_tasks=True,
            sleeper=_instant,
        )
        ctx.verifier = verifier  # type: ignore[attr-defined]
        return ctx

    return _build


async def _instant(_seconds: float) -> None:
    return None
