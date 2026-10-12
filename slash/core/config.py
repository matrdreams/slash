"""Load slash config.yaml into pydantic models. Model names stay in the file."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class ServerConfig(BaseModel):
    bind: str = "127.0.0.1:8787"
    public_base_url: str = "http://127.0.0.1:8787"
    secret_key_file: str | None = None
    # Local single-user token. When empty, the process persists a generated token.
    token: str | None = None
    # Optional raw HMAC secret. secret_key_file wins when the file exists.
    secret: str | None = None


class StorageConfig(BaseModel):
    db_url: str = "sqlite:///./slash.db"
    blob_dir: str = "./blobs"
    retention_days: int = 7


class DeviceDefaults(BaseModel):
    width: int = 720
    height: int = 1280
    dpi: int = 320
    fps: int = 15
    gpu_mode: str = "guest"
    mem: str = "3g"
    cpus: float = 2
    dns: list[str] = Field(default_factory=lambda: ["223.5.5.5"])
    use_memfd: bool = True


class DevicesConfig(BaseModel):
    backend: Literal["compose", "docker", "k8s", "fake", "physical"] = "compose"
    data_root: str = "/srv/slash/devices"
    default_image: str = "redroid/redroid:12.0.0-latest"
    adb_port_base: int = 5600
    idle_timeout_min: int = 30
    boot_timeout_s: int = 90
    reaper_interval_s: int = 30
    defaults: DeviceDefaults = Field(default_factory=DeviceDefaults)
    # Debian hosts bind /dev/binderN. Leave empty on Ubuntu binderfs.
    binder_devices: list[str] = Field(default_factory=list)
    # physical backend: device name -> adb serial (USB or an existing forward).
    serials: dict[str, str] = Field(default_factory=dict)
    apps_registry: str | None = None


class AgentConfig(BaseModel):
    planner: Literal["native", "mobilerun"] = "native"
    mode: Literal["tree", "tree+vision", "vision-only"] = "tree+vision"
    max_steps: int = 40
    screenshot_long_edge: int = 1024
    confirm_sensitive: bool = True
    tree_max_nodes: int = 80
    watchers_file: str | None = None
    # Midscene worker (worker/). "fake" uses the in-process scripted client.
    worker_url: str = "http://127.0.0.1:18790"
    # With the fake device backend the fake worker is used unless this is true.
    worker_url_explicit: bool = False
    worker_poll_s: float = 1.0


class ProviderConfig(BaseModel):
    kind: str
    base_url: str = ""
    model: str = ""
    api_key_env: str = ""
    region: Literal["cn", "local", "global"] = "local"
    vision: bool = False
    coord_space: Literal["pixel", "norm1000", "norm1"] = "pixel"
    price_prompt_per_1k: float = 0.0
    price_completion_per_1k: float = 0.0
    price_image: float = 0.0
    # Scripted provider only. Each item is one action JSON object, in order.
    script: list[dict] = Field(default_factory=list)


class LLMConfig(BaseModel):
    default: str = "qwen-vl"
    data_residency: Literal["cn", "any"] = "cn"
    max_cost_cny: float | None = None
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)


class TakeoverConfig(BaseModel):
    ttl_s: int = 300
    record: bool = True
    ws_scrcpy_upstream: str = "http://127.0.0.1:8000"


class SlashConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    devices: DevicesConfig = Field(default_factory=DevicesConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    takeover: TakeoverConfig = Field(default_factory=TakeoverConfig)


def load_config(path: str | Path) -> SlashConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"config {path} must be a mapping")
    return SlashConfig.model_validate(raw)


def parse_bind(bind: str) -> tuple[str, int]:
    host, _, port = bind.rpartition(":")
    if not host or not port:
        raise ValueError(f"bind must look like host:port, got {bind!r}")
    return host, int(port)
