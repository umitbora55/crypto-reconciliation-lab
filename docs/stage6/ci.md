# Prepared CI and local verification

The [workflow](../../.github/workflows/release.yml) is prepared for push,
pull_request and workflow_dispatch, but **no remote workflow was run in this
task**. There is no green CI badge or published repository/package URL. The
minimum Python metadata is >=3.12; this does not mean every later Python version
or operating system has been tested.

| Prepared cell | Profile | Remote status |
|---|---|---|
| Ubuntu 24.04 / Python 3.12 | Full pinned-AI installed-wheel suite and small reproduction | NOT_RUN |
| Ubuntu 24.04 / Python 3.14 | Full suite, reproduction, six+eighteen demos, and the single 69-case/162-evaluation financial matrix | NOT_RUN |
| Ubuntu 24.04 / Python 3.14 | Separate clean core/no-AI wheel installation and offline reproduction | NOT_RUN |
| Ubuntu 24.04 / actionlint 1.7.12 | Workflow YAML/action/job validation | NOT_RUN |

The local environment available for this task is macOS arm64 / Python 3.14.7.
Python 3.12 and Ubuntu were not locally available, so those combinations are not
converted to PASS by their presence in YAML. Actual local release results, test
counts/skips, interpreter/origin and exits are recorded by the verifier and in
the separate Stage 6 review evidence. Historical 0.5.1 success is identified
separately in the [claim register](claim-evidence.md).

## Same portable entry points

Install the pinned development/build dependencies, then choose fresh output
paths. Installation/build isolation may download packages; the installed core
reproduction has no runtime network or API-key requirement.

```sh
python -m pip install --requirement requirements-build.txt
python scripts/verify_release.py --profile full --financial --output release-full-new
python scripts/verify_release.py --profile core --output release-core-new
```

The verifier's default flow calls `build_release.py`, produces an allowlisted
sdist, builds the wheel from its safe extraction, and installs into separate
owned environments. Explicit `--source EXTRACTED_SDIST --wheel WHEEL` inputs
support already-built distributions. Installed application subprocesses use an
external cwd, `-I`, no PYTHONPATH, and a checked site-packages origin. The full
profile requires all old 355 tests plus the new tool regressions, with no
unexpected skips. The core profile proves AI libraries are absent; it does not
pretend skipped training tests constitute a full-suite pass.

Only the 3.14 full CI cell passes `--financial`; the complete matrix is therefore
not multiplied across jobs. The existing small unit-test training/worker checks
remain. No main generator, training experiment, final holdout evaluator, heavy
benchmark or profiler command is in the workflow.

The workflow has `contents: read`, no secrets/publication permissions,
`persist-credentials: false`, branch-ref concurrency cancellation and bounded
job timeouts. It never uses `pull_request_target`. Failure is not suppressed.
Artifact upload runs even after a failed check to retain diagnostics; it does
not change the job's failure result. Only explicit verification reports, text
logs and small reproduction summary/index files are selected, with seven-day
retention. Venvs, DBs, full matrix payloads and historical trees are not uploaded.

## Verified official references

Checked on **2026-11-13**, using official release pages and GitHub tag/commit API
responses. Full commit pins identify code; the release labels below are readable
annotations. The [reference record](evidence/ci-reference-record.json) includes
URLs, response hashes, commit/release dates and the actionlint checksum proof.

| Dependency | Version | Verified full commit |
|---|---|---|
| [actions/checkout](https://github.com/actions/checkout/releases/tag/v7.0.1) | v7.0.1 | `3d3c42e5aac5ba805825da76410c181273ba90b1` |
| [actions/setup-python](https://github.com/actions/setup-python/releases/tag/v7.1.0) | v7.1.0 | `6d4fd22b20465ccc0f7354476588e8df7c9ca0e0` |
| [actions/upload-artifact](https://github.com/actions/upload-artifact/releases/tag/v7.0.2) | v7.0.2 | `cf430e030ddbb5b0abf93d22962f4752f3646cd9` |
| [actionlint](https://github.com/rhysd/actionlint/releases/tag/v1.7.12) | v1.7.12 | `914e7df21a07ef503a81201c76d2b11c789d3fca` |

The CI lint command downloads the official Linux AMD64 actionlint archive and
checks SHA-256 `8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8`
before extracting its executable. Local validation uses the separately verified
Darwin ARM64 archive. Both use actionlint's YAML/action/job checks; optional
ShellCheck and Pyflakes integrations are disabled and are not claimed tested.
Pinned references and minimal permissions follow
[GitHub's official guidance](https://docs.github.com/en/actions/reference/security/secure-use).

Build-only pins are [build 1.6.1](https://pypi.org/project/build/1.6.1/),
[packaging 26.3](https://pypi.org/project/packaging/26.3/),
[pyproject-hooks 1.3.3](https://pypi.org/project/pyproject-hooks/1.3.3/) and the
unchanged backend [setuptools 80.9.0](https://pypi.org/project/setuptools/80.9.0/).
They are development/build tools, not new application runtime dependencies.
The AI constraints remain the historical pinned file. Actual installed versions
are recorded per verification invocation; a remote job is still NOT_RUN until
it really executes.
