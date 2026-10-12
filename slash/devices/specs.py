"""Device spec shared by the compose, docker, and k8s backends."""

import re
from typing import Any

from pydantic import BaseModel, Field

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def validate_device_name(name: str) -> str:
    if not _NAME.fullmatch(name):
        raise ValueError(
            "device name must match [A-Za-z0-9][A-Za-z0-9_.-]{0,63}"
        )
    return name


def parse_resolution(value: str) -> tuple[int, int]:
    parts = value.lower().split("x")
    if len(parts) != 2:
        raise ValueError(f"resolution must look like 720x1280, got {value!r}")
    return int(parts[0]), int(parts[1])


def parse_mem_mb(mem: str) -> int:
    text = mem.strip().lower()
    if text.endswith("g"):
        return int(float(text[:-1]) * 1024)
    if text.endswith("m"):
        return int(float(text[:-1]))
    return int(text)


class DeviceSpec(BaseModel):
    id: str
    name: str
    image: str
    android: str = "12"
    width: int = 720
    height: int = 1280
    dpi: int = 320
    fps: int = 15
    gpu_mode: str = "guest"
    mem: str = "3g"
    cpus: float = 2
    dns: list[str] = Field(default_factory=lambda: ["223.5.5.5"])
    use_memfd: bool = True
    adb_port: int
    data_path: str
    proxy: str | None = None
    binder_devices: list[str] = Field(default_factory=list)
    overlayfs: bool = False
    extra_props: dict[str, str] = Field(default_factory=dict)
    seq: int = 0

    def adb_serial(self) -> str:
        return f"127.0.0.1:{self.adb_port}"

    def container_name(self) -> str:
        return f"slash-phone-{self.name}"

    def service_name(self) -> str:
        return f"phone-{self.name}"


def boot_args(spec: DeviceSpec) -> list[str]:
    """Redroid androidboot.* arguments. ADB publish address is not one of them."""
    args = [
        f"androidboot.redroid_width={spec.width}",
        f"androidboot.redroid_height={spec.height}",
        f"androidboot.redroid_dpi={spec.dpi}",
        f"androidboot.redroid_fps={spec.fps}",
        f"androidboot.redroid_gpu_mode={spec.gpu_mode}",
        f"androidboot.redroid_net_ndns={len(spec.dns)}",
    ]
    for index, dns in enumerate(spec.dns, start=1):
        args.append(f"androidboot.redroid_net_dns{index}={dns}")
    if spec.use_memfd:
        args.append("androidboot.use_memfd=true")
    if spec.overlayfs:
        args.append("androidboot.use_redroid_overlayfs=1")
    if spec.proxy:
        host, port = spec.proxy.rsplit(":", 1)
        args.append("androidboot.redroid_net_proxy_type=static")
        args.append(f"androidboot.redroid_net_proxy_host={host}")
        args.append(f"androidboot.redroid_net_proxy_port={port}")
    for key, value in spec.extra_props.items():
        args.append(f"{key}={value}")
    return args


def publish_spec(port: int) -> str:
    """Host publish string. Always loopback. Never 0.0.0.0."""
    return f"127.0.0.1:{port}:5555"


def service_dict(spec: DeviceSpec) -> dict[str, Any]:
    volumes = [f"{spec.data_path}:/data"]
    # Debian-style per-instance binder nodes. binderfs hosts leave this empty.
    binder_mounts = {
        "binder": "/dev/binder",
        "hwbinder": "/dev/hwbinder",
        "vndbinder": "/dev/vndbinder",
    }
    for index, node in enumerate(spec.binder_devices):
        target = list(binder_mounts.values())[index] if index < 3 else f"/dev/binder{index}"
        volumes.append(f"{node}:{target}")
    return {
        "image": spec.image,
        "privileged": True,
        "volumes": volumes,
        "ports": [publish_spec(spec.adb_port)],
        "mem_limit": spec.mem,
        "cpus": spec.cpus,
        "networks": [f"net-{spec.name}"],
        "restart": "no",
        "command": boot_args(spec),
    }
