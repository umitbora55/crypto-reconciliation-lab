# Historical evidence in the publication source

The [selection manifest](evidence/selection-manifest.json) identifies six exact
copies of existing reports: original relative path, selected path, byte count
and SHA-256. No values, timestamps, machine-specific paths or result claims in
those originals were rewritten. These selected reports are not a complete
experiment archive and are not measurements made with package 0.6.0.

The selected 0.3.3 interpretation and comparison describe the sole receipt-hash
A/B experiment. The selected model card, evaluation and metrics describe the
frozen 0.5.0 model. The maintenance scope describes 0.5.1 verification. Package
versions and environments remain explicit in the [claim register](claim-evidence.md).
The portable [triage example](../../examples/triage-review/selection-manifest.json)
has a separate manifest for its selected units and packaging-only transformations.

The large historical working trees stay outside the clean publication source.
The following filenames identify separately retained review packages. They are
plain identifiers, not links to files claimed to exist inside this source
package. No public download URL has been published by this task. Obtain a package
separately from the project owner, then verify the stated SHA-256 before using it.

| Separate artifact | Bytes | SHA-256 | Scope |
|---|---:|---|---|
| `stage3_3-review.zip` | 6,853,282 | `e3f05254820632b5c704dcbadd624cb3140fdefae2120b5a723b5439666380fe` | Historical index/migration review; itself omits large raw experiments and records their identities. |
| `stage5_1-review.zip` | 43,420,003 | `3765b921f1072603c12e675278682f20f2720dd5bdc658c4e7c92c1e331578f4` | Maintenance source/tests and preserved main experiment evidence, with documented DB/cache omissions. |

For the larger raw A/B result, the original identifier is
`stage3_3-output/ab/ab.json`, SHA-256
`bd1be74b302362be62419804178cbbba3dd9b566554c740087d7688d370bb8bf`.
It is not bundled here; selected statistics and the old review package explain
its provenance and omissions. The full frozen main experiment is likewise not
regenerated to make this small source package. Old freeze/lock identities remain
historical and are not rebound to the new implementation.

Stage 6 local execution logs and final package/archive manifests belong to its
separate review evidence, including `stage6-review.zip` and its external hash/size
manifest. This static source document makes no claim that an unexecuted local or
remote verification gate passed. The [portable verifier](../../scripts/verify_release.py)
creates a fresh, machine-specific verification record when run.
