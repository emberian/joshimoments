"""Session-wide guards. The first one exists because it was needed within an hour of not
existing.

THE HUNCH TAPE IS PRODUCTION DATA AND THE TEST SUITE MUST NOT BE ABLE TO REACH IT
---------------------------------------------------------------------------------
``state/hunches.jsonl`` is the operator's own record of what they thought about a coin, and
it is the corpus a later model is meant to be fitted to. A test that appends to it does not
merely leave litter: it puts a gesture nobody made into the training set, and because the
tape is append-only and never rewritten, that row is there forever.

This happened. An API test posted a capture with an out-of-range confidence, expecting a
400; the endpoint's ``float(x or default)`` coerced ``0`` to the default instead of
refusing, the request succeeded, and a fabricated hunch landed on the live tape. The
endpoint bug is fixed and the row is retracted on the tape (``hunch.retraction.v1``), but
the durable fix is this fixture: no test can write there, whether or not it remembered to
monkeypatch anything.

It is ``autouse`` and session-scoped on purpose. A fixture a test has to opt into is a
fixture the next test will forget, and "the next test" is how the first one got written.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest


@pytest.fixture(autouse=True, scope="session")
def _never_touch_the_live_hunch_tape(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """Point every default hunch-tape write at a throwaway file for the whole session."""
    import shitcoims_paperdesk.hunch as hunch_module

    sandbox: Path = tmp_path_factory.mktemp("hunch-tape") / "hunches.jsonl"
    real = hunch_module.HUNCH_PATH
    # Every default write and read resolves this module global at CALL time -- including
    # the API's, which calls ``append_hunch`` with no path -- so rebinding it here covers
    # the whole tree, imported or not, now or later in the session.
    hunch_module.HUNCH_PATH = sandbox
    try:
        yield
    finally:
        hunch_module.HUNCH_PATH = real
