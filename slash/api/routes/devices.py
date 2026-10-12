"""Device routes. Colon actions match the spec; slash aliases are accepted too."""

import tempfile
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from slash.api.deps import require_bearer
from slash.api.serialize import app_out, snapshot_out
from slash.core.models import AppInstallIn, DeviceCreate

router = APIRouter(prefix="/devices", dependencies=[Depends(require_bearer)])


def _manager(request: Request):
    return request.app.state.ctx.manager


@router.get("")
async def list_devices(request: Request):
    return await _manager(request).list_devices()


@router.post("")
async def create_device(body: DeviceCreate, request: Request):
    state = request.app.state.ctx
    return await state.manager.create(body, user_id=state.user_id)


@router.get("/{device_id}")
async def get_device(device_id: str, request: Request):
    return await _manager(request).get(device_id)


async def _start(device_id: str, request: Request):
    return await _manager(request).ensure_running(device_id)


async def _stop(device_id: str, request: Request):
    return await _manager(request).stop(device_id)


async def _restart(device_id: str, request: Request):
    await _manager(request).stop(device_id)
    return await _manager(request).ensure_running(device_id)


@router.post("/{device_id}:start")
async def start_device(device_id: str, request: Request):
    return await _start(device_id, request)


@router.post("/{device_id}/start")
async def start_device_slash(device_id: str, request: Request):
    return await _start(device_id, request)


@router.post("/{device_id}:stop")
async def stop_device(device_id: str, request: Request):
    return await _stop(device_id, request)


@router.post("/{device_id}/stop")
async def stop_device_slash(device_id: str, request: Request):
    return await _stop(device_id, request)


@router.post("/{device_id}:restart")
async def restart_device(device_id: str, request: Request):
    return await _restart(device_id, request)


@router.post("/{device_id}/restart")
async def restart_device_slash(device_id: str, request: Request):
    return await _restart(device_id, request)


@router.delete("/{device_id}")
async def delete_device(device_id: str, request: Request, keep_data: bool = True):
    await _manager(request).delete(device_id, keep_data=keep_data)
    return {"deleted": device_id, "keep_data": keep_data}


@router.post("/{device_id}/snapshots")
async def create_snapshot(device_id: str, request: Request, note: str = ""):
    row = await _manager(request).snapshot(device_id, note=note)
    return snapshot_out(row)


@router.get("/{device_id}/snapshots")
async def list_snapshots(device_id: str, request: Request):
    state = request.app.state.ctx
    state.manager.store.require_device(device_id)
    return [snapshot_out(row) for row in state.store.list_snapshots(device_id)]


@router.post("/{device_id}/snapshots/{snapshot_id}:restore")
async def restore_snapshot(device_id: str, snapshot_id: str, request: Request):
    row = await _manager(request).restore(device_id, snapshot_id)
    return snapshot_out(row)


@router.post("/{device_id}/snapshots/{snapshot_id}/restore")
async def restore_snapshot_slash(device_id: str, snapshot_id: str, request: Request):
    row = await _manager(request).restore(device_id, snapshot_id)
    return snapshot_out(row)


@router.get("/{device_id}/apps")
async def list_apps(device_id: str, request: Request):
    packages = await _manager(request).list_packages(device_id)
    return {"packages": packages}


@router.post("/{device_id}/apps")
async def install_app(device_id: str, request: Request):
    """JSON `{source_url, sha256, expected_cert_sha256}` or a multipart upload."""
    manager = _manager(request)
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" in content_type:
        form = await request.form()
        upload = form.get("file")
        expected = str(form.get("expected_cert_sha256") or "")
        digest = form.get("sha256")
        package = form.get("package")
        if upload is None or not hasattr(upload, "read"):
            from fastapi import HTTPException

            raise HTTPException(status_code=400, detail="file is required")
        if not expected:
            from fastapi import HTTPException

            raise HTTPException(status_code=400, detail="expected_cert_sha256 is required")
        raw = await upload.read()
        path = _write_temp(raw)
        try:
            row = await manager.install_app(
                device_id,
                path,
                expected_cert_sha256=expected,
                sha256=str(digest) if digest else None,
                package=str(package) if package else None,
            )
        finally:
            path.unlink(missing_ok=True)
        return app_out(row)

    body = AppInstallIn.model_validate(await request.json())
    if not body.source_url:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="source_url is required")
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        response = await client.get(body.source_url)
        response.raise_for_status()
        data = response.content
    path = _write_temp(data)
    try:
        row = await manager.install_app(
            device_id,
            path,
            expected_cert_sha256=body.expected_cert_sha256,
            sha256=body.sha256,
            package=body.package,
        )
    finally:
        path.unlink(missing_ok=True)
    return app_out(row)


def _write_temp(raw: bytes) -> Path:
    handle = tempfile.NamedTemporaryFile(suffix=".apk", delete=False)
    handle.write(raw)
    handle.close()
    return Path(handle.name)


@router.get("/{device_id}/screenshot")
async def screenshot(device_id: str, request: Request):
    png = await _manager(request).screenshot(device_id)
    return Response(content=png, media_type="image/png")


@router.get("/{device_id}/health")
async def health(device_id: str, request: Request):
    return await request.app.state.ctx.health.check(device_id)


@router.post("/{device_id}/takeover")
async def open_takeover(device_id: str, request: Request, reason: str = "manual"):
    state = request.app.state.ctx
    device = state.manager.store.require_device(device_id)
    return state.takeover.issue(
        device_id=device_id,
        task_id=None,
        reason=reason,
        serial=f"127.0.0.1:{device.adb_port}",
    )
