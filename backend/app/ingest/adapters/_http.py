"""How Sangam identifies itself to the sites it reads, and the error a source that cannot be read raises."""

from __future__ import annotations

USER_AGENT = "Sangam/0.1 (+https://github.com/project-tech4dev/sangam)"
# Explicit, and not httpx's default: its default Accept-Encoding advertises zstd,
# which India CSR's WAF answers with 403. The user agent stays honest.
HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json", "Accept-Encoding": "gzip, deflate"}
TIMEOUT_SECONDS = 25



class SourceUnavailable(RuntimeError):
    """The source could not be read. Carries a sentence for the run summary."""
