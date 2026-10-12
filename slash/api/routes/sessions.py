"""Sessions group several tasks on one device."""

import json

from fastapi import APIRouter, Depends, HTTPException, Request

from slash.api.deps import require_bearer
from slash.api.serialize import session_out
from slash.core.models import SessionCreate
from slash.store.ids import new_id
from slash.store.tables import SessionRow

router = APIRouter(prefix="/sessions", dependencies=[Depends(require_bearer)])


@router.post("")
async def create_session(body: SessionCreate, request: Request):
    state = request.app.state.ctx
    device = state.store.get_device(body.device_id) or state.store.get_device_by_name(body.device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="device not found")
    row = state.store.insert_session(
        SessionRow(
            id=new_id(),
            user_id=state.user_id,
            device_id=device.id,
            context_json=json.dumps(body.context, ensure_ascii=False),
        )
    )
    return session_out(row)
