# Data, labels and evidence lineage

```mermaid
flowchart TD
    U[User acceptance criteria and fixed protocols] --> G[Seeded synthetic worlds]
    G --> I[Retained exact inputs and known injected labels]
    I --> E[Unmodified Store and reconciliation engine]
    G --> O[Independent integer or literal oracle]
    E --> P[Retained complete financial payloads and run identities]
    O --> C[Comparison and labelled confusion counts]
    P --> C
    C --> R[Canonical case ledger and grouped uncertainty]
    G --> B[Identical static benchmark input bytes]
    B --> S[Independent stdlib arithmetic]
    B --> Q[Independent SQLite integer arithmetic]
    B --> A[Production path with full evidence output]
    S --> T[Oracle parity plus measured phases]
    Q --> T
    A --> T
    T --> L[Narrow scope comparisons and censored trials]
    F[Official Treasury and SEC acquisition attempts] --> X[Proxy 403: no real rows acquired]
    X --> N[REAL_DATA_UNVERIFIED: no real arithmetic or labels]
    R --> M[Separate claims and decisions]
    L --> M
    N --> M
    M --> H[Hash inventory and verified review archive]
```

Synthetic labels are outside the application and are not passed into its decisions. Shared family controls and multiple cases from one seed/factor world are dependent; they are not independent institutional observations. The SQL and stdlib benchmark arithmetic implementations are separate, but share an explicitly disclosed narrow input validator and persistence helper. Production replay uses the current engine and is not an independent financial oracle.

No arrow converts unavailable official data into a synthetic real-data substitute. The four transferability classes and missing institutional truth are defined in [real_world_transferability.md](real_world_transferability.md). Hash inventories bind retained bytes; they do not create an external authority for the truth of those bytes.
