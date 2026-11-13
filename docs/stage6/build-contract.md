# Distribution and publication-source contract

Version 0.6.0 declares Python >=3.12; core remains standard-library-only and the
AI extra remains scikit-learn==1.9.1. Actual installed NumPy 2.5.4 and SciPy 1.18.1
metadata both require Python >=3.12. This does not certify every newer Python/OS.

New build-only pins are build==1.6.1, packaging==26.3 and pyproject-hooks==1.3.3;
the existing backend stays setuptools==80.9.0. See requirements-build.txt. The
official [PyPA build documentation](https://build.pypa.io/en/stable/) and
[Packaging Flow](https://packaging.python.org/en/latest/flow/) describe the roles.
Versions were checked on 13 November 2026 against official metadata:
[build](https://pypi.org/pypi/build/1.6.1/json),
[packaging](https://pypi.org/pypi/packaging/26.3/json),
[pyproject-hooks](https://pypi.org/pypi/pyproject-hooks/1.3.3/json).

build_release.py copies an explicit allowlist into a new clean source tree.
Stale workspace egg-info, build/work/backup/output directories are neither build
inputs nor deleted originals. MANIFEST.in separately declares sdist contents.
All tests and their actual script/fixture/schema dependencies, portable tools,
workflow, static documents and small examples must survive the sdist.

The wheel is built only from the safely extracted sdist. It contains application
modules, HTML/CSS/JavaScript assets, license and distribution metadata. Tests and
historical reports stay in source. Version, entrypoint, Python minimum, optional
dependencies and every application/asset byte are checked. Installed verification
uses an outside cwd, -I and actual site-packages origins.

Extraction rejects absolute/traversal paths, links, duplicate/unexpected members
and oversized archives. DBs/sidecars, backups, environments, caches/Git, keys/env
files and working outputs are excluded. New outputs cannot replace existing paths
or lie in protected source/history trees. Generated sdist PKG-INFO/setup.cfg and
bounded egg-info metadata are explicit exceptions, not stale workspace inputs.

Isolation may download the pinned backend; first setup is not promised offline.
Installed core operation is offline. Logical/financial equivalence and actual
artifact hashes do not constitute a two-build byte reproducibility measurement.

Clean source and distributions are publication preparation only. Full historical
archives remain separate and are identified in the
[historical evidence guide](historical-evidence.md). No remote repository,
package upload, workflow dispatch or release/tag is created.
