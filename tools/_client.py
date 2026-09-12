"""Shared client bootstrap for the course's own tools.

Mirrors the notebooks exactly: an explicit ClientConfig, the two-identity branch from
Chapter 02, and a repo-root .env loaded without depending on python-dotenv.
"""
from __future__ import annotations

import os
import pathlib

from cognite.client import CogniteClient, global_config

global_config.disable_pypi_version_check = True
from cognite.client.config import ClientConfig  # noqa: E402
from cognite.client.credentials import (  # noqa: E402
    OAuthClientCredentials,
    OAuthInteractive,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load_env() -> None:
    """Load repo-root .env. A real environment variable always wins."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        key, value = s.split("=", 1)
        if " #" in value and not value.startswith(('"', "'")):
            value = value.split(" #", 1)[0].rstrip()
        os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def participant() -> str:
    name = os.environ.get("PARTICIPANT")
    if not name:
        raise SystemExit(
            "  PARTICIPANT is not set.\n"
            "  Add PARTICIPANT=<YOURNAME> to your .env, or export it for this shell."
        )
    return name


def cdf_client(name: str = "course-selfcheck") -> CogniteClient:
    load_env()
    missing = [k for k in ("CDF_PROJECT", "CDF_CLUSTER", "IDP_CLIENT_ID") if not os.environ.get(k)]
    if missing:
        raise SystemExit(f"  missing {missing} — copy .env.example to .env and fill it in")

    base_url = os.environ.get("CDF_URL") or f"https://{os.environ['CDF_CLUSTER']}.cognitedata.com"
    scopes = [s for s in os.environ.get("IDP_SCOPES", f"{base_url}/.default").split(",") if s]

    if os.environ.get("LOGIN_FLOW", "interactive").lower() == "interactive":
        credentials = OAuthInteractive(
            authority_url=os.environ["IDP_AUTHORITY_URL"],
            client_id=os.environ["IDP_CLIENT_ID"],
            scopes=scopes,
        )
    else:
        credentials = OAuthClientCredentials(
            token_url=os.environ["IDP_TOKEN_URL"],
            client_id=os.environ["IDP_CLIENT_ID"],
            client_secret=os.environ["IDP_CLIENT_SECRET"],
            scopes=scopes,
        )

    return CogniteClient(
        ClientConfig(
            client_name=name,
            project=os.environ["CDF_PROJECT"],
            base_url=base_url,
            credentials=credentials,
        )
    )


class Report:
    """Collects PASS/FAIL lines so a learner sees the whole picture, not the first failure."""

    def __init__(self, chapter: str) -> None:
        self.chapter = chapter
        self.rows: list[tuple[bool, str, str]] = []

    def check(self, label: str, got, want=None, *, ok: bool | None = None) -> bool:
        passed = ok if ok is not None else (got == want)
        detail = "" if ok is not None else f"got={got!r} want={want!r}"
        if ok is not None and got is not None:
            detail = str(got)
        self.rows.append((bool(passed), label, detail))
        return bool(passed)

    def note(self, label: str, value) -> None:
        self.rows.append((True, f"[note] {label}", str(value)))

    def finish(self) -> int:
        width = max((len(label) for _, label, _ in self.rows), default=10)
        failed = 0
        for passed, label, detail in self.rows:
            if label.startswith("[note]"):
                print(f"       {label[6:].strip():<{width}}  {detail}")
                continue
            mark = "PASS" if passed else "FAIL"
            failed += 0 if passed else 1
            print(f"  [{mark}] {label:<{width}}  {detail}")
        total = sum(1 for _, l, _ in self.rows if not l.startswith("[note]"))
        print(f"\n  Chapter {self.chapter}: {total - failed}/{total} checks passed")
        if failed:
            print("  Not ready for the next chapter — fix the FAILs above.")
        return 1 if failed else 0
