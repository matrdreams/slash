"""Native planner: one structured LLM call per step."""

import json

from slash.agent.actions import ACTION_ADAPTER, Action
from slash.agent.observer import Observation
from slash.agent.prompts.native import NATIVE_SYSTEM
from slash.core.errors import LLMError
from slash.llm.base import LLMResult, Message
from slash.llm.coords import convert_action
from slash.store.tables import DeviceRow


class NativePlanner:
    async def verify(self, goal: str, history: list[dict], obs: Observation):
        return await verify_goal(self.provider, goal, history, obs)

    name = "native"

    def __init__(self, provider, *, mode: str) -> None:
        self.provider = provider
        self.mode = mode

    async def next(
        self,
        goal: str,
        history: list[dict],
        obs: Observation,
        device: DeviceRow,
        *,
        human_reply: str = "",
        hints: dict | None = None,
    ) -> tuple[Action, LLMResult]:
        user = {
            "goal": goal,
            "mode": self.mode,
            "screen": {"width": device.width, "height": device.height},
            "tree": obs.tree_text if self.mode != "vision-only" else "",
            "tree_note": "vision-only: the tree may be incomplete; use the screenshot",
            "history": history[-8:],
            "human_reply": human_reply,
        }
        if hints:
            user.update(hints)
        messages = [
            Message(role="system", content=NATIVE_SYSTEM),
            Message(role="user", content=json.dumps(user, ensure_ascii=False)),
        ]
        images: list[bytes] = []
        if self.mode in {"tree+vision", "vision-only"} and self.provider.supports_vision:
            if obs.screenshot_for_llm:
                images = [obs.screenshot_for_llm]
        result = await self.provider.complete(messages, images=images, schema=ACTION_ADAPTER)
        action = _action_from_result(result)
        action = convert_action(action, self.provider.coord_space, device.width, device.height)
        return action, result


def _action_from_result(result: LLMResult) -> Action:
    if result.parsed is not None:
        try:
            return ACTION_ADAPTER.validate_python(
                result.parsed.model_dump() if hasattr(result.parsed, "model_dump") else result.parsed
            )
        except Exception:
            pass
    if not result.text:
        raise LLMError("planner returned an empty response")
    try:
        from slash.llm.base import parse_json_payload

        return ACTION_ADAPTER.validate_python(parse_json_payload(result.text))
    except Exception as exc:
        raise LLMError(f"planner output is not an action: {exc}") from exc


async def verify_goal(provider, goal: str, history: list[dict], obs: Observation) -> tuple[bool, str, LLMResult]:
    """Ask the provider a yes/no question: is the goal already achieved on this screen?"""
    from slash.agent.completion import VERIFY_SYSTEM, parse_verdict

    user = {"goal": goal, "tree": obs.tree_text, "history": history[-6:]}
    messages = [
        Message(role="system", content=VERIFY_SYSTEM),
        Message(role="user", content=json.dumps(user, ensure_ascii=False)),
    ]
    result = await provider.complete(messages, images=[], schema=None)
    achieved, evidence = parse_verdict(result.text)
    return achieved, evidence, result
