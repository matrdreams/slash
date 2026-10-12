"""Docker Engine backend driven by the docker CLI (same arguments as the Engine API).

`docker create` is used so slashd, not a restart policy, owns the container lifecycle.
The publish address is always 127.0.0.1.
"""

from collections.abc import Awaitable, Callable
from pathlib import Path

from slash.core.errors import SlashError
from slash.core.models import DeviceRuntimeState
from slash.devices.adb import run_cmd_bytes
from slash.devices.specs import DeviceSpec, boot_args, publish_spec

Runner = Callable[[list[str], float | None], Awaitable[tuple[int, bytes, bytes]]]


def docker_create_args(spec: DeviceSpec) -> list[str]:
    publish = publish_spec(spec.adb_port)
    if not publish.startswith("127.0.0.1:"):
        raise SlashError(f"refusing to publish ADB on {publish}")
    args = [
        "docker",
        "create",
        "--name",
        spec.container_name(),
        "--privileged",
        "--restart",
        "no",
        "--memory",
        spec.mem,
        "--cpus",
        str(spec.cpus),
        "-v",
        f"{spec.data_path}:/data",
        "-p",
        publish,
        "--network",
        f"slash-net-{spec.name}",
    ]
    mounts = {
        0: "/dev/binder",
        1: "/dev/hwbinder",
        2: "/dev/vndbinder",
    }
    for index, node in enumerate(spec.binder_devices):
        target = mounts.get(index, f"/dev/binder{index}")
        args.extend(["-v", f"{node}:{target}"])
    args.append(spec.image)
    args.extend(boot_args(spec))
    return args


class DockerRedroidBackend:
    def __init__(self, runner: Runner | None = None) -> None:
        self.runner = runner or run_cmd_bytes
        self.specs: dict[str, DeviceSpec] = {}

    def _require(self, device_id: str) -> DeviceSpec:
        spec = self.specs.get(device_id)
        if spec is None:
            raise SlashError(f"docker device {device_id} is not registered")
        return spec

    async def _run(self, args: list[str], *, ok_if: str | None = None) -> str:
        code, out, err = await self.runner(args, 180)
        text = (out + err).decode(errors="replace")
        if code != 0 and not (ok_if and ok_if in text.lower()):
            raise SlashError(text.strip() or f"command failed: {' '.join(args)}")
        return text

    async def ensure_spec(self, spec: DeviceSpec) -> None:
        self.specs[spec.id] = spec

    async def create(self, spec: DeviceSpec) -> str:
        await self.ensure_spec(spec)
        Path(spec.data_path).mkdir(parents=True, exist_ok=True)
        await self._run(
            ["docker", "network", "create", f"slash-net-{spec.name}"],
            ok_if="already exists",
        )
        await self._run(docker_create_args(spec))
        return spec.container_name()

    async def start(self, device_id: str) -> None:
        spec = self._require(device_id)
        await self._run(["docker", "start", spec.container_name()])

    async def stop(self, device_id: str, sync: bool = True) -> None:
        spec = self._require(device_id)
        await self._run(["docker", "stop", spec.container_name()])

    async def delete(self, device_id: str, keep_data: bool = True) -> None:
        spec = self._require(device_id)
        await self._run(["docker", "rm", "-f", spec.container_name()])
        await self._run(
            ["docker", "network", "rm", f"slash-net-{spec.name}"],
            ok_if="not found",
        )
        self.specs.pop(device_id, None)
        if not keep_data:
            path = Path(spec.data_path)
            if path.exists():
                import shutil

                shutil.rmtree(path)

    async def status(self, device_id: str) -> DeviceRuntimeState:
        spec = self._require(device_id)
        code, out, err = await self.runner(
            [
                "docker",
                "inspect",
                "-f",
                "{{.State.Status}} {{.State.OOMKilled}}",
                spec.container_name(),
            ],
            30,
        )
        if code != 0:
            return DeviceRuntimeState(state="STOPPED", running=False, detail=err.decode(errors="replace"))
        parts = out.decode(errors="replace").strip().split()
        status = parts[0] if parts else "unknown"
        oom = len(parts) > 1 and parts[1].lower() == "true"
        running = status == "running"
        return DeviceRuntimeState(
            state="RUNNING" if running else "STOPPED",
            running=running,
            oom=oom,
            detail=status,
        )

    async def adb_serial(self, device_id: str) -> str:
        return self._require(device_id).adb_serial()

    async def logs(self, device_id: str, tail: int = 200) -> str:
        spec = self._require(device_id)
        return await self._run(["docker", "logs", "--tail", str(tail), spec.container_name()])
