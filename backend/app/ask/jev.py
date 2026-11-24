"""Jev's decisions in Ask: which way a question goes and which skill it needs (docs/features/2026-11-24-jev-ask-decisions.md)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from langchain.agents.middleware import after_agent
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from app.ask.audit import DATA_TOOLS
from app.ask.middleware import this_turn
from app.core.config import Settings
from app.integrations.tracing import score_answer
from app.integrations.typesafe import Decision, adecide

QUESTION_CHARS = 1000
NO_SKILL = "none"
ROUTES = {
    "catalog": "Answerable from Sangam's database of Indian NGOs, funders, grants, CSR spending, funder fit and news "
    "about them, or a follow-up to such a question in the same chat.",
    "research": "Asks to find out new facts about an organisation from the web or its documents, which Sangam Scout "
    "does, not this chat.",
    "off_topic": "Not about NGOs, funders or funding in India: small talk, general knowledge, the weather, or current "
    "affairs unrelated to them.",
}
_SKILL_PATH = re.compile(r"/skills/([^/]+)/SKILL\.md$")
_FIELD = re.compile(r"^(name|description):\s*(.+)$", re.MULTILINE)


def skill_catalog(skills_dir: Path) -> dict[str, str]:
    """Each skill's name and frontmatter description, as Jev's choices."""
    skills = {}
    for path in sorted(skills_dir.glob("*/SKILL.md")):
        text = path.read_text()
        head = text.split("---", 2)[1] if text.startswith("---") else ""
        fields = dict(_FIELD.findall(head))
        skills[fields.get("name", path.parent.name)] = fields.get("description", "")
    return skills


def questions(skills: dict[str, str]) -> dict[str, dict]:
    return {
        "route": {"type": "choice", "instructions": "Where should this question go?", "criteria": ROUTES},
        "skill": {
            "type": "choice",
            "instructions": "Which procedure should the assistant load before answering?",
            "criteria": {**skills, NO_SKILL: "No procedure: a direct lookup, count, list, definition or follow-up."},
        },
    }


def asked(messages: list[BaseMessage]) -> dict[str, str | None] | None:
    """The question and the one before it, as Jev's state; None when the turn has no typed question."""
    texts = [m.text.strip() for m in messages if isinstance(m, HumanMessage) and m.text.strip()]
    if not texts:
        return None
    return {
        "question": texts[-1][:QUESTION_CHARS],
        "previous_question": texts[-2][:QUESTION_CHARS] if len(texts) > 1 else None,
    }


@dataclass(frozen=True, slots=True)
class Did:
    """What the turn actually did: the label each decision is compared with."""

    skills: tuple[str, ...]  # skills the model read, in order
    used_data: bool  # a data tool ran


def did(messages: list[BaseMessage]) -> Did:
    skills, used = [], False
    for message in this_turn(messages):
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                found = _SKILL_PATH.search(str(call["args"].get("file_path", ""))) if call["name"] == "read_file" else None
                if found and found.group(1) not in skills:
                    skills.append(found.group(1))
        elif isinstance(message, ToolMessage) and message.name in DATA_TOOLS:
            used = True
    return Did(tuple(skills), used)


def route_agrees(route: str, label: Did, follow_up: bool = False) -> bool | None:
    """The turn is the label: a catalog question runs a data tool, and the other two do not. None when it cannot
    tell: a follow-up answered from the chat is catalog too, with no tool."""
    if route == "catalog" and follow_up and not label.used_data:
        return None
    return (route == "catalog") == label.used_data


def skill_agrees(skill: str, label: Did) -> bool:
    """Jev names the first skill the model read, or none when it read none."""
    return skill == (label.skills[0] if label.skills else NO_SKILL)


def score_route(decision: Decision, label: Did, follow_up: bool = False) -> None:
    route, confidence, probabilities = decision.choice("route")
    agrees = route_agrees(route, label, follow_up) if route else None
    if agrees is None:
        return
    score_answer(
        "jev_route_agree",
        1.0 if agrees else 0.0,
        comment=f"jev={route} ({confidence:.2f}); data tool ran: {label.used_data}",
        metadata={"probabilities": probabilities, "latency_ms": decision.latency_ms},
    )


def score_skill(decision: Decision, label: Did) -> None:
    skill, confidence, probabilities = decision.choice("skill")
    if skill is None:
        return
    score_answer(
        "jev_skill_agree",
        1.0 if skill_agrees(skill, label) else 0.0,
        comment=f"jev={skill} ({confidence:.2f}); model read: {', '.join(label.skills) or NO_SKILL}",
        metadata={"probabilities": probabilities, "latency_ms": decision.latency_ms},
    )


def jev_shadow(settings: Settings, skills: dict[str, str]):
    """After the answer, ask Jev what it would have decided and score it against what the turn did."""
    wanted = {name for name, mode in (("route", settings.jev_route), ("skill", settings.jev_skill)) if mode == "shadow"}
    asking = {k: v for k, v in questions(skills).items() if k in wanted}

    @after_agent(name="jev_shadow")
    async def _shadow(state, runtime):
        state_in = asked(state["messages"])
        if state_in is None:
            return
        decision = await adecide(state_in, asking, name="jev_route_skill", settings=settings)
        if decision is None:
            return
        label = did(state["messages"])
        score_route(decision, label, follow_up=state_in["previous_question"] is not None)
        score_skill(decision, label)

    return _shadow
