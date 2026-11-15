"""Finite TEST-ONLY replay-link witnesses from unchanged historical captures.

The stream witness is byte-identical to the independent Stage13 review input.
Renewed pins identify deliberately altered synthetic material, not trusted
original executions. No fixture is regenerated through the implementation.
"""
from pathlib import Path

from replay_fixtures import rebound, write_historical
from replay_historical_fixtures import historical_0101


ORIGINAL_PIN = 'f9514f8cba20a5000b9fdbd1f299159f409e0e491662d9526aa6f243bcabd436'
STREAM_PIN = '16719ee4fa9e6b061e76e133852ca76ccebc9e2c02994819525522abc8f097be'
ORIGINAL_CONTEXT_SHA256 = '818205dca3fbb63676d5af9e0d4db37d8431b22f14b925a71b16c8891a02c1d6'
STREAM_CONTEXT_SHA256 = '17f2d06188a55da57ff2bf49c91e64b57353152e05acdbd6c89c7fb13a3ccb86'
RAW_RUN_SHA256 = '14c675e3bdb3106451c069915db22095e9cacf26c1ab9e674b64d04754738dd0'


def link_pairs(root):
    """Original, exact review stream mismatch, and existing-sequence mismatch."""
    root = Path(root)
    original = write_historical(root/'original', historical_0101()['after-current-replay'])

    def change(context, field, value):
        decision = next(row for row in context['tables']['auth_decisions'] if row['id'] == 31)
        decision[field] = value

    stream = rebound(original, root/'stream-mismatch',
        mutate_context=lambda context: change(context, 'stream_id', 'nonexistent-stream'),
        raw_run=original['run_path'].read_bytes())
    sequence = rebound(original, root/'sequence-mismatch',
        mutate_context=lambda context: change(context, 'sequence', 2),
        raw_run=original['run_path'].read_bytes())
    return original, stream, sequence
