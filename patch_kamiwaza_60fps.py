#!/usr/bin/env python3
"""
Kamiwaza: Way of the Thief - Framerate Cap Patcher (Proof of Concept)

Lifts the engine's 30 FPS framerate cap to 60 FPS by patching five
4-byte float constants in the .data section of the Windows PE executable.

Usage:
    python3 patch_kamiwaza_60fps.py <input.exe> [output.exe]

If output path is omitted, the patched file is written next to the input
as <input>.patched.exe. The input file is never modified.

Requires Python 3.8+. No external dependencies.

Exit codes:
    0  All patches applied successfully
    1  Input file not found / not readable
    2  Pre-patch byte verification failed (wrong game version, already patched,
       or unexpected bytes at one of the target offsets)
    3  Output file could not be written
"""

import hashlib
import os
import shutil
import struct
import sys


# Each patch entry:
#   (file_offset, expected_old_bytes_hex, new_bytes_hex, description)
#
# All offsets are absolute file offsets (not virtual addresses).
# Pre-patch verification: if the bytes at any offset do not match
# expected_old_bytes_hex, the script aborts with exit code 2 and the
# output file is deleted. This prevents silently corrupting a binary
# of an unexpected version.
PATCHES = [
    # Constant block at file offset 0x475b080 (virtual address 0x14475c880).
    # This block holds the engine's primary target-FPS / per-frame-delta
    # constants used by the frame-timing gate at virtual address 0x140d9edc0.
    (
        0x0475B080,
        "0000f041",
        "00007042",
        "Target FPS: 30.0f -> 60.0f",
    ),
    (
        0x0475B084,
        "00007041",
        "0000f041",
        "Half-rate companion: 15.0f -> 30.0f",
    ),
    (
        0x0475B088,
        "8988083d",
        "8988883c",
        "Per-frame delta (primary): 1/30 -> 1/60",
    ),
    # Two additional 1/30 constants elsewhere in .data. These feed the
    # simulation step's fixed-delta logic. Patching them is required for
    # the simulation to advance by 1/60 s per tick instead of 1/30 s.
    (
        0x047C0630,
        "8988083d",
        "8988883c",
        "Per-frame delta (secondary): 1/30 -> 1/60",
    ),
    (
        0x047C0DD8,
        "8988083d",
        "8988883c",
        "Fixed simulation delta: 1/30 -> 1/60",
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

    # Copy input to output, then patch in place
    try:
        shutil.copy2(input_path, output_path)
    except OSError as e:
        sys.stderr.write("ERROR: cannot copy to output: %s\n" % e)
        return 3

    # Read original bytes for verification
    with open(input_path, "rb") as f:
        original = f.read()

    # Verify size is plausible (the target binary is ~81 MB; allow any size
    # large enough to contain all patch offsets)
    max_offset = max(p[0] for p in PATCHES) + 4
    if len(original) < max_offset:
        sys.stderr.write(
            "ERROR: input file is %d bytes, smaller than the largest "
            "patch offset (0x%x). Wrong file?\n" % (len(original), max_offset)
        )
        os.remove(output_path)
        return 2

    # Apply patches
    applied = 0
    skipped = 0
    with open(output_path, "r+b") as f:
        for (offset, expected_hex, new_hex, desc) in PATCHES:
            expected = bytes.fromhex(expected_hex)
            new = bytes.fromhex(new_hex)

            f.seek(offset)
            actual = f.read(len(expected))

            if actual != expected:
                sys.stderr.write(
                    "VERIFY FAIL at file offset 0x%08x\n"
                    "  expected (pre-patch): %s\n"
                    "  actual:               %s\n"
                    "  description:           %s\n"
                    "  This usually means the input is not the expected "
                    "build of Kamiwaza.exe, or has already been patched.\n"
                    % (offset, expected_hex, actual.hex(), desc)
                )
                os.remove(output_path)
                return 2

            f.seek(offset)
            f.write(new)
            print(
                "patched 0x%08x: %s -> %s  (%s)"
                % (offset, expected_hex, new_hex, desc)
            )
            applied += 1

    # Hash the patched output
    with open(output_path, "rb") as f:
        patched_bytes = f.read()

    md5 = hashlib.md5(patched_bytes).hexdigest()
    sha1 = hashlib.sha1(patched_bytes).hexdigest()

    print("")
    print("input:  %s" % input_path)
    print("output: %s" % output_path)
    print("size:   %d bytes" % len(patched_bytes))
    print("md5:    %s" % md5)
    print("sha1:   %s" % sha1)
    print("")
    print("patches applied: %d / %d" % (applied, len(PATCHES)))

    if skipped:
        sys.stderr.write("WARNING: %d patch(es) skipped\n" % skipped)
    return 0


if __name__ == "__main__":
    sys.exit(main())
