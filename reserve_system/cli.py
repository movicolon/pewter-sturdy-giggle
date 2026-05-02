"""CLI entry point for the Currency Reserve Simulation System."""

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .generator import GenerationEngine
from .index_manager import IndexManager
from .ledger import Ledger
from .verifier import Verifier


# ---------------------------------------------------------------------------
# Paths resolved relative to this package's parent (the repo root)
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).parent.parent
RESERVE_DIR = _ROOT / "reserve"
LEDGER_PATH = _ROOT / "ledger.json"
KEYS_DIR = _ROOT / "keys"


# ---------------------------------------------------------------------------
# Sub-commands
# ---------------------------------------------------------------------------

def cmd_generate(args) -> None:
    """Generate a batch of bills and update the ledger + index."""
    private_key = None
    if args.sign:
        priv_path = KEYS_DIR / "private.pem"
        if not priv_path.exists():
            _die(f"Private key not found at {priv_path}. Run 'keygen' first.")
        from .crypto_utils import load_private_key
        private_key = load_private_key(str(priv_path))

    ledger = Ledger(str(LEDGER_PATH))

    # Seeded runs continue from the ledger's global counter so serials stay unique.
    start_counter = ledger.bill_count if args.seed else 0

    engine = GenerationEngine(
        reserve_dir=str(RESERVE_DIR),
        private_key=private_key,
        seed=args.seed,
        start_counter=start_counter,
    )

    if args.denominations:
        distribution = GenerationEngine.parse_distribution(args.denominations)
    else:
        distribution = GenerationEngine.distribution_from_count(args.count)

    total_bills = sum(distribution.values())
    total_value = sum(d * c for d, c in distribution.items())

    print(f"Generating {total_bills} bills  (total value: {total_value:,})")
    for denom in sorted(distribution, reverse=True):
        count = distribution[denom]
        print(f"  {denom:>4}s  {count:>6} bills  = {denom * count:>9,}")

    batch_id, bills = engine.generate_batch(distribution)
    ledger.record_batch(batch_id, distribution, args.seed, signed=args.sign)
    index = IndexManager(str(RESERVE_DIR)).rebuild()

    print(f"\n  Batch ID   : {batch_id}")
    print(f"  Bills      : {len(bills)}")
    print(f"  Total value: {total_value:,}")
    print(f"  Ledger     : {LEDGER_PATH}")
    print(f"  Index      : {RESERVE_DIR / 'index.json'}")
    print(f"  Merkle root: {index['global_merkle_root']}")


def cmd_audit(args) -> None:
    """Run the full integrity audit and exit 0 on PASS, 1 on FAIL."""
    pub_path = str(KEYS_DIR / "public.pem") if (KEYS_DIR / "public.pem").exists() else None
    verifier = Verifier(str(RESERVE_DIR), public_key_path=pub_path)

    print("Running full audit …\n")
    result = verifier.full_audit()
    print(result.summary())

    def _section(title: str, items: list) -> None:
        if items:
            print(f"\n{title}:")
            for item in items[:20]:
                print(f"  {item}")
            if len(items) > 20:
                print(f"  … and {len(items) - 20} more")

    _section("INVALID CHECKSUMS",      result.invalid_checksums)
    _section("DUPLICATE SERIALS",      result.duplicate_serials)
    _section("FILENAME MISMATCHES",    result.filename_mismatches)
    _section("DENOMINATION MISMATCHES", result.denomination_mismatches)
    _section("SIGNATURE FAILURES",     result.signature_failures)
    _section("MERKLE MISMATCHES",      result.merkle_mismatches)
    _section("PARSE ERRORS",           result.parse_errors)

    sys.exit(0 if result.passed else 1)


def cmd_summarize(args) -> None:
    """Print a human-readable reserve summary."""
    index = IndexManager(str(RESERVE_DIR)).load()
    if index is None:
        print("No index found. Run 'generate' or 'rebuild-index' first.")
        return

    W = 52
    print("=" * W)
    print("  CURRENCY RESERVE — SIMULATION SUMMARY")
    print("=" * W)
    print(f"  Index built  : {index.get('generated_at', 'N/A')}")
    print(f"  Total value  : {index.get('total_value', 0):>14,}")
    print(f"  Total bills  : {index.get('bill_count', 0):>14,}")
    print()
    print(f"  {'Denom':>6}  {'Count':>8}  {'Total Value':>12}  Merkle Root (prefix)")
    print("  " + "-" * (W - 2))
    for denom_str, info in sorted(
        index.get("denominations", {}).items(),
        key=lambda x: -int(x[0]),
    ):
        short = info["merkle_root"][:12] + "…"
        print(f"  {denom_str:>6}  {info['count']:>8,}  {info['total_value']:>12,}  {short}")
    print()
    print(f"  Global Merkle root: {index.get('global_merkle_root', 'N/A')}")
    print("=" * W)

    if LEDGER_PATH.exists():
        ledger = Ledger(str(LEDGER_PATH))
        print(f"\n  Issuance log: {len(ledger.batches)} batch(es)\n")
        for batch in ledger.batches[-10:]:
            ts = batch["generated_at"][:19]
            bid = batch["batch_id"][:8]
            print(f"    [{ts}] batch={bid}…  bills={batch['bills_generated']}  value={batch['total_value']:,}")


def cmd_verify(args) -> None:
    """Verify a single bill by serial number."""
    pub_path = str(KEYS_DIR / "public.pem") if (KEYS_DIR / "public.pem").exists() else None
    verifier = Verifier(str(RESERVE_DIR), public_key_path=pub_path)

    info = verifier.verify_bill(args.serial)
    if not info["found"]:
        print(f"Bill not found: {args.serial}")
        sys.exit(1)

    _ok = lambda v: "OK" if v else "FAIL"
    print(f"  Serial         : {args.serial}")
    print(f"  File           : {info['file']}")
    print(f"  Denomination   : {info['denomination']}")
    print(f"  Created at     : {info['created_at']}")
    print(f"  Batch ID       : {info['batch_id']}")
    print(f"  Checksum       : {_ok(info['checksum_valid'])}")
    if info["signed"]:
        sv = info["signature_valid"]
        print(f"  Signature      : {_ok(sv) if sv is not None else 'UNVERIFIED (no public key)'}")
    else:
        print(f"  Signature      : unsigned")

    sys.exit(0 if info["checksum_valid"] else 1)


def cmd_keygen(args) -> None:
    """Generate an RSA-2048 key pair for bill signing."""
    from .crypto_utils import generate_key_pair
    key_dir = args.key_dir or str(KEYS_DIR)
    priv, pub = generate_key_pair(key_dir)
    print(f"  Private key : {priv}  (chmod 600)")
    print(f"  Public key  : {pub}")
    print("\n  Use --sign with 'generate' to sign bills with this key pair.")


def cmd_rebuild_index(args) -> None:
    """Rebuild reserve/index.json by scanning the file system."""
    print(f"Scanning {RESERVE_DIR} …")
    index = IndexManager(str(RESERVE_DIR)).rebuild()
    print(f"  Bill count : {index['bill_count']:,}")
    print(f"  Total value: {index['total_value']:,}")
    print(f"  Merkle root: {index['global_merkle_root']}")
    print(f"\nIndex written to {RESERVE_DIR / 'index.json'}")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reserve",
        description="Currency Reserve Simulation System — simulation/internal asset model only",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    # generate
    g = sub.add_parser("generate", help="Generate a batch of bills")
    g.add_argument("--count", type=int, default=100,
                   help="Total bills to generate when --denominations is omitted (default: 100)")
    g.add_argument("--denominations", metavar="SPEC",
                   help="Explicit distribution: 'denom:count[,...]'  e.g. '100:10,20:30,1:60'")
    g.add_argument("--seed", help="Deterministic seed for reproducible serial generation")
    g.add_argument("--sign", action="store_true",
                   help="Sign each bill with the private key in keys/private.pem")
    g.set_defaults(func=cmd_generate)

    # audit
    a = sub.add_parser("audit", help="Full integrity audit (exits 0=PASS, 1=FAIL)")
    a.set_defaults(func=cmd_audit)

    # summarize
    s = sub.add_parser("summarize", help="Print reserve composition summary")
    s.set_defaults(func=cmd_summarize)

    # verify
    v = sub.add_parser("verify", help="Verify a single bill by serial number")
    v.add_argument("--serial", required=True, help="32-hex-char serial number")
    v.set_defaults(func=cmd_verify)

    # keygen
    k = sub.add_parser("keygen", help="Generate RSA-2048 key pair for bill signing")
    k.add_argument("--key-dir", metavar="DIR",
                   help=f"Output directory (default: {KEYS_DIR})")
    k.set_defaults(func=cmd_keygen)

    # rebuild-index
    r = sub.add_parser("rebuild-index", help="Rebuild index.json from the file system")
    r.set_defaults(func=cmd_rebuild_index)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


def _die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    sys.exit(1)
