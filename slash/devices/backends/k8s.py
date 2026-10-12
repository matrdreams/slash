"""Kubernetes backend (M4 surface). Renders a privileged StatefulSet + ClusterIP Service.

`kubectl` is invoked only when an operation runs. Unit tests call `render_manifest`
and never need a cluster. kind cannot load binder_linux; this backend does not pretend it can.
"""

from collections.abc import Awaitable, Callable

import tempfile
from pathlib import Path

import yaml

from slash.core.errors import SlashError
from slash.core.models import DeviceRuntimeState
from slash.devices.adb import run_cmd_bytes
from slash.devices.specs import DeviceSpec, boot_args

Runner = Callable[[list[str], float | None], Awaitable[tuple[int, bytes, bytes]]]


def render_manifest(spec: DeviceSpec) -> dict:
    name = spec.service_name()
    return {
        "statefulset": {
            "apiVersion": "apps/v1",
            "kind": "StatefulSet",
            "metadata": {"name": name, "labels": {"app": "slash-phone", "slash.dev/device": spec.name}},
            "spec": {
                "serviceName": name,
                "replicas": 1,
                "selector": {"matchLabels": {"app": "slash-phone", "slash.dev/device": spec.name}},
                "template": {
                    "metadata": {"labels": {"app": "slash-phone", "slash.dev/device": spec.name}},
                    "spec": {
                        "nodeSelector": {"slash.dev/binder": "true"},
                        "containers": [
                            {
                                "name": "redroid",
                                "image": spec.image,
                                "securityContext": {"privileged": True},
                                "args": boot_args(spec),
                                "ports": [{"name": "adb", "containerPort": 5555}],
                                "volumeMounts": [{"name": "data", "mountPath": "/data"}],
                            }
                        ],
                    },
                },
                "volumeClaimTemplates": [
                    {
                        "metadata": {"name": "data"},
                        "spec": {
                            "accessModes": ["ReadWriteOnce"],
                            "resources": {"requests": {"storage": "16Gi"}},
                        },
                    }
                ],
            },
        },
        "service": {
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {"name": name},
            "spec": {
                "type": "ClusterIP",
                "selector": {"app": "slash-phone", "slash.dev/device": spec.name},
                "ports": [{"name": "adb", "port": 5555, "targetPort": "adb"}],
            },
        },
    }


class K8sBackend:
    def __init__(self, namespace: str = "slash", runner: Runner | None = None) -> None:
        self.namespace = namespace
        self.runner = runner or run_cmd_bytes
        self.specs: dict[str, DeviceSpec] = {}

    def _require(self, device_id: str) -> DeviceSpec:
        spec = self.specs.get(device_id)
        if spec is None:
            raise SlashError(f"k8s device {device_id} is not registered")
        return spec

    async def _kubectl(self, args: list[str]) -> str:
        code, out, err = await self.runner(["kubectl", "-n", self.namespace, *args], 180)
        text = (out + err).decode(errors="replace")
        if code != 0:
            raise SlashError(text.strip() or "kubectl failed")
        return text

    async def _apply(self, spec: DeviceSpec) -> None:
        manifest = render_manifest(spec)
        payload = yaml.safe_dump_all([manifest["statefulset"], manifest["service"]])
        directory = Path(tempfile.mkdtemp(prefix="slash-k8s-"))
        path = directory / f"{spec.service_name()}.yaml"
        path.write_text(payload, encoding="utf-8")
        await self._kubectl(["apply", "-f", str(path)])

    async def ensure_spec(self, spec: DeviceSpec) -> None:
        self.specs[spec.id] = spec

    async def create(self, spec: DeviceSpec) -> str:
        await self.ensure_spec(spec)
        await self._apply(spec)
        # Scale to 0 so create does not boot until start().
        await self._kubectl(["scale", f"statefulset/{spec.service_name()}", "--replicas=0"])
        return spec.service_name()

    async def start(self, device_id: str) -> None:
        spec = self._require(device_id)
        await self._kubectl(["scale", f"statefulset/{spec.service_name()}", "--replicas=1"])

    async def stop(self, device_id: str, sync: bool = True) -> None:
        spec = self._require(device_id)
        await self._kubectl(["scale", f"statefulset/{spec.service_name()}", "--replicas=0"])

    async def delete(self, device_id: str, keep_data: bool = True) -> None:
        spec = self._require(device_id)
        await self._kubectl(["delete", "statefulset", spec.service_name(), "--ignore-not-found"])
        await self._kubectl(["delete", "service", spec.service_name(), "--ignore-not-found"])
        if not keep_data:
            await self._kubectl(["delete", "pvc", "-l", f"slash.dev/device={spec.name}", "--ignore-not-found"])
        self.specs.pop(device_id, None)

    async def status(self, device_id: str) -> DeviceRuntimeState:
        spec = self._require(device_id)
        text = await self._kubectl(
            ["get", "pods", "-l", f"slash.dev/device={spec.name}", "-o", "jsonpath={.items[0].status.phase}"]
        )
        running = "Running" in text
        return DeviceRuntimeState(state="RUNNING" if running else "STOPPED", running=running, detail=text.strip())

    async def adb_serial(self, device_id: str) -> str:
        # In-cluster the Service is ClusterIP. The serial is the service DNS name,
        # not a public address. Host-side adb uses `kubectl port-forward` separately.
        spec = self._require(device_id)
        return f"{spec.service_name()}.{self.namespace}.svc:5555"

    async def logs(self, device_id: str, tail: int = 200) -> str:
        spec = self._require(device_id)
        return await self._kubectl(["logs", f"statefulset/{spec.service_name()}", f"--tail={tail}"])
