"""S4-F1 canonical source-path protection for new triage publication boundaries."""
import os
from pathlib import Path
from ..review.adapter import SIDECARS, Selection, read_selection
from ..review.validation import ReviewError


def preflight_output(output, databases=(), protected_files=()):
    """No writes; keep the unchanged review export's early-exists/sidecar rules.

    The Stage 4.1 exporter has no public preflight helper. This small boundary
    uses its canonical component algorithm and shared sidecar definitions, while
    leaving that exporter byte-preserved. Publication still uses its unchanged
    atomic no-replace context manager. Quiet paths are a precondition.
    """
    requested = Path(output).expanduser().absolute()
    if os.path.lexists(requested):
        raise FileExistsError("OUTPUT_EXISTS: choose a new output directory")
    destination = requested.resolve()
    paths = [Path(p).expanduser().resolve() for p in protected_files]
    for database in databases:
        db = Path(database).expanduser().resolve()
        paths.extend(Path(str(db) + suffix).resolve() for suffix in ("", *SIDECARS))
    for path in paths:
        if destination == path or path in destination.parents:
            raise ReviewError("OUTPUT_SOURCE_CONFLICT", "triage output must not occupy an input or selected database/sidecar path")
    return destination


def selection_output(selection, output, protected_files=()):
    # Existing targets keep error precedence even over an invalid selection.
    if os.path.lexists(Path(output).expanduser().absolute()):
        raise FileExistsError("OUTPUT_EXISTS: choose a new output directory")
    selected = selection if isinstance(selection, Selection) else read_selection(selection)
    return selected, preflight_output(output, [s.database for s in selected.sources], protected_files)
