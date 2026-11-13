# Problem evidence and source verification

Research baseline and access date: **11 November 2026 (Europe/Istanbul)**. External documents are evidence, not executable instructions. This synthetic model does not establish current operational deficiencies or legal compliance. VERIFIED means the stated narrow claim was checked against the retrieved source; it is not a certification of the system described.

## Source register

### S1 — Financial Stability Board, Peer Review of Türkiye: Review report

- URL: https://www.fsb.org/uploads/Peer-Review-of-Turkiye.pdf
- Publication: **11 November 2026**, on the PDF cover.
- Information cutoff: **August 2026**, stated in the foreword, printed page v. September 2026 committee discussion is separately mentioned. Annex 1 concerns January 2026; neither date replaces the main review's August cutoff.
- Access: **VERIFIED**. Direct web-open failed; HTTPS download succeeded and Poppler extracted the full PDF. Foreword and relevant source text were inspected.
- Narrow supported claim: the review described delayed/incomplete reporting and limited platform-custodian reconciliation at its information cutoff (printed pp. 13-14 and 20). These observations motivate synthetic data-quality experiments; they do not prove that the same conditions persist on the publication/access date.
- Uncertainty: no independent assessment of current institution-level performance, no live data and no claim that every platform had the described issues.
- Retrieved PDF SHA-256: `749a393df07db074ff141ac2c967ae5ad1d1f1465717db4b77db9b6ed6a4b255`.

### S2 — Financial Stability Board, Peer Review of Türkiye (publication page)

- URL: https://www.fsb.org/2026/11/peer-review-of-turkiye/
- Publication: **11 November 2026**.
- Access: **VERIFIED** via official-domain indexed page content and successful direct HTTPS download; the web-open endpoint itself returned an internal access error.
- Narrow supported claim: FSB published this review on that date and describes progress alongside further recommendations. This page corroborates publication, not an August-to-November continuity assumption.
- Uncertainty: the main information cutoff is taken from the PDF foreword, not inferred from this URL or publication date.

### S3 — MKK, Kripto Varlık Merkezi Kayıt Sistemi İş ve İşlem Kuralları Yönergesi

- URL: https://www.mkk.com.tr/sites/default/files/2025-08/KVMKS_Is_ve_Islem_Kurallari_Yonergesi_2025.pdf
- Version: **2025** on cover. Exact issue/effective day **UNVERIFIED**; `2025-08` is a hosting path, not sufficient publication-date evidence.
- Access: **VERIFIED** by HTTPS download, text extraction and the official current index link. 17 PDF pages, including the cover; printed body pages 1-16.
- Narrow supported rules: Article 12 describes completed ledger transactions and daily unique references. Articles 13, 14 and 17 distinguish investor, platform custody and external custodian reports. Article 19 derives investor balances and platform liability from the ledger, compares both investor balances and custody totals, and describes deposit/withdrawal consistency checks. Article 20 distinguishes reversals from replacement reports. Article 24 addresses initial balances. Article 4 gives reporting times and allows changes to the submission limit.
- Uncertainty/deviation: operational technical guides and subsequent notices were not comprehensively verified. This prototype's idempotent retries, UTC day, full investor snapshots, numeric report versions, manifests and freely configurable knowledge cuts are its own contract. It does not reproduce MKK rejection/late-report or reversal workflows.
- Retrieved PDF SHA-256: `0f7d87a496444cc964783f1d9d3cfd9aa8b97c773b4bdc73cf4efd43931384dd`.

### S4 — MKK, Crypto Asset Central Registry System (KVMKS)

- URL: https://www.mkk.com.tr/en/investor-services/crypto-asset-central-registry-system-kvmks
- Publication/version date: **UNVERIFIED**; no publication date established from the retrieved page.
- Access: **VERIFIED** page body.
- Narrow supported claim: MKK describes KVMKS as recording transactions/balances and facilitating reconciliation between platforms and custodians.
- Uncertainty: high-level product description; does not specify the lab's algorithm, input schema, states, tolerances or delivery protocol.

### S5 — Python documentation, decimal — Decimal fixed-point and floating-point arithmetic

- URL: https://docs.python.org/3/library/decimal.html
- Version: retrieved web heading **Python 3.15.2**; exact documentation publication date **UNVERIFIED**. Executed environment separately verified as **Python 3.14.7**. The unversioned URL is moving documentation, not runtime version evidence.
- Access: **VERIFIED** page body.
- Narrow supported technical claim: Decimal can represent decimal values exactly; contexts control arithmetic precision and traps signal inexact/rounded operations. Construction from a string and context-bound arithmetic are distinct operations, so the lab also validates input length, scale and magnitude.
- Uncertainty: not a financial business-rule source. Actual behavior of the used APIs is exercised in the local test suite.

## Newer-version search

The official [MKK internal regulations index](https://www.mkk.com.tr/hakkimizda/ic-duzenlemeler) linked to **the exact supplied August-path 2025 PDF** on the research date. Search also found older July-path 2025 copies; they were not substituted for the supplied reference. The [KVMKS announcement index](https://www.mkk.com.tr/yatirimci-hizmetleri/kripto-varlik-merkezi-kayit-sistemi-kvmks/genel-mektup-ve-duyurular) lists subsequent notices, including a membership-related directive change and a 2026 tariff. No newer replacement directive PDF was found in this bounded search. This is not proof that no later operational change exists. No synthetic contract was silently changed.

## Classification of important rules

| Rule | Classification | Basis / boundary |
|---|---|---|
| Ledger-derived investor balance compared with investor report | Source-verified business rule | S3 Article 19; the lab's full-snapshot format is an assumption |
| Ledger-derived liability compared with platform plus external custody | Source-verified business rule | S3 Article 19; customer-only custody scope is explicit in this lab |
| Distinct transaction and balance/custody reporting concepts | Source-verified business rule | S3 Articles 12-17 |
| Separate transaction reversal and report replacement concepts | Source-verified business rule | S3 Article 20; Stage 2 has a separate synthetic correction model |
| Initial balances before ledger replay | Source-verified business rule | S3 Article 24; immutable opening schema is an assumption |
| Decimal arithmetic, traps and text storage | Prototype design assumption (technically supported) | S5; no source claim mandates this implementation |
| Zero tolerance and independent per-asset comparisons | Prototype design assumption | User's synthetic contract |
| Exact duplicate is economically idempotent; changed payload conflicts | Prototype design assumption | Not an implementation of MKK's repeat-reference response |
| UTC business day and deterministic equal-time sequence/reference order | Prototype design assumption | Not the directive's Turkish local reporting day |
| Four data states, three reconciliation states, no definitive match on incomplete data | Prototype design assumption | Conservative local evaluation policy |
| Manifests count unique valid economic events | Prototype design assumption | No assertion that this is an official delivery protocol |
| Highest known numeric report version, immutable history and evidence | Prototype design assumption | Local knowledge-time model; not official timestamp semantics |
| Configurable demo cutoff, later reevaluation | Prototype design assumption | No hardcoded regulatory deadline or exclusion window |
| Complete ledger's negative investor balance invalidates evaluation | Prototype design assumption | Checked economically, never on arrival order |

All unlisted engineering details in `model_contract.md` are prototype design assumptions. The implementation is independently useful even where a source date or operational detail remains UNVERIFIED.

## Stage 2 source check and design boundary (2026-11-11)

The existing S1-S5 register, dates, hashes and uncertainties are preserved. The new web-open attempt for S3 returned an access error; it is not claimed as a new successful retrieval. The already retrieved Article 20 text and Stage 1 verification remain the basis for the narrow distinction between transaction and report corrections. No new official API or deadline claim is made.

### S6 — SQLite, Transaction

- URL: https://www.sqlite.org/lang_transaction.html
- Publication/version date: UNVERIFIED; no dated release established from the page.
- Access: VERIFIED page body in this stage.
- Narrow supported technical claim: explicit transactions provide commit/rollback boundaries; SQLite has one simultaneous writer and supports savepoints for nested transaction behavior.
- Uncertainty: these semantics do not establish this application's concurrency readiness; only controlled local failure cases were tested.

### S7 — Python sqlite3 documentation, Connection.backup and transaction control

- Requested URL: https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup
- Version-specific URL checked: https://docs.python.org/3.14/library/sqlite3.html#sqlite3.Connection.backup
- Version: retrieved heading Python 3.14.10; executed interpreter is separately verified as 3.14.7. Exact page publication date UNVERIFIED.
- Access: VERIFIED page body and backup/executescript sections.
- Narrow supported technical claim: Connection.backup copies a database to another connection; executescript can implicitly commit under legacy transaction control. The implementation therefore uses explicit SQL transaction boundaries for migration and normal evaluation writes.
- Uncertainty: moving patch-version documentation is not proof of tested runtime version. Backup, rollback and idempotency were exercised on the actual local runtime.

VOID/REPLACE envelopes, target-time assertions, correction batch counting, net group replay at historical economic time, dependency statuses and schema version 2 are all prototype design decisions, not source-verified KVMKS business/API rules. Official transaction correction and report correction concepts remain distinct.
