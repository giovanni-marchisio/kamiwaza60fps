#!/usr/bin/env python3
"""
Kamiwaza: Way of the Thief - Combined Patcher (Proof of Concept)

Applies both patches in a single pass:

  1. Framerate cap patch (5 byte changes)
     Lifts the engine's 30 FPS framerate cap to 60 FPS by editing
     five 4-byte float constants in the .data section.

  2. Cutscene desync patch (1 byte change)
     Forces the engine to use variable-delta time stepping for
     sequence evaluation, eliminating the audio-leads-animation
     desync observed when running at 60 FPS.

Idempotent: the script accepts both the original (unpatched) bytes
AND the already-patched bytes at each offset. If the input is
already 60fps-patched (e.g. by patch_kamiwaza_60fps.py), this
script will skip the already-applied FPS-cap patches and only
apply the cutscene byte. If the input is fully unpatched, all
six patches are applied.

Usage:
    python3 patch_kamiwaza_combined.py <input.exe> [output.exe]

If output path is omitted, the patched file is written next to the
input as <input>.patched.exe. The input file is never modified.

Requires Python 3.8+. No external dependencies.

Exit codes:
    0  All applicable patches applied successfully (or already present)
    1  Input file not found / not readable
    2  Pre-patch byte verification failed (unknown bytes at offset)
    3  Output file could not be written
"""

import hashlib
import os
import shutil
import sys


# Each patch entry:
#   (file_offset, [valid_before_hex_list], new_hex, description)
#
# `valid_before_hex_list` is a list of acceptable pre-patch byte patterns.
# - For unpatched input: the first pattern in the list is expected.
# - For already-patched input: a later pattern in the list is expected,
#   and the script will skip the patch (idempotent).
#
# If the actual bytes match none of the patterns, the script aborts
# with exit code 2.
PATCHES = [
    # === Framerate cap patch (5 patches) ===
    # Each accepts the original (unpatched) bytes OR the post-60fps-patch
    # bytes. If the input already has the post-patch bytes, no write
    # happens for that offset.
    (
        0x0475B080,
        ["0000f041", "00007042"],   # 30.0f (original) OR 60.0f (already patched)
        "00007042",                 # final: 60.0f
        "FPS cap: target FPS 30.0f -> 60.0f",
    ),
    (
        0x0475B084,
        ["00007041", "0000f041"],   # 15.0f (original) OR 30.0f (already patched)
        "0000f041",                 # final: 30.0f
        "FPS cap: half-rate 15.0f -> 30.0f",
    ),
    (
        0x0475B088,
        ["8988083d", "8988883c"],   # 1/30 (original) OR 1/60 (already patched)
        "8988883c",                 # final: 1/60
        "FPS cap: per-frame delta 1/30 -> 1/60 (primary)",
    ),
    (
        0x047C0630,
        ["8988083d", "8988883c"],
        "8988883c",
        "FPS cap: per-frame delta 1/30 -> 1/60 (secondary)",
    ),
    (
        0x047C0DD8,
        ["8988083d", "8988883c"],
        "8988883c",
        "FPS cap: fixed simulation delta 1/30 -> 1/60",
    ),
    # === Cutscene desync patch (1 patch) ===
    # Accepts the original `je` opcode (0x74) OR the patched `jmp` opcode
    # (0xEB). If already patched, skip.
    (
        0x0D9E4DF,
        ["74", "eb"],               # je (original) OR jmp (already patched)
        "eb",                       # final: jmp
        "Cutscene desync: je -> jmp (force variable-delta path)",
    ),
]


def parse_args():
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        sys.stderr.write(__doc__)
        sys.exit(1)
    input_path = sys.argv[1]
    if len(sys.argv) == 3:
        output_path = sys.argv[2]
    else:
        root, ext = os.path.splitext(input_path)
        output_path = root + ".patched" + ext
    return input_path, output_path


def main():
    input_path, output_path = parse_args()

    if not os.path.isfile(input_path):
        sys.stderr.write("ERROR: input file not found: %s\n" % input_path)
        return 1

    try:
        shutil.copy2(input_path, output_path)
    except OSError as e:
        sys.stderr.write("ERROR: cannot copy to output: %s\n" % e)
        return 3

    with open(input_path, "rb") as f:
        original = f.read()

    max_offset = max(p[0] for p in PATCHES) + 4
    if len(original) < max_offset:
        sys.stderr.write(
            "ERROR: input file is %d bytes, smaller than the largest "
            "patch offset (0x%x). Wrong file?\n" % (len(original), max_offset)
        )
        os.remove(output_path)
        return 2

    applied = 0
    skipped = 0
    with open(output_path, "r+b") as f:
        for (offset, valid_before_list, new_hex, desc) in PATCHES:
            new = bytes.fromhex(new_hex)
            f.seek(offset)
            actual = f.read(len(new))

            # Check if the actual bytes match any of the valid pre-patch
            # patterns (which includes the post-patch value).
            matched_pattern = None
            for valid_hex in valid_before_list:
                if actual == bytes.fromhex(valid_hex):
                    matched_pattern = valid_hex
                    break

            if matched_pattern is None:
                sys.stderr.write(
                    "VERIFY FAIL at file offset 0x%08x\n"
                    "  expected one of: %s\n"
                    "  actual:           %s\n"
                    "  desc:             %s\n"
                    "  This usually means the input is not the expected "
                    "build of Kamiwaza.exe.\n"
                    % (offset, ", ".join(valid_before_list), actual.hex(), desc)
                )
                os.remove(output_path)
                return 2

            if matched_pattern == new_hex:
                # Already patched - skip
                print("already-patched 0x%08x: %s == %s  (%s) - skipping"
                      % (offset, matched_pattern, new_hex, desc))
                skipped += 1
                continue

            f.seek(offset)
            f.write(new)
            print("patched 0x%08x: %s -> %s  (%s)"
                  % (offset, matched_pattern, new_hex, desc))
            applied += 1

    with open(output_path, "rb") as f:
        patched_bytes = f.read()

    print("")
    print("input:  %s" % input_path)
    print("output: %s" % output_path)
    print("size:   %d bytes" % len(patched_bytes))
    print("md5:    %s" % hashlib.md5(patched_bytes).hexdigest())
    print("sha1:   %s" % hashlib.sha1(patched_bytes).hexdigest())
    print("patches applied: %d / %d  (already-patched: %d)"
          % (applied, len(PATCHES), skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
