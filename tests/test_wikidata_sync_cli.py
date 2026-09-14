"""Feature 79 — the exit codes of ``scripts/sync_wikidata.py``.

Its own module rather than a block inside ``test_wikidata_sync.py`` because
``main()`` calls ``asyncio.run()``, which cannot be invoked from inside a
running event loop — and that module is ``pytest.mark.asyncio`` throughout.

The contract under test is the one ``.github/workflows/wikidata-sync.yml``
branches on:

* ``0`` — both passes finished their walk;
* ``2`` — the run happened but is **degraded**: the time budget cut a walk
  short, or QIDs were skipped (issues #22 / #24).  The workflow turns this into
  a ``::warning::`` and keeps the job green-ish, because a partial anchor is
  better than none and the cursor makes the next dispatch continue — but it
  must never be reported as a clean run;
* ``1`` — unrecoverable failure.
"""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from backlogg.recommendations.wikidata_sync import AnchorPassResult, RelationsPassResult

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "sync_wikidata.py"
_spec = importlib.util.spec_from_file_location("sync_wikidata", _SCRIPT_PATH)
sync_script = importlib.util.module_from_spec(_spec)
sys.modules["sync_wikidata"] = sync_script
_spec.loader.exec_module(sync_script)


def test_cli_exits_0_on_a_complete_run_and_2_when_degraded():
    """Exit 2 = "ran but incomplete". A partial pass must never look green."""
    complete_anchor = AnchorPassResult(completed=True)
    complete_relations = RelationsPassResult(completed=True)

    with (
        patch.object(sync_script, "run_anchor_pass", AsyncMock(return_value=complete_anchor)),
        patch.object(sync_script, "run_relations_pass", AsyncMock(return_value=complete_relations)),
        patch.object(sync_script, "engine", MagicMock(dispose=AsyncMock())),
    ):
        assert sync_script.main([]) == 0

    # The time budget cut the walk short: the cursor is kept, the run is not green.
    with (
        patch.object(
            sync_script,
            "run_anchor_pass",
            AsyncMock(return_value=AnchorPassResult(completed=False)),
        ),
        patch.object(sync_script, "run_relations_pass", AsyncMock(return_value=complete_relations)),
        patch.object(sync_script, "engine", MagicMock(dispose=AsyncMock())),
    ):
        assert sync_script.main([]) == 2

    # Issue #22/#24 skips are a loss of data and are reported the same way.
    with (
        patch.object(
            sync_script,
            "run_anchor_pass",
            AsyncMock(return_value=AnchorPassResult(completed=True, skipped_links=3)),
        ),
        patch.object(sync_script, "run_relations_pass", AsyncMock(return_value=complete_relations)),
        patch.object(sync_script, "engine", MagicMock(dispose=AsyncMock())),
    ):
        assert sync_script.main([]) == 2


def test_cli_exits_1_when_a_pass_raises():
    with (
        patch.object(
            sync_script, "run_anchor_pass", AsyncMock(side_effect=RuntimeError("wdqs is down"))
        ),
        patch.object(sync_script, "engine", MagicMock(dispose=AsyncMock())),
    ):
        assert sync_script.main([]) == 1


def test_cli_can_run_a_single_pass():
    relations = AsyncMock(return_value=RelationsPassResult(completed=True))
    anchor = AsyncMock(return_value=AnchorPassResult(completed=True))
    with (
        patch.object(sync_script, "run_anchor_pass", anchor),
        patch.object(sync_script, "run_relations_pass", relations),
        patch.object(sync_script, "engine", MagicMock(dispose=AsyncMock())),
    ):
        assert sync_script.main(["--pass", "relations"]) == 0
    anchor.assert_not_awaited()
    relations.assert_awaited_once()
