# Kamiwaza: Way of the Thief - Framerate Cap Patch

**Proof of Concept.** This patch lifts the engine's 30 FPS framerate
cap to 60 FPS and fixes the cutscene audio/animation desync that
appears when running at 60 FPS. It is the result of static
reverse-engineering only and has not been validated on every supported
configuration. Treat it as a research artifact, not a finished product.

- Target binary: `Kamiwaza.exe`, 81,519,616 bytes, Windows PE x64,
  Unreal Engine 4.27.1 (build path `C:\BuildSpot\DRB_UE4.27.1\...`,
  source project codename `DoroboHD`).
- Effect 1: replaces the engine's hardcoded 30 FPS timing constants
  with their 60 FPS equivalents.
- Effect 2: forces the engine to use variable-delta time stepping for
  sequence (cutscene) evaluation, eliminating the audio-leads-animation
  desync observed when running at 60 FPS.
- Scope: binary patch only. A separate config-file change is also
  required (see "Required config changes" below) or the patch has no
  observable effect at runtime.

---

## What the patch does

The patch has two independent parts that work together:

### Part 1: Framerate cap (5 byte changes)

The engine's frame-timing logic reads a small table of float constants
from a fixed location in `.data` and uses them as the target FPS, the
half-rate companion, and the per-frame simulation delta. By replacing
30.0f with 60.0f and 1/30 with 1/60 at every site that references these
constants, the cap is raised from 30 to 60.

### Part 2: Cutscene desync fix (1 byte change)

UE4 cutscenes (`ULevelSequence` / `UMovieScene`) can evaluate using
either fixed-delta time stepping (advance simulation by a constant
amount per tick, regardless of real elapsed time) or variable-delta
(advance by real elapsed time). The original PS2-era tuning expects
fixed-delta at 30 fps.

When the framerate is unlocked to 60 FPS but the sequence evaluation
path is still on the fixed-delta branch, audio (which always plays at
real time) leads animation (which advances by a fixed 1/30 s per tick,
but only fires on certain rendered frames). The result is that
character voices play before the corresponding mouth movement / body
animation.

The patch forces the engine to always take the variable-delta path by
changing a single conditional jump to be unconditional.

The patch does not modify:
- The `t.MaxFPS` console variable (its default is already 0 = uncapped
  in this build; the cap is enforced by the constant table, not by the
  cvar system).
- The `rhi.SyncInterval` / VSync cvar defaults.
- Any other control-flow instructions. All six edits are pure data or
  single-byte opcode changes.
- The project's `GameUserSettings.ini`. The user must do this manually.

---

## What was changed

Six byte changes total: five 4-byte writes for the framerate cap, and
one 1-byte opcode change for the cutscene fix. All offsets are
absolute file offsets; the virtual addresses are listed for
cross-reference with disassembler output.

| # | File offset | Virtual address | Before (hex) | After (hex) | Before | After | Purpose |
|---|---|---|---|---|---|---|---|
| 1 | `0x0475B080` | `0x14475C880` | `00 00 F0 41` | `00 00 70 42` | 30.0f | 60.0f | Primary target FPS |
| 2 | `0x0475B084` | `0x14475C884` | `00 00 70 41` | `00 00 F0 41` | 15.0f | 30.0f | Half-rate companion |
| 3 | `0x0475B088` | `0x14475C888` | `89 88 08 3D` | `89 88 88 3C` | 1/30 (~0.03333) | 1/60 (~0.01667) | Per-frame delta (primary) |
| 4 | `0x047C0630` | `0x1447C1E30` | `89 88 08 3D` | `89 88 88 3C` | 1/30 (~0.03333) | 1/60 (~0.01667) | Per-frame delta (secondary) |
| 5 | `0x047C0DD8` | `0x1447C25D8` | `89 88 08 3D` | `89 88 88 3C` | 1/30 (~0.03333) | 1/60 (~0.01667) | Fixed simulation delta |
| 6 | `0x0D9E4DF` | `0x140D9EEDF` | `74` | `EB` | `je +0x17` | `jmp +0x17` | Force variable-delta path (cutscene fix) |

The surrounding constant block at `0x14475C880` (untouched entries
shown for context):

```
0x14475C880:  60.0f   <- patched (was 30.0f)
0x14475C884:  30.0f   <- patched (was 15.0f)
0x14475C888:  0.0166f <- patched (was 0.0333f, i.e. 1/30)
0x14475C88C:  1       (int32, untouched)
0x14475C890:  64.0f   (untouched, upper bound)
0x14475C894:  255.0f  (untouched, absolute max)
0x14475C898:  20.0f   (untouched, low-quality target)
0x14475C89C:  48.0f   (untouched, high-quality target)
0x14475C8A0:  0.95f   (untouched, smoothing factor)
0x14475C8A4:  80.0f   (untouched)
```

### Why these specific constants

The function at virtual address `0x140D9EDC0` (file offset `0x0D9E3C0`)
is the engine's frame-timing gate. Its disassembly (post-patch):

```asm
0x140D9EED8: test byte ptr [rcx + 0x2410c], 0x40   ; fixed-delta flag check
0x140D9EEDF: je   +0x17                              ; <- PATCHED: now `jmp +0x17`
                                                      ;   (was `je`, conditional on the flag)
                                                      ;   forces always-skip of fixed-delta path
...
0x140D9EF7B: movss xmm0, [0x14475C880]    ; xmm0 = 60.0f (was 30.0f)
0x140D9EF83: mulss xmm2, xmm6               ; xmm2 = current delta * scalar
0x140D9EF87: mulss xmm0, [rax + 0x240D4]    ; xmm0 = 60.0 * tick_rate_scalar
0x140D9EF8F: addss xmm0, [rbx + 0x118]      ; accumulate
0x140D9EF97: comiss xmm0, xmm2              ; compare threshold vs actual
0x140D9EF9A: movss [rbx + 0x118], xmm0      ; store
0x140D9EFA2: jbe   0x140D9EFAF               ; skip frame advance if target met
```

Before the patch, the comparison threshold is 30.0f and the fixed-delta
path is taken when the flag bit is set. After the patch, the threshold
is 60.0f and the variable-delta path is always taken, so sequence
evaluation uses real elapsed time per frame, matching the audio
playback rate.

The two `1/30 -> 1/60` constants at `0x1447C1E30` and `0x1447C25D8`
feed the simulation-step fixed-delta logic. Without patching them, the
engine would tick the simulation by 1/30 s per frame even though the
rendering target is 60 FPS, causing the simulation to fall behind real
time when the GPU cannot sustain 60 FPS.

---

## Required config changes

The binary patch alone is not sufficient. The game's `GameUserSettings.ini`
sets `FrameRateLimit=30.0` at runtime, which overrides the binary
constants. This must be edited manually.

### GameUserSettings.ini

Path (typical Windows install):

```
<GameInstallDir>/Saved/Config/WindowsNoEditor/GameUserSettings.ini
```

Find (or add) the section `[/Script/Engine.GameUserSettings]` and set:

```ini
[/Script/Engine.GameUserSettings]
FrameRateLimit=60.000000
```

---

## Applying the patch

The included `patch_kamiwaza_60fps.py` script applies all six byte
changes. It does not modify the input file; a new `<input>.patched.exe`
is produced.

```bash
python3 patch_kamiwaza_60fps.py Kamiwaza.exe
# Produces Kamiwaza.patched.exe in the same directory.
```

Or with an explicit output path:

```bash
python3 patch_kamiwaza_60fps.py Kamiwaza.exe Kamiwaza_60fps.exe
```

The script is **idempotent**: it accepts both the original (unpatched)
bytes AND the already-patched bytes at each offset. If the input is
already 60fps-patched (e.g. by an earlier version of the 60 FPS patcher),
this script will skip the already-applied FPS-cap patches and only
apply the cutscene byte. If the input is fully unpatched, all six
patches are applied. If the input is already fully patched, the script
reports "already-patched" for every offset and produces an identical
output file.

The script verifies the pre-patch bytes at every offset before writing.
If the verification fails (wrong game version, or unexpected bytes at
an offset), the script aborts with a non-zero exit code and deletes
the partial output. The input file is never modified.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | All applicable patches applied successfully (or already present) |
| 1 | Input file not found / not readable |
| 2 | Pre-patch byte verification failed (unknown bytes at offset) |
| 3 | Output file could not be written |

---

## Verification

After applying the patch and modifying the config:

1. Run the patched executable.
2. Open the in-game console (typically the `~` key, or launch with
   `-AllowConsole` if the console is disabled).
3. Type `stat unit`. The displayed FPS counter should reach approximately
   60 instead of 30.
4. Walk around for 10 real seconds and verify the in-game clock advances
   by approximately 10 seconds (not 5, not 20).
5. Play an in-game cutscene that previously exhibited desync. Verify
   that character mouth movements and body animations now match the
   voice audio.

External tools such as FRAPS, RivaTuner Statistics Server, or PresentMon
can also be used to measure the actual present rate.

---

## Known issues (Proof of Concept limitations)

This patch is incomplete. The following problems have been observed or
are anticipated:

### Slowdown when FPS drops below 60

Kamiwaza is a port of a PS2-era game and retains the original's
fixed-delta time-stepping model: each rendered frame advances the
simulation by a fixed amount, rather than by the actual elapsed real
time. The framerate-cap part of this patch changes the fixed step from
1/30 to 1/60 of a second, so the simulation now expects 60 ticks per
real second.

The cutscene-desync part of this patch (byte #6) forces the
variable-delta path, which mitigates this for sequence evaluation
(cutscenes, animations). However, the underlying simulation step
(physics, AI) may still be affected when the GPU cannot sustain 60 FPS.

If the GPU cannot sustain 60 FPS, the simulation falls behind real time
and the game appears to run in slow motion. The severity scales linearly
with the frame rate deficit (at 30 FPS rendered, the game runs at
roughly 50% speed for the parts of the simulation still on the
fixed-delta path).

### Animation / physics tuning

The original PS2 simulation was tuned for 33 ms steps. Even with the
patched 16.67 ms steps, animation curves, particle systems, and physics
solvers may behave subtly differently. Visual glitches or
inconsistent behavior are possible.

### Potential crashes

If the patched executable is loaded alongside unpatched DLC or mods
that read the original constants, the version mismatch may cause
asserts or crashes. The patched executable should be tested in
isolation first.

### Pre-rendered movie stutter (not fixed)

The starting movie (and any other pre-rendered video files) may stutter
when running at 60 FPS on a high-refresh-rate display. This is a
separate issue caused by UE4's `UMediaPlayer` having its own internal
clock that drifts relative to the engine's frame timing. There is no
clean fix without re-encoding the video at 60 fps.

### Only the listed constants are patched

This patch addresses the cap and desync mechanisms as identified by
static analysis. The binary may contain additional timing-related
constants that were not identified by this analysis. If the cap is
still enforced in some code path, or if the desync persists in some
specific cutscene, the patched executable may still exhibit issues.
A more thorough analysis (e.g., a full Ghidra decompilation of
`FEngineLoop::Tick` and related functions) would be required to rule
this out.

### No checksum re-signing

The PE file's checksum field in the optional header is not updated.
Most loaders ignore this field for EXE files, but anti-cheat or
integrity-checking systems that verify the checksum will reject the
patched executable.

---

## Rollback

To roll back:

1. Delete the patched executable.
2. Restore the original `Kamiwaza.exe` from backup (or re-download from
   the original game distribution).
3. Restore `GameUserSettings.ini` from the backup UE4 automatically
   creates at `<GameInstallDir>/Saved/Config/WindowsNoEditor/GameUserSettings.ini.bak`,
   or delete the `FrameRateLimit` line you added.

---

## Reproduction

This patch was produced by static analysis of `Kamiwaza.exe` with
Ghidra 11.3.2 headless and Capstone 5.x.

### Framerate cap (patches 1-5)

The analysis identified the constant block at virtual address
`0x14475C880` by:

1. Searching the `.rdata` and `.data` sections for the byte pattern
   `00 00 F0 41` (the IEEE-754 encoding of 30.0f).
2. For each match, scanning the `.text` section for `movss xmmN, [rip+disp32]`
   instructions whose displacement resolves to the match address.
3. For each code cross-reference, disassembling the surrounding
   function and looking for the pattern `movss xmm, [30.0f]; comiss; jcc`
   (load-then-compare-then-conditional-jump), which is the canonical
   shape of a frame-rate cap.
4. Following the static cvar pointer at `0x144BF06E0` (where the
   `t.MaxFPS` IConsoleVariable is cached after registration) to confirm
   that the cvar's default is 0.0f (uncapped), proving the cap is
   enforced by the constant table rather than the cvar.

The same procedure, applied to the byte pattern `89 88 08 3D` (the
IEEE-754 encoding of 1/30 = 0.0333...), located the two additional
constants at `0x1447C1E30` and `0x1447C25D8`.

### Cutscene desync (patch 6)

The analysis identified the fixed-delta flag check at virtual address
`0x140D9EED8` by:

1. Scanning the binary for the 8-byte `FFixedFrameRate{30, 1}` struct
   pattern (`1E 00 00 00 01 00 00 00`).
2. For each match, scanning `.text` for LEA references.
3. Discovering the getter-thunk pattern (`lea rax, [rip+disp32]; ret`).
4. Finding all 16 thunks and their callers.
5. Confirming all callers funnel into a single dispatcher function
   at `0x1433338E0` (the engine's "GetFrameRateForEnum" lookup).
6. Cross-referencing with the previously-identified frame-timing
   function at `0x140D9EDC0` to confirm the fixed-delta path is the
   source of the desync.
7. Identifying the `je` instruction at `0x140D9EEDF` (opcode `0x74`)
   that gates the fixed-delta branch, and confirming that changing it
   to `jmp` (opcode `0xEB`) forces the variable-delta path.

Full analysis details are in `CUTSCENE_DESYNC.md`.
