"""Ask Sangam's graph state: the organisation's readiness, judged once and handed to every funder-assessor.

deepagents passes an isolated subagent the parent's state and merges its updates back, so a key written by
org-readiness reaches the supervisor and, through it, every funder-assessor launched afterwards.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, NotRequired

from deepagents.graph import DeepAgentState
from langchain.agents.middleware import after_agent

from app.agent.assessment import PairAssessment, ReadinessAssessment, merge


def merge_readiness(left: dict | None, right: dict | None) -> dict:
    # A wave returns the inherited key from every task in one step; a plain channel would refuse that.
    return {**(left or {}), **(right or {})}


class AskState(DeepAgentState):
    # org_id (as text: checkpoints serialise keys) -> {"assessment": ReadinessAssessment dump, "assessed_at": iso}
    org_readiness: Annotated[NotRequired[dict[str, dict]], merge_readiness]


def readiness_update(state: dict[str, Any]) -> dict | None:
    """The org-readiness reply, filed under its org so later funder checks can use it."""
    result = state.get("structured_response")
    if not isinstance(result, ReadinessAssessment):
        return None
    entry = {"assessment": result.model_dump(), "assessed_at": datetime.now(UTC).isoformat(timespec="seconds")}
    return {"org_readiness": {str(result.org_id): entry}}


def merged_reply(state: dict[str, Any]) -> dict | None:
    """One funder's checks joined with the stored readiness, so the supervisor gets a scored verdict."""
    pair = state.get("structured_response")
    if not isinstance(pair, PairAssessment):
        return None
    stored = (state.get("org_readiness") or {}).get(str(pair.org_id))
    if stored is None:
        reply: Any = (
            f"funder-assessor failed: org-readiness has not run for org {pair.org_id}. "
            f"Launch org-readiness for it, wait, then assess {pair.funder_name} again."
        )
    else:
        try:
            reply = merge(stored["assessment"], pair)
        except Exception as exc:  # noqa: BLE001 - a raised error would abort the whole run
            reply = f"funder-assessor failed: {exc}"
    return {"structured_response": reply}


@after_agent(name="record_readiness")
def record_readiness(state, runtime):
    return readiness_update(state)


@after_agent(name="merge_with_readiness")
def merge_with_readiness(state, runtime):
    return merged_reply(state)
