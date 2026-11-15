# S13-F2: preserve completed comparison on output path failure

The independent review observed a real Linux/Python 3.12.14 failure when
`--output loop/new-report` crossed a test-owned `loop -> loop` symlink.
`Path.resolve()` raised `RuntimeError` after the worker had completed. The
unhandled exception removed the JSON result from both a clean replay and a
coherently bound, numerically divergent replay. This was an error-classification
and result-preservation defect, with no observed overwrite or financial error.

Only the two canonicalization calls inside replay API `_destination` now
translate `RuntimeError` to `ReplayError(REPLAY_OUTPUT)`. The existing public API
handler marks the existing worker report as `ERROR`, operation `ERROR`, exit 2.
It retains the completed validation/calculation/comparison fields and the
`REPRODUCED`/`EQUAL` or `DIVERGED`/`DIFFERENT` result. Other RuntimeError sources
are not covered by this handler. The worker, financial calculation, input
reader, general publication helper, no-overwrite checks and atomic publication
remain unchanged.

The new fixture stores byte-exact clean and divergent input pairs from the
independent evidence, with fixed sizes, SHA-256 values and external execution
identities. The divergent saved liability is the independently specified string
`12`; its unchanged financial inputs require `11`. Its renewed pin is TEST-ONLY.

Eight new tests cover actual self-loop filesystem behavior in both API and CLI,
two successful normal-output controls, and two deterministic output-parent-only
RuntimeError seams. Every test uses the real worker and financial computation.
They check the full completed comparison, literal financial difference, JSON
exit behavior, unchanged input hashes and absence of partial publication.
There is no skip decorator. Existing final-link, collision, dotdot and atomic
publication tests retain their original assertions.

The local interpreter is Python 3.14.7; Python 3.12 is unavailable locally.
Therefore local real Python 3.12 execution is NOT_RUN. The independent real
Python 3.12.14 evidence is retained separately. The deterministic seam makes
the unchanged 0.11.0 API fail at the exact output-parent canonicalization call;
it is not described as a real Python 3.12 CLI run. The same test and fixture
bytes then pass after the narrow repair. Final CI must run the actual filesystem
tests on both supported Python cells, including Python 3.12, without skips.

Command records, raw RED/GREEN logs, interpreter/import identities, file hashes,
timings and the independent original evidence belong outside Git in the current
`stage13_1-output` evidence tree. No historical output or contract is rewritten.
