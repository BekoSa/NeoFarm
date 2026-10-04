"""Distributed worker nodes.

A *node* is a teammate's machine running the ``farm-cli node`` agent. The
agent heartbeats here; in return the farm hands it the exploit tasks the
operator assigned from the UI. The agent then runs those exploits in round
loops (the same path as ``farm-cli run``), so their flags and run reports
flow through the normal pipeline — this module only manages the registry
and the task assignments.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import models, schemas
from ..config import get_config
from ..db import get_session
from ..deps import require_token
from ..ws import hub

log = logging.getLogger("farm.api.nodes")

router = APIRouter(prefix="/api/nodes", tags=["nodes"])

# A node not heard from within this window is treated as offline; crossing
# it in either direction is worth a feed event.
_ONLINE_WINDOW = timedelta(seconds=15)
_SCRIPT_LIMIT = 256 * 1024


def _running(node: models.Node) -> list[dict]:
    if not node.running:
        return []
    try:
        data = json.loads(node.running)
        return data if isinstance(data, list) else []
    except ValueError:
        return []


async def _task_counts(sess: AsyncSession) -> dict[int, int]:
    res = await sess.execute(
        select(models.NodeTask.node_id, func.count())
        .group_by(models.NodeTask.node_id)
    )
    return {node_id: n for node_id, n in res.all()}


def _to_out(node: models.Node, task_count: int) -> schemas.NodeOut:
    return schemas.NodeOut(
        id=node.id,
        node_id=node.node_id,
        name=node.name,
        hostname=node.hostname,
        ip=node.ip,
        labels=node.labels,
        agent_version=node.agent_version,
        enabled=node.enabled,
        status=node.status,
        running=_running(node),
        task_count=task_count,
        last_seen=node.last_seen,
        created_at=node.created_at,
    )


async def _get_or_404(sess: AsyncSession, node_id: int) -> models.Node:
    node = await sess.get(models.Node, node_id)
    if node is None:
        raise HTTPException(404, "node not found")
    return node


@router.post("/heartbeat", response_model=schemas.NodeHeartbeatResponse)
async def heartbeat(
    payload: schemas.NodeHeartbeat,
    sess: AsyncSession = Depends(get_session),
    _: None = Depends(require_token),
) -> schemas.NodeHeartbeatResponse:
    """Register (first call) or refresh a node, and return its work."""
    now = datetime.now(UTC)
    res = await sess.execute(
        select(models.Node).where(models.Node.node_id == payload.node_id)
    )
    node = res.scalar_one_or_none()

    was_offline = node is None or (
        node.last_seen is None or now - node.last_seen > _ONLINE_WINDOW
    )
    fresh = node is None

    if node is None:
        node = models.Node(node_id=payload.node_id, created_at=now)
        sess.add(node)

    node.name = payload.name or node.name or payload.hostname
    node.hostname = payload.hostname or node.hostname
    node.ip = payload.ip or node.ip
    node.labels = payload.labels if payload.labels is not None else node.labels
    node.agent_version = payload.agent_version or node.agent_version
    node.status = payload.status or node.status
    node.running = json.dumps(payload.running, default=str)
    node.last_seen = now
    await sess.commit()
    await sess.refresh(node)

    if fresh or was_offline:
        await hub.publish(
            "node",
            {
                "action": "registered" if fresh else "online",
                "name": node.name,
                "hostname": node.hostname,
            },
        )

    res = await sess.execute(
        select(models.NodeTask)
        .where(models.NodeTask.node_id == node.id)
        .order_by(models.NodeTask.sploit)
    )
    tasks = list(res.scalars().all())

    cfg = get_config()
    return schemas.NodeHeartbeatResponse(
        enabled=node.enabled,
        paused=cfg.paused,
        round_length=cfg.round_length,
        flag_format=cfg.flag_format,
        tasks=[schemas.NodeTaskOut.model_validate(t) for t in tasks],
    )


@router.get("", response_model=list[schemas.NodeOut], dependencies=[Depends(require_token)])
async def list_nodes(sess: AsyncSession = Depends(get_session)) -> list[schemas.NodeOut]:
    res = await sess.execute(select(models.Node).order_by(models.Node.name))
    nodes = list(res.scalars().all())
    counts = await _task_counts(sess)
    return [_to_out(n, counts.get(n.id, 0)) for n in nodes]


@router.patch("/{node_id}", response_model=schemas.NodeOut, dependencies=[Depends(require_token)])
async def update_node(
    node_id: int,
    payload: schemas.NodeUpdate,
    sess: AsyncSession = Depends(get_session),
) -> schemas.NodeOut:
    node = await _get_or_404(sess, node_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(node, key, value)
    await sess.commit()
    await sess.refresh(node)
    counts = await _task_counts(sess)
    await hub.publish("node", {"action": "updated", "name": node.name, "enabled": node.enabled})
    return _to_out(node, counts.get(node.id, 0))


@router.delete("/{node_id}", dependencies=[Depends(require_token)])
async def delete_node(
    node_id: int,
    sess: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    node = await sess.get(models.Node, node_id)
    if node is None:
        return {"ok": False}
    name = node.name
    await sess.delete(node)
    await sess.commit()
    await hub.publish("node", {"action": "removed", "name": name})
    return {"ok": True}


@router.get(
    "/{node_id}/tasks",
    response_model=list[schemas.NodeTaskOut],
    dependencies=[Depends(require_token)],
)
async def list_tasks(
    node_id: int,
    sess: AsyncSession = Depends(get_session),
) -> list[models.NodeTask]:
    await _get_or_404(sess, node_id)
    res = await sess.execute(
        select(models.NodeTask)
        .where(models.NodeTask.node_id == node_id)
        .order_by(models.NodeTask.sploit)
    )
    return list(res.scalars().all())


@router.post(
    "/{node_id}/tasks",
    response_model=schemas.NodeTaskOut,
    dependencies=[Depends(require_token)],
)
async def create_task(
    node_id: int,
    payload: schemas.NodeTaskCreate,
    sess: AsyncSession = Depends(get_session),
) -> models.NodeTask:
    node = await _get_or_404(sess, node_id)
    if len(payload.script) > _SCRIPT_LIMIT:
        raise HTTPException(413, "script too large")
    script_name = payload.script_name or f"{payload.sploit}.py"
    now = datetime.now(UTC)

    res = await sess.execute(
        select(models.NodeTask).where(
            models.NodeTask.node_id == node_id,
            models.NodeTask.sploit == payload.sploit,
        )
    )
    task = res.scalar_one_or_none()
    if task is None:
        task = models.NodeTask(node_id=node_id, sploit=payload.sploit, rev=1)
        sess.add(task)
    else:
        task.rev += 1  # same sploit re-pushed: bump so the agent re-syncs
    task.script = payload.script
    task.script_name = script_name
    task.args = payload.args
    task.enabled = payload.enabled
    task.updated_at = now
    await sess.commit()
    await sess.refresh(task)
    await hub.publish("node", {"action": "task", "name": node.name, "sploit": task.sploit})
    return task


@router.patch(
    "/{node_id}/tasks/{task_id}",
    response_model=schemas.NodeTaskOut,
    dependencies=[Depends(require_token)],
)
async def update_task(
    node_id: int,
    task_id: int,
    payload: schemas.NodeTaskUpdate,
    sess: AsyncSession = Depends(get_session),
) -> models.NodeTask:
    task = await sess.get(models.NodeTask, task_id)
    if task is None or task.node_id != node_id:
        raise HTTPException(404, "task not found")
    fields = payload.model_dump(exclude_unset=True)
    if "script" in fields and fields["script"] is not None and len(fields["script"]) > _SCRIPT_LIMIT:
        raise HTTPException(413, "script too large")
    # Only a content change needs the agent to rewrite + restart the exploit.
    if any(k in fields and fields[k] is not None for k in ("script", "script_name", "args")):
        task.rev += 1
    for key, value in fields.items():
        if value is not None:
            setattr(task, key, value)
    task.updated_at = datetime.now(UTC)
    await sess.commit()
    await sess.refresh(task)
    return task


@router.delete(
    "/{node_id}/tasks/{task_id}",
    dependencies=[Depends(require_token)],
)
async def delete_task(
    node_id: int,
    task_id: int,
    sess: AsyncSession = Depends(get_session),
) -> dict[str, bool]:
    res = await sess.execute(
        delete(models.NodeTask).where(
            models.NodeTask.id == task_id,
            models.NodeTask.node_id == node_id,
        )
    )
    await sess.commit()
    return {"ok": res.rowcount > 0}
