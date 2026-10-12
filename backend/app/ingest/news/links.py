"""What a link is: its outlet, its kind, a date its own ID carries, and whether its title says anything."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from urllib.parse import urlsplit

SOCIAL = {"linkedin.com": "LinkedIn", "instagram.com": "Instagram", "x.com": "X", "twitter.com": "X",
          "youtube.com": "YouTube", "facebook.com": "Facebook"}
PRINT = {"assamtribune.com", "sentinelassam.com", "theshillongtimes.com", "nagalandpost.com", "morungexpress.com",
         "easternmirrornagaland.com", "arunachaltimes.in", "ifp.co.in", "highlandpost.com", "nagalandtribune.in",
         "imphaltimes.com", "tripuratimes.com", "thehindu.com", "timesofindia.indiatimes.com", "indianexpress.com",
         "hindustantimes.com", "economictimes.indiatimes.com", "livemint.com", "deccanherald.com",
         "telegraphindia.com", "business-standard.com", "thehindubusinessline.com", "tribuneindia.com",
         "newindianexpress.com", "financialexpress.com"}
SECTOR = {"thecsrjournal.in", "indiacsr.in", "csrbox.org", "idronline.org", "thecsruniverse.com", "csrmandate.org",
          "indiadevelopmentreview.com", "thebetterindia.com", "ngoconnect.net", "fundsforngos.org",
          "alliancemagazine.org", "devex.com"}
# Best first, for choosing a story's main link (D3): news, then organisation sites, then social.
RANK = {"print media": 0, "online news": 1, "CSR or sector media": 2, "organisation site": 3, "other web": 4,
        "YouTube": 5, "LinkedIn": 6, "X": 7, "Instagram": 8}
_B64 = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def host(url: str) -> str:
    h = urlsplit(url or "").netloc.lower()
    for prefix in ("www.", "m.", "mobile."):
        h = h.removeprefix(prefix)
    return h


def _social(url: str) -> str | None:
    h = host(url)
    return next((name for domain, name in SOCIAL.items() if h == domain or h.endswith("." + domain)), None)


def is_social(url: str) -> bool:
    return _social(url) is not None


# Employer reviews, job boards and company registers: a page about the organisation, never news of it.
DIRECTORIES = ("ambitionbox.com", "glassdoor.com", "glassdoor.co.in", "naukri.com", "indeed.com", "justdial.com",
               "zaubacorp.com", "tofler.in", "thecompanycheck.com",
               # job boards: an ad names the organisation and is never an event
               "jobaaj.com", "foundit.in", "shine.com", "timesjobs.com", "apna.co", "internshala.com",
               "devnetjobsindia.org", "ngojobs.in", "idealist.org")
_JOB_SEGMENTS = {"job", "jobs", "career", "careers", "vacancy", "vacancies", "recruitment", "internship"}


def is_profile_page(url: str) -> bool:
    """An account, person or company page, or a feed of posts: about the organisation, but never one event."""
    h = host(url)
    if any(h == d or h.endswith("." + d) for d in DIRECTORIES):
        return True
    path = urlsplit(url or "").path.rstrip("/")
    if _JOB_SEGMENTS & {seg.lower() for seg in path.split("/")}:
        return True
    social = _social(url)
    if social == "LinkedIn":
        return bool(re.fullmatch(r"/(in|company|school|showcase)/[^/]+(/(posts|about|people|jobs|life))?", path))
    if social == "X":
        return "/status/" not in path
    if social == "Instagram":
        return not re.search(r"/(p|reel|reels|tv)/", path)
    if social == "YouTube":
        return bool(re.match(r"/(@[^/]+|c/|channel/|user/)", path))
    return False


def is_facebook(url: str) -> bool:
    return _social(url) == "Facebook"


def source_type(url: str, content_kind: str | None) -> str:
    if social := _social(url):
        return social
    h = host(url)
    if h in PRINT:
        return "print media"
    if h in SECTOR:
        return "CSR or sector media"
    if content_kind in ("news", "opinion"):
        return "online news"
    if content_kind == "press_release":
        return "organisation site"
    return "other web"


def best_link_rank(kind: str) -> int:
    return RANK.get(kind, 9)


def post_id_date(url: str) -> date | None:
    """LinkedIn, Instagram and X IDs carry the posting time in their top bits (D10)."""
    if m := re.search(r"instagram\.com/(?:[^/]+/)?(?:p|reel|reels)/([A-Za-z0-9_-]{11})", url):
        n = 0
        for ch in m.group(1):
            n = n * 64 + _B64.index(ch)
        ms = (n >> 23) + 1314220021721
    elif m := re.search(r"linkedin\.com/.*(?:activity|share|ugcPost)[-:](\d{19})", url):
        ms = int(m.group(1)) >> 22
    elif m := re.search(r"(?:x|twitter)\.com/[^/]+/status/(\d+)", url):
        ms = (int(m.group(1)) >> 22) + 1288834974657
    else:
        return None
    return datetime.fromtimestamp(ms / 1000, UTC).date()


def url_key(url: str) -> str:
    s = urlsplit(url or "")
    return (host(url) + s.path.rstrip("/")).lower()


def title_key(title: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (title or "").lower())).strip()[:80]


def weak_title(title: str | None, url: str) -> bool:
    """A title that names nothing: empty, the platform's name, hashtags or a file name (D9)."""
    t = (title or "").strip()
    if not t or t.lower() in {name.lower() for name in SOCIAL.values()}:
        return True
    words = t.split(" | ")[0].split()  # "<post text> | <account>", as Tavily titles social posts
    if words and sum(w.startswith("#") for w in words) * 2 >= len(words):
        return True
    if re.fullmatch(r"(#\w+\s*)+", t) or re.fullmatch(r"[\w-]+\.(jpe?g|png|pdf|mp4)", t, re.IGNORECASE):
        return True
    return len(re.findall(r"[A-Za-z]{3,}", t)) < 3
