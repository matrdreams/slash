"""Build the process-wide objects the API and CLI share."""

import hashlib
import secrets
from dataclasses import dataclass
from pathlib import Path

import yaml

from slash.agent.actuator import Actuator
from slash.agent.loop import AgentRuntime
from slash.agent.observer import Observer
from slash.agent.planners.mobilerun import MobilerunPlanner
from slash.agent.planners.native import NativePlanner
from slash.core.config import SlashConfig
from slash.core.events import EventBus
from slash.core.metrics import Metrics
from slash.devices.adb import AdbClient
from slash.devices.backends.compose import ComposeBackend
from slash.devices.backends.docker_api import DockerRedroidBackend
from slash.devices.backends.fake import FakeBackend
from slash.devices.backends.k8s import K8sBackend
from slash.devices.certs import ApksignerVerifier
from slash.devices.fake_adb import FakeAdb
from slash.devices.health import HealthMonitor
from slash.devices.manager import DeviceManager
from slash.llm.registry import build_provider
from slash.store.blobstore import BlobStore
from slash.store.db import Store
from slash.takeover.recorder import Recorder
from slash.takeover.service import TakeoverService
from slash.takeover.tokens import TokenService


@dataclass
class AppContext:
    config: SlashConfig
    store: Store
    blobs: BlobStore
    backend: object
    adb: object
    manager: DeviceManager
    provider: object
    runtime: AgentRuntime
    takeover: TakeoverService
    health: HealthMonitor
    token: str
    secret: bytes
    metrics: Metrics
    bus: EventBus
    user_id: str
    inline_tasks: bool = False


def load_pins(path: str | None) -> dict[str, str]:
    if not path:
        return {}
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    pins: dict[str, str] = {}
    for entry in document.get("apps") or []:
        package = entry.get("package")
        cert = entry.get("cert_sha256")
        if package and cert:
            pins[str(package)] = str(cert)
    return pins


def _prepare_sqlite(url: str) -> None:
    if not url.startswith("sqlite"):
        return
    if ":memory:" in url:
        return
    raw = url.split("sqlite:///", 1)[-1]
    path = Path(raw)
    if str(path):
        path.parent.mkdir(parents=True, exist_ok=True)


def resolve_token(config: SlashConfig) -> str:
    if config.server.token:
        return config.server.token
    path = Path(config.storage.blob_dir).parent / "api.token"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    token = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token, encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return token


def resolve_secret(config: SlashConfig) -> bytes:
    if config.server.secret_key_file:
        file = Path(config.server.secret_key_file)
        if file.is_file():
            data = file.read_bytes().strip()
            if data:
                return data
    if config.server.secret:
        return config.server.secret.encode()
    path = Path(config.storage.blob_dir).parent / "secret"
    if path.is_file():
        return path.read_bytes().strip()
    secret = secrets.token_hex(32).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(secret)
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return secret


def make_backend(config: SlashConfig):
    kind = config.devices.backend
    if kind == "fake":
        return FakeBackend()
    if kind == "docker":
        return DockerRedroidBackend()
    if kind == "k8s":
        return K8sBackend()
    override = Path(config.devices.data_root) / "phones.override.yml"
    return ComposeBackend(override)


def build_context(
    config: SlashConfig,
    *,
    backend=None,
    adb=None,
    provider=None,
    cert_verifier=None,
    inline_tasks: bool = False,
    sleeper=None,
) -> AppContext:
    _prepare_sqlite(config.storage.db_url)
    store = Store(config.storage.db_url)
    store.init_db()
    blobs = BlobStore(config.storage.blob_dir)
    token = resolve_token(config)
    secret = resolve_secret(config)
    user = store.ensure_user(hashlib.sha256(token.encode()).hexdigest())
    bus = EventBus()
    metrics = Metrics()
    if backend is None:
        backend = make_backend(config)
    if adb is None:
        adb = FakeAdb() if config.devices.backend == "fake" else AdbClient()
    if provider is None:
        provider = build_provider(config.llm)
    pins = load_pins(config.devices.apps_registry)
    manager = DeviceManager(
        config,
        store,
        backend,
        adb,
        bus=bus,
        metrics=metrics,
        cert_verifier=cert_verifier if cert_verifier is not None else ApksignerVerifier(),
        pins=pins,
        sleeper=sleeper,
    )
    observer = Observer(
        adb,
        long_edge=config.agent.screenshot_long_edge,
        tree_limit=config.agent.tree_max_nodes,
    )
    actuator = Actuator(adb, sleeper=sleeper)
    planner_cls = MobilerunPlanner if config.agent.planner == "mobilerun" else NativePlanner
    planner = planner_cls(provider, mode=config.agent.mode)
    tokens = TokenService(secret, ttl_s=config.takeover.ttl_s)
    recorder = Recorder(adb)
    takeover = TakeoverService(
        config=config.takeover,
        public_base_url=config.server.public_base_url,
        tokens=tokens,
        store=store,
        blobs=blobs,
        recorder=recorder,
        record=config.takeover.record,
    )
    runtime = AgentRuntime(
        store=store,
        blobs=blobs,
        manager=manager,
        observer=observer,
        actuator=actuator,
        planner=planner,
        takeover=takeover,
        bus=bus,
        metrics=metrics,
    )
    health = HealthMonitor(manager, adb, bus=bus)
    return AppContext(
        config=config,
        store=store,
        blobs=blobs,
        backend=backend,
        adb=adb,
        manager=manager,
        provider=provider,
        runtime=runtime,
        takeover=takeover,
        health=health,
        token=token,
        secret=secret,
        metrics=metrics,
        bus=bus,
        user_id=user.id,
        inline_tasks=inline_tasks,
    )
