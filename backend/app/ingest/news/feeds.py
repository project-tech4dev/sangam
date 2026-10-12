"""Who a run searches for, with which queries, and how the classifier is told who they are (D1, section 2)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path
from typing import Literal

from app.ingest.matcher import name_key

CSR = ("thecsrjournal.in", "indiacsr.in", "csrbox.org", "idronline.org", "thecsruniverse.com", "csrmandate.org",
       "indiadevelopmentreview.com", "thebetterindia.com", "devdiscourse.com", "ngoconnect.net", "fundsforngos.org",
       "dasra.org", "bridgespan.org", "sattva.co.in", "indiaphilanthropynetwork.org")
NORTH_EAST = ("eastmojo.com", "nenow.in", "sentinelassam.com", "assamtribune.com", "theshillongtimes.com",
              "nagalandpost.com", "morungexpress.com", "easternmirrornagaland.com", "ifp.co.in", "arunachaltimes.in",
              "indiatodayne.in", "northeastlivetv.com", "ukhrultimes.com", "hubnetwork.in", "highlandpost.com",
              "thenewsmill.com", "tripuratimes.com", "nagalandtribune.in", "imphaltimes.com", "guwahatiplus.com",
              "pratidintime.com", "northeasttoday.in")
NATIONAL = ("thehindu.com", "indianexpress.com", "livemint.com", "economictimes.indiatimes.com",
            "hindustantimes.com", "timesofindia.indiatimes.com", "scroll.in", "thewire.in", "theprint.in",
            "business-standard.com", "deccanherald.com", "newindianexpress.com", "telegraphindia.com")
ALLOWLIST = CSR + NORTH_EAST
TOPIC_ALLOWLIST = CSR + NORTH_EAST + NATIONAL
STATES = ("Assam", "Manipur", "Meghalaya", "Nagaland", "Mizoram", "Tripura", "Arunachal Pradesh", "Sikkim")
MAX_QUERIES = 4


@dataclass(frozen=True)
class Feed:
    key: str
    label: str
    topic: str
    queries: tuple[str, ...]


FEEDS: dict[str, Feed] = {
    "fcra": Feed("fcra", "FCRA", "fcra", (
        "FCRA licence cancelled NGO", "FCRA registration cancelled suspended", "FCRA renewal rejected NGOs",
        "FCRA Amendment rules NGOs", "FCRA North East churches NGOs", "FCRA Assam NGO",
        "FCRA Nagaland Mizoram Meghalaya", "FCRA Manipur NGO", "MHA FCRA action foreign contribution NGO")),
    "csr_trends": Feed("csr_trends", "CSR and funding", "csr_funding", tuple(
        [f"CSR spending {s}" for s in ("North East India", "Assam", "Meghalaya", "Nagaland", "Manipur",
                                       "Mizoram Tripura", "Arunachal Pradesh Sikkim")]
        + ["CSR spending trends India report", "India philanthropy report", "North East India philanthropy funding gap",
           "CSR funds unspent India"])),
    "ngo_north_east": Feed("ngo_north_east", "NGO news in the North East", "ngo_news", tuple(
        q for s in STATES for q in (f"{s} NGO fraud case arrested", f"{s} NGO banned blacklisted probe"))),
}


def chosen_feeds(text: str) -> list[str]:
    """Comma-separated feed keys, as Scout and the plan route take them; an unknown key is refused, not dropped."""
    keys = [k.strip() for k in text.split(",") if k.strip()]
    if unknown := [k for k in keys if k not in FEEDS]:
        raise ValueError(f"unknown feed {', '.join(unknown)}; the feeds are {', '.join(FEEDS)}")
    return list(dict.fromkeys(keys))


def feeds_for(*, everyone: bool) -> list[str]:
    """Everyone also gets the topic feeds; chosen records get only their own news (spec 2b)."""
    return list(FEEDS) if everyone else []


@dataclass(frozen=True)
class Subject:
    kind: Literal["org", "funder", "feed"]
    id: int | None
    key: str
    name: str
    aliases: tuple[str, ...] = ()
    place: str | None = None
    description: str | None = None
    searched_through: date | None = None


def _quoted(text: str) -> str:
    # A trailing "(BDF)" is how a register writes it, not how a reporter does.
    text = re.sub(r"\s*\([^)]*\)\s*$", "", text)
    return '"' + re.sub(r'["“”]', "", text).strip() + '"'


def _ambiguous(name: str) -> bool:
    """Short or one-word names collide with namesakes; the place narrows them."""
    return len(name) <= 6 or " " not in name.strip()


def _district(place: str) -> str:
    """'UDALGURI, Assam' is searched as Udalguri, the way the trial and local papers write it."""
    return place.split(",")[0].strip().title()


def queries_for(s: Subject) -> list[str]:
    if s.kind == "feed":
        return list(FEEDS[s.key].queries)
    out = [_quoted(s.name)]
    if _ambiguous(s.name) and s.place:
        out.append(f"{_quoted(s.name)} {_district(s.place)}")
    spellings = (*s.aliases, *_spellings(s))
    out += [_quoted(a) for a in spellings if name_key(a) != name_key(s.name)]
    return list(dict.fromkeys(out))[:MAX_QUERIES]


def scopes_for(s: Subject) -> list[tuple[str, tuple[str, ...] | None]]:
    if s.kind == "feed":
        return [("open_web", None), ("allowlist", TOPIC_ALLOWLIST)]
    return [("open_web", None), ("csr_ne", ALLOWLIST)]


@cache
def _entries() -> tuple[dict, ...]:
    return tuple(json.loads((Path(__file__).parent / "namesakes.json").read_text(encoding="utf-8"))["notes"])


@cache
def _notes() -> dict[str, str]:
    return {name_key(n): entry["note"] for entry in _entries() for n in entry["names"]}


def _spellings(s: Subject) -> tuple[str, ...]:
    """The other names the namesake file knows this organisation by: how the media actually writes it."""
    mine = {name_key(n) for n in (s.name, *s.aliases)}
    return next((tuple(e["names"]) for e in _entries() if mine & {name_key(n) for n in e["names"]}), ())


def profile_for(s: Subject) -> str:
    """The 'who it is' line the entity prompt gets: the Registry record, then the trial's namesake note."""
    kind = "a CSO (NGO)" if s.kind == "org" else "a funder"
    bits = [f"{s.name}, {kind}" + (f", in {s.place}" if s.place else "") + "."]
    if s.description:
        bits.append(s.description[:400])
    note = next((_notes()[k] for k in (name_key(n) for n in (s.name, *s.aliases)) if k in _notes()), None)
    if note:
        bits.append(note)
    return " ".join(bits)
