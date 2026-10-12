"""Prompt-compatible Mobilerun planner.

The upstream package (`mobilerun`, formerly DroidRun) is optional and is not imported.
This planner uses the same action schema and actuator as the native loop so a config
change can switch planners without a second runtime. Vision flags follow the task mode
(`tree`, `tree+vision`, `vision-only`).
"""

from slash.agent.planners.native import NativePlanner
from slash.agent.prompts.native import MOBILERUN_SYSTEM


class MobilerunPlanner(NativePlanner):
    name = "mobilerun"

    async def next(self, goal, history, obs, device, *, human_reply: str = ""):
        return await self._with_prompt(goal, history, obs, device, human_reply)

    async def _with_prompt(self, goal, history, obs, device, human_reply: str):
        import json

        from slash.agent.actions import ACTION_ADAPTER
        from slash.agent.planners.native import _action_from_result
        from slash.llm.base import Message
        from slash.llm.coords import convert_action

        user = {
            "goal": goal,
            "vision": self.mode in {"tree+vision", "vision-only"},
            "vision_only": self.mode == "vision-only",
            "tree": "" if self.mode == "vision-only" else obs.tree_text,
            "history": history[-8:],
            "human_reply": human_reply,
        }
        messages = [
            Message(role="system", content=MOBILERUN_SYSTEM),
            Message(role="user", content=json.dumps(user, ensure_ascii=False)),
        ]
        images = []
        if self.mode in {"tree+vision", "vision-only"} and self.provider.supports_vision and obs.screenshot_for_llm:
            images = [obs.screenshot_for_llm]
        result = await self.provider.complete(messages, images=images, schema=ACTION_ADAPTER)
        action = convert_action(
            _action_from_result(result),
            self.provider.coord_space,
            device.width,
            device.height,
        )
        return action, result
