# Currency Reserve Simulation System

> **Disclaimer:** This is a **simulation / internal asset model only**.
> It does not represent, constitute, or replicate real-world currency,
> legal tender, financial instruments, or any regulated monetary system.

---

## Table of Contents

1. [System Design](#system-design)
2. [Directory Structure](#directory-structure)
3. [Bill Format](#bill-format)
4. [How to Run](#how-to-run)
5. [CLI Reference](#cli-reference)
6. [Integrity Model](#integrity-model)
7. [Digital Signatures](#digital-signatures)
8. [Deterministic Reproducibility](#deterministic-reproducibility)
9. [Ledger & Index](#ledger--index)
10. [Example Dataset](#example-dataset)

---

## System Design

Each simulated "bill" is a self-contained JSON file.  The reserve is
reconstructable from the file system alone: no database, no hidden state.

```
                   ┌──────────────────────┐
                   │   Generation Engine  │
                   │  (generator.py)      │
                   └────────┬─────────────┘
                            │ writes
                 ┌──────────▼──────────────────┐
                 │  reserve/<denom>s/<serial>.json  │  ← individual bills
                 └──────────┬──────────────────┘
                            │ aggregated by
               ┌────────────▼────────────────────┐
               │  reserve/index.json              │  ← per-denomination
               │  (IndexManager)                  │    Merkle roots +
               │                                  │    global root
               └────────────┬────────────────────┘
                            │ issuance log
            ┌───────────────▼─────────────────────┐
            │  ledger.json  (Ledger)               │  ← append-only batch log
            └──────────────────────────────────────┘
```

### Key design decisions

| Concern | Approach |
|---|---|
| Uniqueness | 128-bit cryptographically random serial (HMAC-SHA256 in seeded mode) |
| Tamper detection | SHA-256 checksum embedded in every bill |
| Structural integrity | Binary Merkle tree per denomination + global Merkle root |
| Optional authenticity | RSA-2048 / SHA-256 signature via system `openssl` |
| Reproducibility | Seeded generation via HMAC(seed, counter) |
| Auditability | Append-only ledger + full audit command |

---

## Directory Structure

```
.
├── reserve/                  # Data store (reconstructable from files alone)
│   ├── 1s/                   # Bills of denomination 1
│   │   └── <serial>.json
│   ├── 5s/
│   ├── 10s/
│   ├── 20s/
│   ├── 50s/
│   ├── 100s/
│   └── index.json            # Aggregate index with Merkle roots
├── ledger.json               # Master issuance log
├── keys/
│   ├── private.pem           # RSA-2048 private key (chmod 600)
│   └── public.pem            # RSA-2048 public key
├── reserve_system/           # Python package
│   ├── __init__.py
│   ├── __main__.py
│   ├── bill.py               # Bill data model
│   ├── cli.py                # CLI entry point
│   ├── crypto_utils.py       # Serials, checksums, RSA signing
│   ├── generator.py          # Batch generation engine
│   ├── index_manager.py      # Index file management
│   ├── ledger.py             # Master ledger
│   ├── merkle.py             # Binary Merkle tree
│   └── verifier.py           # Audit & single-bill verification
├── requirements.txt
└── README_RESERVE.md
```

---

## Bill Format

Each bill is stored as a JSON file at `reserve/<denom>s/<serial>.json`:

```json
{
  "batch_id": "3cf17ad1-11a1-4ef0-be2a-6b91f89d24fb",
  "checksum": "e3b0c44298fc1c149afbf4c8996fb924...",
  "created_at": "2026-05-02T22:04:19.486764+00:00",
  "denomination": 100,
  "serial": "088316570a418285f3b476f8d58139c2",
  "signature": "<base64-encoded RSA-SHA256 signature>",
  "version": "1.0"
}
```

| Field | Description |
|---|---|
| `serial` | 32 hex chars (128-bit); unique per bill |
| `denomination` | Integer: 1, 5, 10, 20, 50, or 100 |
| `created_at` | ISO 8601 UTC timestamp |
| `batch_id` | UUID linking the bill to its generation event in the ledger |
| `checksum` | SHA-256 of all fields except `checksum` and `signature` (canonical JSON) |
| `signature` | Base64 RSA-SHA256 signature over the checksum (optional) |
| `version` | Schema version string |

The **filename** always equals `<serial>.json`, so any filename/serial mismatch
is itself a tampering signal detected by the auditor.

---

## How to Run

### Prerequisites

```bash
# Python 3.9+ required; openssl must be on PATH (standard on Linux/macOS)
python3 --version
openssl version
```

The `cryptography` PyPI package is listed in `requirements.txt` for
environments where it works.  The signing layer gracefully falls back
to the system `openssl` binary when the Python bindings are unavailable.

```bash
pip install -r requirements.txt   # optional; signing works without it
```

### Quick start

```bash
# From the repo root:

# 1. Generate 200 bills with auto-distribution
python -m reserve_system generate --count 200

# 2. Check the reserve summary
python -m reserve_system summarize

# 3. Run a full integrity audit
python -m reserve_system audit

# 4. Generate RSA keys and a signed batch
python -m reserve_system keygen
python -m reserve_system generate --denominations "100:5,50:10" --sign

# 5. Verify one bill by its serial number
python -m reserve_system verify --serial <32-hex-serial>
```

---

## CLI Reference

```
python -m reserve_system <command> [options]
```

### `generate`

Create bills and write them to `reserve/`.

| Option | Default | Description |
|---|---|---|
| `--count N` | 100 | Total bills when `--denominations` is omitted |
| `--denominations SPEC` | — | Explicit distribution: `"100:10,20:30,1:60"` |
| `--seed TEXT` | — | Deterministic seed (see [Reproducibility](#deterministic-reproducibility)) |
| `--sign` | off | Sign each bill with `keys/private.pem` |

After generation the index and ledger are updated automatically.

### `audit`

Full integrity scan of every bill in `reserve/`.  Checks:

- SHA-256 checksum validity
- Serial uniqueness across the entire reserve
- Filename == serial invariant
- Denomination directory == bill denomination
- RSA signature validity (if `keys/public.pem` exists)
- Per-denomination Merkle roots against the stored index

Exit code: `0` = PASS, `1` = FAIL.

### `summarize`

Prints a formatted table of denomination counts, values, Merkle root
prefixes, the global Merkle root, and recent issuance batches.

### `verify --serial SERIAL`

Looks up one bill by serial, confirms its checksum and (if keys are
present) its RSA signature.  Exit code: `0` = valid, `1` = not found or
invalid.

### `keygen [--key-dir DIR]`

Generates an RSA-2048 key pair in `keys/` (or `--key-dir`).

### `rebuild-index`

Reconstructs `reserve/index.json` entirely from the file system.
Useful after manual edits or external file operations.

---

## Integrity Model

### Per-bill checksum

The checksum is SHA-256 over the **canonical serialisation** of the bill —
all fields sorted alphabetically, with `checksum` and `signature` excluded:

```
checksum = SHA256(JSON({batch_id, created_at, denomination, serial, version},
                       sort_keys=True, no_spaces))
```

Any modification to denomination, serial, timestamp, or batch reference
invalidates the checksum.

### Merkle tree

Bills within each denomination folder are sorted by filename and their
checksums become the leaves of a binary Merkle tree:

```
         root
        /    \
      h01    h23
     /  \   /  \
   h0   h1 h2  h3
   |    |  |    |
  b0   b1 b2  b3   ← bill checksums
```

The per-denomination Merkle root is stored in `reserve/index.json`.
A single tampered or inserted bill changes its leaf hash and propagates
the change all the way to the root — detected instantly.

A **global Merkle root** is computed from all per-denomination roots in
denomination-sorted order and stored in the index.

### What the auditor detects

| Attack | Detection mechanism |
|---|---|
| Modify a field inside a bill | Checksum mismatch |
| Add a duplicate bill (copy-paste) | Duplicate serial |
| Rename a bill file | Filename ≠ serial |
| Move a bill to the wrong folder | Denomination mismatch |
| Add a new bill without regenerating index | Merkle root divergence |
| Delete a bill without regenerating index | Merkle root divergence |
| Forge a signed bill | RSA signature failure |

---

## Digital Signatures

When `--sign` is passed, the system:

1. Computes the SHA-256 checksum of the bill (as above).
2. Signs the checksum hex-string with the RSA-2048 private key using
   `openssl dgst -sha256 -sign`.
3. Stores the base64-encoded DER signature in the `signature` field.

During audit, if `keys/public.pem` is present, every signed bill is
verified with `openssl dgst -sha256 -verify`.

Generate a key pair first:

```bash
python -m reserve_system keygen          # writes keys/private.pem + keys/public.pem
python -m reserve_system generate --sign
python -m reserve_system audit           # reports "Valid signatures: N"
```

Keep `keys/private.pem` secret.  You can distribute `keys/public.pem`
to anyone who needs to verify authenticity.

---

## Deterministic Reproducibility

Pass `--seed <string>` to produce the same serial numbers from the same
seed.  Serials are derived as:

```
serial_i = HMAC-SHA256(seed, "serial:<global_counter + i>")[:32]
```

The global counter starts from the ledger's current `bill_count`, so
running with the same seed on a non-empty reserve still produces
unique serials.

**Seeded mode is intended for testing and audit replay**, not for
production issuance.  Unseeded generation uses `secrets.token_hex(16)`
(OS CSPRNG) and is appropriate for the primary reserve.

---

## Ledger & Index

### `ledger.json`

Append-only log of every generation event:

```json
{
  "bill_count": 260,
  "total_value": 6045,
  "version": "1.0",
  "batches": [
    {
      "batch_id": "3cf17ad1-…",
      "generated_at": "2026-05-02T22:04:19.…+00:00",
      "seed": "example-seed-2026",
      "signed": false,
      "bills_generated": 150,
      "total_value": 3865,
      "denomination_distribution": {"1":15,"5":22,"10":38,"20":38,"50":22,"100":15},
      "status": "committed"
    }
  ]
}
```

### `reserve/index.json`

Snapshot of the current reserve state, including per-denomination Merkle
roots and the full entry list.  Rebuild at any time:

```bash
python -m reserve_system rebuild-index
```

The entire reserve can be reconstructed from the individual bill files
alone; the index is a derived artefact.

---

## Example Dataset

The repository ships with a pre-generated example dataset in `reserve/`:

| Denomination | Count | Total Value |
|---|---|---|
| 100 | 23 | 2,300 |
| 50 | 35 | 1,750 |
| 20 | 57 | 1,140 |
| 10 | 78 | 780 |
| 5 | 72 | 360 |
| 1 | 65 | 65 |
| **Total** | **330** | **6,395** |

Three batches are present:

1. **Batch 1** — 150 bills, seeded (`example-seed-2026`), unsigned.
2. **Batch 2** — 100 bills, explicit distribution, unsigned.
3. **Batch 3** — 10 bills (`100:3,50:3,20:4`), RSA-signed.

Run `python -m reserve_system summarize` to see live figures, or
`python -m reserve_system audit` to verify the full dataset in one command.
