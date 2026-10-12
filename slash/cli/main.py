"""slash CLI: device lifecycle, `run`, and `serve`."""

import asyncio
import json
from pathlib import Path

import typer

from slash import __version__
from slash.core.config import load_config, parse_bind
from slash.core.models import DeviceCreate, TaskStatus
from slash.store.ids import new_id
from slash.store.tables import TaskRow
from slash.wiring import build_context

app = typer.Typer(no_args_is_help=True, help="Control Redroid devices and run GUI tasks.")
device_app = typer.Typer(no_args_is_help=True, help="Manage Redroid devices.")
devices_app = typer.Typer(no_args_is_help=True, help="Alias of `slash device`.")


def _context(config: Path | None):
    if config is None:
        raise typer.BadParameter("pass --config or set SLASH_CONFIG")
    return build_context(load_config(config), inline_tasks=True)


def _device_row(ctx, name_or_id: str):
    row = ctx.store.get_device(name_or_id) or ctx.store.get_device_by_name(name_or_id)
    if row is None:
        raise typer.BadParameter(f"device {name_or_id} not found")
    return row


def _list(config: Path | None) -> None:
    state = _context(config)
    devices = asyncio.run(state.manager.list_devices())
    typer.echo(json.dumps([item.model_dump() for item in devices], default=str))


def _create(
    name: str,
    config: Path | None,
    image: str | None,
    resolution: str | None,
    mem: str | None,
    cpus: float | None,
) -> None:
    state = _context(config)
    created = asyncio.run(
        state.manager.create(
            DeviceCreate(name=name, image=image, resolution=resolution, mem=mem, cpus=cpus),
            user_id=state.user_id,
        )
    )
    typer.echo(created.model_dump_json())


def _start(name: str, config: Path | None) -> None:
    state = _context(config)
    row = _device_row(state, name)
    try:
        started = asyncio.run(state.manager.ensure_running(row.id))
    except Exception as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(started.model_dump_json())


def _stop(name: str, config: Path | None) -> None:
    state = _context(config)
    row = _device_row(state, name)
    stopped = asyncio.run(state.manager.stop(row.id))
    typer.echo(stopped.model_dump_json())


def _delete(name: str, config: Path | None, keep_data: bool) -> None:
    state = _context(config)
    row = _device_row(state, name)
    asyncio.run(state.manager.delete(row.id, keep_data=keep_data))
    typer.echo(json.dumps({"deleted": row.id, "keep_data": keep_data}))


def _snapshot(name: str, config: Path | None, note: str) -> None:
    state = _context(config)
    row = _device_row(state, name)
    snap = asyncio.run(state.manager.snapshot(row.id, note=note))
    typer.echo(json.dumps({"id": snap.id, "path": snap.path, "size_bytes": snap.size_bytes}))


def _register(group: typer.Typer) -> None:
    config_opt = typer.Option(None, "--config", "-c", envvar="SLASH_CONFIG")

    @group.command("list")
    def list_devices(config: Path | None = config_opt) -> None:
        _list(config)

    @group.command("create")
    def create_device(
        name: str,
        config: Path | None = config_opt,
        image: str | None = None,
        resolution: str | None = None,
        mem: str | None = None,
        cpus: float | None = None,
    ) -> None:
        _create(name, config, image, resolution, mem, cpus)

    @group.command("start")
    def start_device(name: str, config: Path | None = config_opt) -> None:
        _start(name, config)

    @group.command("stop")
    def stop_device(name: str, config: Path | None = config_opt) -> None:
        _stop(name, config)

    @group.command("delete")
    def delete_device(
        name: str,
        config: Path | None = config_opt,
        keep_data: bool = True,
    ) -> None:
        _delete(name, config, keep_data)

    @group.command("snapshot")
    def snapshot_device(
        name: str,
        config: Path | None = config_opt,
        note: str = "",
    ) -> None:
        _snapshot(name, config, note)


_register(device_app)
_register(devices_app)
app.add_typer(device_app, name="device")
app.add_typer(devices_app, name="devices")


@app.command()
def run(
    device: str,
    goal: str,
    config: Path | None = typer.Option(None, "--config", "-c", envvar="SLASH_CONFIG"),
    max_steps: int | None = None,
    mode: str | None = None,
) -> None:
    """Run one natural-language goal on a device."""
    state = _context(config)
    row = _device_row(state, device)
    task = state.store.insert_task(
        TaskRow(
            id=new_id(),
            device_id=row.id,
            goal=goal,
            mode=mode or state.config.agent.mode,
            provider=state.config.llm.default,
            status=TaskStatus.PENDING.value,
            max_steps=max_steps or state.config.agent.max_steps,
            require_confirm=state.config.agent.confirm_sensitive,
            max_cost_cny=state.config.llm.max_cost_cny,
        )
    )
    finished = asyncio.run(state.runtime.run(task.id))
    payload = {
        "id": finished.id,
        "status": finished.status,
        "result": finished.result_json,
        "error": finished.error,
        "steps_used": finished.steps_used,
        "takeover_url": finished.takeover_url,
    }
    typer.echo(json.dumps(payload, ensure_ascii=False))
    if finished.status == TaskStatus.SUCCEEDED.value:
        raise typer.Exit(code=0)
    if finished.status == TaskStatus.NEED_HUMAN.value:
        raise typer.Exit(code=2)
    raise typer.Exit(code=1)


@app.command()
def serve(
    config: Path | None = typer.Option(None, "--config", "-c", envvar="SLASH_CONFIG"),
    host: str | None = None,
    port: int | None = None,
) -> None:
    """Serve the control-plane API."""
    import uvicorn

    from slash.api.app import create_app

    state = _context(config)
    # serve builds its own background loop; tasks are not inlined.
    state.inline_tasks = False
    bind_host, bind_port = parse_bind(state.config.server.bind)
    uvicorn.run(
        create_app(state, start_background=True),
        host=host or bind_host,
        port=port or bind_port,
    )


@app.command()
def version() -> None:
    typer.echo(__version__)


if __name__ == "__main__":
    app()
