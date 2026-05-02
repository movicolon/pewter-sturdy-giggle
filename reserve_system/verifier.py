"""Integrity verification and full-audit logic for the currency reserve."""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

from .crypto_utils import verify_checksum, verify_signature, load_public_key
from .index_manager import IndexManager
from .merkle import compute_merkle_root


class AuditResult:
    """Accumulates findings from a full audit pass."""

    def __init__(self):
        self.total_bills: int = 0
        self.valid_checksums: int = 0
        self.invalid_checksums: List[str] = []
        self.duplicate_serials: List[str] = []
        self.filename_mismatches: List[str] = []
        self.denomination_mismatches: List[str] = []
        self.signature_failures: List[str] = []
        self.valid_signatures: int = 0
        self.merkle_mismatches: List[str] = []
        self.parse_errors: List[str] = []

    @property
    def passed(self) -> bool:
        return not any([
            self.invalid_checksums,
            self.duplicate_serials,
            self.filename_mismatches,
            self.denomination_mismatches,
            self.signature_failures,
            self.merkle_mismatches,
            self.parse_errors,
        ])

    def summary(self) -> str:
        w = 28
        lines = [
            f"  {'Bills scanned':<{w}} {self.total_bills}",
            f"  {'Valid checksums':<{w}} {self.valid_checksums}",
            f"  {'Invalid checksums':<{w}} {len(self.invalid_checksums)}",
            f"  {'Duplicate serials':<{w}} {len(self.duplicate_serials)}",
            f"  {'Filename mismatches':<{w}} {len(self.filename_mismatches)}",
            f"  {'Denomination mismatches':<{w}} {len(self.denomination_mismatches)}",
            f"  {'Signature failures':<{w}} {len(self.signature_failures)}",
            f"  {'Merkle mismatches':<{w}} {len(self.merkle_mismatches)}",
            f"  {'Parse errors':<{w}} {len(self.parse_errors)}",
        ]
        if self.valid_signatures:
            lines.append(f"  {'Valid signatures':<{w}} {self.valid_signatures}")
        lines += ["", f"  {'Status':<{w}} {'PASS' if self.passed else 'FAIL'}"]
        return "\n".join(lines)


class Verifier:
    """Validates the integrity of every bill in the reserve directory."""

    def __init__(self, reserve_dir: str, public_key_path: Optional[str] = None):
        self.reserve_dir = Path(reserve_dir)
        self.public_key = None
        if public_key_path and os.path.exists(public_key_path):
            try:
                self.public_key = load_public_key(public_key_path)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Full audit
    # ------------------------------------------------------------------

    def full_audit(self) -> AuditResult:
        result = AuditResult()
        seen_serials: Dict[str, str] = {}
        index = IndexManager(str(self.reserve_dir)).load()

        for denom_dir in sorted(self.reserve_dir.iterdir()):
            if not denom_dir.is_dir() or not denom_dir.name.endswith("s"):
                continue
            try:
                denomination = int(denom_dir.name[:-1])
            except ValueError:
                continue

            denom_checksums: List[str] = []

            for bill_file in sorted(denom_dir.glob("*.json")):
                result.total_bills += 1

                try:
                    data = json.loads(bill_file.read_text())
                except Exception as e:
                    result.parse_errors.append(f"{bill_file}: {e}")
                    continue

                serial = data.get("serial", "")

                # Filename must match serial
                if bill_file.name != f"{serial}.json":
                    result.filename_mismatches.append(str(bill_file))

                # Denomination must match directory
                if data.get("denomination") != denomination:
                    result.denomination_mismatches.append(str(bill_file))

                # Checksum
                if verify_checksum(data):
                    result.valid_checksums += 1
                    denom_checksums.append(data["checksum"])
                else:
                    result.invalid_checksums.append(str(bill_file))

                # RSA signature (only if key is loaded and bill is signed)
                if data.get("signature"):
                    if self.public_key:
                        if verify_signature(data["checksum"], data["signature"], self.public_key):
                            result.valid_signatures += 1
                        else:
                            result.signature_failures.append(str(bill_file))

                # Duplicate serial check
                if serial in seen_serials:
                    result.duplicate_serials.append(serial)
                else:
                    seen_serials[serial] = str(bill_file)

            # Merkle root verification against stored index
            if denom_checksums and index:
                stored = index.get("denominations", {}).get(str(denomination), {}).get("merkle_root")
                if stored:
                    computed = compute_merkle_root(denom_checksums)
                    if stored != computed:
                        result.merkle_mismatches.append(
                            f"{denomination}s: stored={stored[:16]}... computed={computed[:16]}..."
                        )

        return result

    # ------------------------------------------------------------------
    # Single-bill lookup
    # ------------------------------------------------------------------

    def verify_bill(self, serial: str) -> dict:
        """Locate and verify one bill by its serial number."""
        for denom_dir in self.reserve_dir.iterdir():
            if not denom_dir.is_dir():
                continue
            candidate = denom_dir / f"{serial}.json"
            if candidate.exists():
                data = json.loads(candidate.read_text())
                checksum_ok = verify_checksum(data)
                sig_ok = None
                if data.get("signature") and self.public_key:
                    sig_ok = verify_signature(data["checksum"], data["signature"], self.public_key)
                return {
                    "found":          True,
                    "file":           str(candidate),
                    "denomination":   data.get("denomination"),
                    "created_at":     data.get("created_at"),
                    "batch_id":       data.get("batch_id"),
                    "checksum_valid": checksum_ok,
                    "signed":         bool(data.get("signature")),
                    "signature_valid": sig_ok,
                }
        return {"found": False, "serial": serial}
