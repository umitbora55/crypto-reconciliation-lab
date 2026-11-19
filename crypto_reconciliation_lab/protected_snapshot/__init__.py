"""Opt-in Linux protected snapshot boundary; legacy review behavior is unchanged."""

FORMAT = "protected-snapshot-v1"


class ProtectionError(RuntimeError):
    """A protection invariant could not be established; never continue export."""
