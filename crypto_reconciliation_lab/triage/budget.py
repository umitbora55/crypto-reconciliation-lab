"""One monotonic deadline and combined file budget for a bounded experiment."""
from contextlib import contextmanager
from pathlib import Path
import time


class ExperimentBudget:
    def __init__(self, roots, *, seconds=900, max_bytes=2 * 1024 ** 3):
        self.started = time.monotonic()
        self.seconds = seconds
        self.max_bytes = max_bytes
        self.roots = [Path(root).resolve() for root in roots]
        self.temporary_root = self.roots[0]
        self.peak_bytes = 0
        self.last_scan = -100.0
        self.last_bytes = 0
        self.reserved_bytes = 0
        self.peak_reserved_bytes = 0

    @contextmanager
    def reserve_transient(self, byte_count):
        """Account for unchanged adapter copies outside the owned runtime tree.

        This is resource accounting only, never a model feature. The adapter
        holds one complete verified copy per selected source until it returns.
        """
        if type(byte_count) is not int or byte_count < 0:
            raise ValueError("TRIAGE_BUDGET_RESERVATION: nonnegative byte count required")
        self.reserved_bytes += byte_count
        self.peak_reserved_bytes = max(self.peak_reserved_bytes, self.reserved_bytes)
        try:
            self.check(force=True)
            yield
            self.check(force=True)
        finally:
            self.reserved_bytes -= byte_count

    def add_root(self, root):
        path = Path(root).resolve()
        if path not in self.roots:
            self.roots.append(path)

    def check(self, force=False):
        elapsed = time.monotonic() - self.started
        if elapsed > self.seconds:
            raise ValueError("TRIAGE_BUDGET_TIME: common 900-second experiment deadline exceeded")
        if force or elapsed - self.last_scan >= 2:
            roots = [p for p in self.roots if not any(p != other and p.is_relative_to(other) for other in self.roots)]
            self.last_bytes = sum(p.stat().st_size for root in roots if root.exists()
                                  for p in root.rglob("*") if p.is_file() and not p.is_symlink())
            self.last_scan = elapsed
        accounted = self.last_bytes + self.reserved_bytes
        self.peak_bytes = max(self.peak_bytes, accounted)
        if accounted > self.max_bytes:
            raise ValueError("TRIAGE_BUDGET_BYTES: combined temporary/retained experiment files exceed 2 GiB")
        elapsed = time.monotonic() - self.started
        if elapsed > self.seconds:
            raise ValueError("TRIAGE_BUDGET_TIME: common experiment deadline exceeded during file accounting")
        return {"elapsed_seconds": elapsed, "current_bytes": accounted,
                "peak_bytes": self.peak_bytes, "reserved_transient_bytes": self.reserved_bytes,
                "peak_reserved_transient_bytes": self.peak_reserved_bytes,
                "limit_seconds": self.seconds, "limit_bytes": self.max_bytes}


def budgeted_read_selected_sources(selection, budget=None):
    """Use the unchanged read-only adapter with conservative copy accounting."""
    from ..review.adapter import read_selected_sources
    if budget is None:
        return read_selected_sources(selection)
    with budget.reserve_transient(sum(source.database.stat().st_size for source in selection.sources)):
        return read_selected_sources(selection)
