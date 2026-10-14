"""Read-only ECFG audit against project.binary in the original exported PCK.

Only four exact render-setting names may differ. Every other key and encoded
Variant must match byte for byte, including export features and input/display
settings. No Godot, extraction, settings generation, network or output files.

scaling_3d/mode=0 may be omitted by save_custom: omission is accepted ONLY when
both exports omit the key. That preserves the original default; it is reported
separately and is not proof of an explicitly serialized or runtime-tested zero.
This does not inspect camera transforms or controls implemented in scenes/code.

Exit 0: stored settings match the contract; 1: settings differ; 2: invalid input.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
import sys

from inspect_web_pack import read_pack


ROOT = Path(__file__).resolve().parents[2]
MAX_ECFG_BYTES = 16 * 1024 * 1024
MODE = "rendering/scaling_3d/mode"
ALLOWED = {
    "rendering/scaling_3d/scale": (3, 0.5),
    MODE: (2, 0),
    "rendering/lights_and_shadows/directional_shadow/size": (2, 2048),
    "rendering/anti_aliasing/quality/msaa_3d": (2, 1),
}


def parse_ecfg(blob):
    """Decode the ECFG envelope; retain all Variant bytes, even unknown types."""
    if not 8 <= len(blob) <= MAX_ECFG_BYTES or blob[:4] != b"ECFG":
        raise ValueError("Invalid ECFG header or input size")
    count = struct.unpack_from("<I", blob, 4)[0]
    if count > 10000 or count > (len(blob) - 8) // 13:
        raise ValueError("Invalid ECFG record count")
    cursor, records = 8, {}

    def field():
        nonlocal cursor
        if cursor + 4 > len(blob):
            raise ValueError("Truncated ECFG field length")
        size = struct.unpack_from("<I", blob, cursor)[0]
        cursor += 4
        if size == 0 or size > len(blob) - cursor:
            raise ValueError("Empty or truncated ECFG field")
        data = bytes(blob[cursor:cursor + size])
        cursor += size
        return data

    for _ in range(count):
        name = field().decode("utf-8")
        if "\0" in name or name in records:
            raise ValueError(f"Invalid or duplicate ECFG key: {name!r}")
        value = field()
        if len(value) < 4:
            raise ValueError(f"Truncated Variant header: {name}")
        records[name] = value
    if cursor != len(blob):
        raise ValueError("Trailing ECFG bytes")
    return records


def numeric_variant(raw):
    if len(raw) < 4:
        raise ValueError("Truncated numeric Variant header")
    code = struct.unpack_from("<I", raw)[0]
    formats = {2: "<i", 2 | 0x10000: "<q", 3: "<f", 3 | 0x10000: "<d"}
    if code not in formats or len(raw) != 4 + struct.calcsize(formats[code]):
        raise ValueError("Expected an exact integer or float Variant")
    value = struct.unpack_from(formats[code], raw, 4)[0]
    if not math.isfinite(value):
        raise ValueError("Nonfinite numeric Variant")
    return code & 0xffff, value


def describe_variant(raw):
    """Human-readable diagnostics only; decoded equality never replaces bytes."""
    if raw is None:
        return {"present": False}
    code = struct.unpack_from("<I", raw)[0]
    result = {"present": True, "variant_tag": code, "bytes": len(raw),
              "sha256": hashlib.sha256(raw).hexdigest()}
    try:
        if code in (2, 3, 2 | 0x10000, 3 | 0x10000):
            result["value"] = numeric_variant(raw)[1]
        elif code == 1 and len(raw) == 8 and struct.unpack_from("<I", raw, 4)[0] in (0, 1):
            result["value"] = bool(struct.unpack_from("<I", raw, 4)[0])
        elif code in (4, 34):  # String and PackedStringArray, as serialized in this export.
            cursor = 4

            def string(packed=False):
                nonlocal cursor
                size = struct.unpack_from("<I", raw, cursor)[0]
                cursor += 4
                end = cursor + size
                padded_end = end + (-size % 4)
                if padded_end > len(raw):
                    raise ValueError("Truncated string Variant")
                value = raw[cursor:end]
                cursor = padded_end
                return (value.removesuffix(b"\0") if packed else value).decode("utf-8")

            if code == 4:
                value = string()
            else:
                count = struct.unpack_from("<I", raw, cursor)[0]
                cursor += 4
                if count > (len(raw) - cursor) // 4:
                    raise ValueError("Invalid string array count")
                value = [string(packed=True) for _ in range(count)]
            if cursor != len(raw):
                raise ValueError("Trailing string Variant bytes")
            result["value"] = value
        else:
            result["encoding"] = "opaque; exact raw bytes compared"
    except (ValueError, struct.error) as error:
        result["decode_error"] = str(error)
    return result


def encoded_record_size(key, raw):
    return 0 if raw is None else 8 + len(key.encode("utf-8")) + len(raw)


def compare_settings(original, candidate):
    before, after = parse_ecfg(original), parse_ecfg(candidate)
    differences, errors, proposal, approved = [], [], [], {}
    for key in sorted(before.keys() | after.keys()):
        a, b = before.get(key), after.get(key)
        if a == b:
            continue
        kind = "added" if a is None else "removed" if b is None else "changed"
        differences.append({"key": key, "kind": kind, "allowed_key": key in ALLOWED,
                            "before": describe_variant(a), "after": describe_variant(b),
                            "record_bytes_delta": encoded_record_size(key, b) - encoded_record_size(key, a)})
        if key not in ALLOWED:
            errors.append(f"Unapproved {kind} setting: {key}")
            proposal.append(f"Remove newly saved setting {key!r}." if a is None
                            else f"Restore {key!r} from the original exported ECFG, preserving its Variant bytes.")
    for key, (expected_type, expected) in ALLOWED.items():
        check = {"expected": expected, "actual": describe_variant(after.get(key))}
        if key == MODE and key not in before and key not in after:
            check.update(status="omitted_in_both", note="Unchanged engine default; zero is not explicitly encoded or runtime-verified.")
        else:
            try:
                if key not in after:
                    raise ValueError("Missing required setting")
                actual_type, actual = numeric_variant(after[key])
                if (actual_type, actual) != (expected_type, expected):
                    raise ValueError(f"Expected Variant type {expected_type} with value {expected}; got type {actual_type}, value {actual}")
                check["status"] = "matches"
            except ValueError as error:
                check.update(status="invalid", error=str(error))
                errors.append(f"{key}: {error}")
                proposal.append(f"Set only {key!r} to {expected} with Variant type {expected_type} in the existing builder.")
        approved[key] = check
    unchanged = sorted(key for key in before if before[key] == after.get(key))
    exact_others = {key: value for key, value in before.items() if key not in ALLOWED} == {
        key: value for key, value in after.items() if key not in ALLOWED}
    protected = {}
    for group, match in {
        "export_features": lambda key: "features" in key,
        "display_layout": lambda key: key.startswith("display/"),
        "input_controls": lambda key: key.startswith("input/"),
        "camera_settings": lambda key: "camera" in key.lower(),
    }.items():
        keys = sorted(key for key in before.keys() | after.keys() if match(key))
        protected[group] = {"status": "not_stored_in_ecfg" if not keys else
                            "exact" if all(key in unchanged for key in keys) else "changed", "keys": keys}
    return {"passed": not errors, "original_bytes": len(original), "candidate_bytes": len(candidate),
            "bytes_delta": len(candidate) - len(original),
            "original_records": len(before), "candidate_records": len(after),
            "original_sha256": hashlib.sha256(original).hexdigest(),
            "candidate_sha256": hashlib.sha256(candidate).hexdigest(),
            "differences": differences, "approved_settings": approved,
            "all_other_variant_bytes_exact": exact_others, "unchanged_keys": unchanged,
            "protected_settings": protected, "errors": errors,
            "minimal_patch_proposal": proposal,
            "limitations": ["No engine/browser/runtime verification; omitted defaults are not serialized values.",
                            "Scene/script camera transforms and control handlers are outside this ECFG-only audit."]}


def fingerprint(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def original_settings(pack):
    """Use the shared PCK index reader; verify just the selected entry's MD5."""
    stamp = fingerprint(pack)
    inventory = read_pack(pack, verify=False)
    entries = [entry for entry in inventory["entries"] if entry["path"].removeprefix("res://") == "project.binary"]
    if len(entries) != 1 or not 8 <= entries[0]["bytes"] <= MAX_ECFG_BYTES:
        raise ValueError("Expected one bounded project.binary entry in the original PCK")
    entry = entries[0]
    with pack.open("rb") as stream:
        stream.seek(entry["offset"])
        blob = stream.read(entry["bytes"])
    if hashlib.md5(blob).hexdigest() != entry["md5"] or fingerprint(pack) != stamp:
        raise ValueError("Original project.binary checksum mismatch or PCK changed during audit")
    return blob, {"path": str(pack), "engine": inventory["engine"], "pack_format": inventory["version"],
                  "entry_offset": entry["offset"], "entry_md5": entry["md5"],
                  "integrity_scope": "project.binary entry only"}


def audit(original_pack, candidate_path):
    original_pack, candidate_path = original_pack.resolve(strict=True), candidate_path.resolve(strict=True)
    original, source = original_settings(original_pack)
    stamp = fingerprint(candidate_path)
    if not 8 <= stamp[2] <= MAX_ECFG_BYTES:
        raise ValueError("Candidate ECFG exceeds audit size limit")
    candidate = candidate_path.read_bytes()
    if fingerprint(candidate_path) != stamp:
        raise ValueError("Candidate settings changed during audit")
    report = compare_settings(original, candidate)
    report.update(source_pack=source, candidate_path=str(candidate_path))
    return report


def readable_value(description):
    if not description["present"]:
        return "<not stored>"
    if "value" in description:
        return json.dumps(description["value"], ensure_ascii=False)
    return f"<Variant {description['variant_tag']}, {description['bytes']} bytes, sha256={description['sha256']}>"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--original-pack", type=Path, default=ROOT / "artifacts/v114/index.pck")
    parser.add_argument("--candidate", type=Path, default=ROOT / "artifacts/loading-v115/settings/project.binary")
    parser.add_argument("--json", action="store_true", help="Print complete structured report to stdout")
    args = parser.parse_args(argv)
    try:
        report = audit(args.original_pack, args.candidate)
    except (OSError, ValueError, struct.error) as error:
        print(json.dumps({"passed": False, "input_error": str(error)}, ensure_ascii=False))
        return 2
    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
    else:
        print(f"{'PASS' if report['passed'] else 'FAIL'}: {report['original_bytes']} -> {report['candidate_bytes']} bytes; "
              f"{report['original_records']} -> {report['candidate_records']} settings")
        for difference in report["differences"]:
            print(f"  {difference['kind']} {difference['key']}: {readable_value(difference['before'])} -> "
                  f"{readable_value(difference['after'])} ({difference['record_bytes_delta']:+d} bytes)")
        print(f"Other settings byte-exact: {report['all_other_variant_bytes_exact']}; unchanged keys: {len(report['unchanged_keys'])}")
        if report["approved_settings"][MODE]["status"] == "omitted_in_both":
            print("  scaling_3d/mode: omitted in BOTH files; original default retained, zero not explicitly encoded/runtime-verified.")
        for group, result in report["protected_settings"].items():
            print(f"  {group}: {result['status']} ({len(result['keys'])} stored keys)")
        for error in report["errors"]:
            print(f"ERROR: {error}")
        for proposal in report["minimal_patch_proposal"]:
            print(f"PROPOSED MINIMAL PATCH: {proposal}")
        if report["passed"]:
            print("No settings-builder patch needed for this stored-settings contract.")
        for limitation in report["limitations"]:
            print(f"Scope: {limitation}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
