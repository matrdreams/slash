import json
import subprocess
from pathlib import Path

import yaml
from typer.testing import CliRunner

from slash.cli.main import app
from slash.core.config import load_config
from tests.conftest import make_config

ROOT = Path(__file__).resolve().parents[2]
runner = CliRunner()


def test_example_config_parses():
    cfg = load_config(ROOT / "examples" / "config.example.yaml")
    assert cfg.devices.backend == "compose"
    assert cfg.devices.adb_port_base == 5600
    assert cfg.agent.max_steps == 40
    assert cfg.agent.mode == "tree+vision"
    assert cfg.llm.data_residency == "cn"
    assert cfg.llm.providers["qwen-vl"].region == "cn"
    assert cfg.devices.defaults.dns == ["223.5.5.5"]
    assert cfg.takeover.ttl_s == 300


def test_cli_help_and_fake_run(tmp_path):
    help_result = runner.invoke(app, ["--help"])
    assert help_result.exit_code == 0
    assert "serve" in help_result.stdout
    assert "run" in help_result.stdout
    device_help = runner.invoke(app, ["device", "--help"])
    assert device_help.exit_code == 0
    assert "create" in device_help.stdout
    devices_help = runner.invoke(app, ["devices", "--help"])
    assert devices_help.exit_code == 0

    config = make_config(
        tmp_path,
        actions=[
            {"type": "type", "text": "显示", "submit": False},
            {"type": "done", "success": True, "result": "ok"},
        ],
    )
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(config.model_dump(mode="json")), encoding="utf-8")
    created = runner.invoke(app, ["device", "create", "u1", "--config", str(path)])
    assert created.exit_code == 0, created.stdout + created.stderr
    body = json.loads(created.stdout)
    assert body["adb_serial"] == "127.0.0.1:5601"
    ran = runner.invoke(app, ["run", "u1", "打开设置并搜索显示", "--config", str(path)])
    assert ran.exit_code == 0, ran.stdout + ran.stderr
    payload = json.loads(ran.stdout)
    assert payload["status"] == "SUCCEEDED"
    assert payload["steps_used"] == 2


def test_host_scripts_are_executable_bash():
    for relative in (
        "host/install.sh",
        "host/check.sh",
        "dev/qemu/make-arm64-vm.sh",
        "dev/qemu/make-x86-vm.sh",
        "images/fetch-apks.sh",
        "deploy/proxy/iptables.sh",
    ):
        path = ROOT / relative
        syntax = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
        assert syntax.returncode == 0, syntax.stderr
    help_install = subprocess.run(["bash", str(ROOT / "host/install.sh"), "--help"], capture_output=True, text=True)
    assert help_install.returncode == 0
    assert "--no-docker" in help_install.stdout
    checked = subprocess.run(["bash", str(ROOT / "host/check.sh"), "--json"], capture_output=True, text=True)
    payload = json.loads(checked.stdout)
    for key in ("binder", "binderfs", "page_size", "docker", "adb", "arch", "issues"):
        assert key in payload
    assert isinstance(payload["issues"], list)
    assert isinstance(payload["page_size"], int)
    text = (ROOT / "dev/qemu/make-x86-vm.sh").read_text(encoding="utf-8")
    assert "accel=kvm" in text
    assert "/dev/kvm" in text
    arm = (ROOT / "dev/qemu/make-arm64-vm.sh").read_text(encoding="utf-8")
    assert "qemu-system-aarch64" in arm
    assert "-accel kvm -cpu host" in arm
