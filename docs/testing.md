# Testing changes without a car (IDEmu)

> **Language:** English · [Русский](testing.ru.md)

Some evocode changes can be rehearsed in an emulator before you touch a real head unit.
[IDEmu](https://github.com/herrbimmer/IDEmu) is a QEMU-based emulator of the NBT EVO / iDrive6 head
unit (macOS) that boots the unit's **own** software from your own PSdZData/SWFL, with SSH and a coding
editor. (License: PolyForm Noncommercial.)

The one thing it is genuinely useful for here is the **blobB anchor swap** — confirming that a patched
`NBTCarHU` (`evocode fsc patch-blobb`) boots the unit's own software **without bricking it**, which is
the scariest step of the on-car FSC procedure.

## What it can and can't test

| ✅ Rehearsable in IDEmu | ❌ Only on the car |
|---|---|
| A patched `NBTCarHU` boots QNX (services + SSH come up) | Diagnostic-plane commands — `write`, `fsc apply`/`read`, `root` — IDEmu does not expose the HSFZ endpoint (TCP 6801) |
| No boot regression vs. stock (reaches the same stage) | Whether an FSC is actually **accepted** (needs the diagnostic write + a running `NBTCarHU`) |
| The binary stays intact / length-preserving | HMI render and feature activation — validated only for specific HMI builds¹ |
| Coding survives (it lives in a separate image, untouched by a blobB swap) | Maps / navigation, Android Auto |

¹ If your HMI build is not in IDEmu's validated set, boot stalls near the end (the HMI never finishes)
and `NBTCarHU` — gated behind HMI readiness — will not start. That is an emulator/version limit, not
your patch: you still validate the **system layer** (boot / SSH / coding). Compare patched vs. stock —
if **both** reach the same stage, the swap is boot-safe.

## Rehearsing a blobB swap

1. **Baseline (stock).** Build a version-matched environment from your own SWFL, cold-boot it, and over
   SSH record: `uname -a`, the size of `NBTCarHU`, `pidin a | grep -i carhu` (which processes are up),
   and how far boot got. This separates "my patch broke it" from "the emulator behaves this way on my
   build."
2. **Build the patched binary** with evocode (length-preserving — only the 128-byte blobB changes):
   ```bash
   evocode fsc find-blobb NBTCarHU.stock      # offset + current anchor fingerprint (per-build — do not hardcode)
   evocode fsc patch-blobb NBTCarHU.stock --key owner.json --backup stock_blobB.bin -o NBTCarHU.patched
   ```
3. **Inject into the image.** Because the patch is length-preserving, the stock 128-byte anchor appears
   verbatim in the environment's root image — replace it in place, then **cold-boot** (the root image is
   a RAM-disk, so edits inside a running guest do not survive a reboot):
   ```python
   img = bytearray(open(".../sda.img", "rb").read())
   old = open("stock_blobB.bin", "rb").read()        # from --backup above
   new = open("owner_blobB.bin", "rb").read()        # your anchor (evocode fsc keygen --blobb)
   i = img.find(old)
   assert i >= 0 and img.find(old, i + 1) == -1, "anchor not found / not unique in image"
   img[i:i + 128] = new
   open(".../sda.img", "wb").write(img)
   ```
   (Alternative, closer to the on-car step: `scp` the patched `NBTCarHU` into a running guest and restart
   the HMI — it mirrors the at-car rename-over, but it is not a disk cold-boot.)
4. **Cold-boot** the patched image and verify against the baseline.

## Pass / fail

| Check | PASS | FAIL |
|---|---|---|
| Cold-boot of the patched image | reaches the baseline stage, QNX + services alive | panics / hangs **earlier** than baseline |
| SSH into the guest | answers; `uname` = QNX OMAP5 | no session |
| `NBTCarHU` process | present in `pidin a`, not crash-looping | absent / crash-loop |
| Binary size | unchanged (patch is length-preserving) | changed |
| Anchor in the image | your anchor's fingerprint (`evocode fsc fingerprint`) | stock / foreign fingerprint |

**PASS** = the anchor swap is boot-safe → on the car you risk only the write transport, not a brick.

## What this does and does not map to

It rehearses the **firmware-file install** (that the patched `NBTCarHU` boots). It does **not** cover
the diagnostic-plane steps (`fsc apply`/`read`, coding `write`, `root enable` — no HSFZ in the
emulator), feature verification, maps, or Android Auto. Those stay for the car. See
[root-access.md](root-access.md) for the firmware/filesystem plane and [../AGENTS.md](../AGENTS.md) §1
for the two-plane model.

## Notes

- Find the blobB offset with `evocode fsc find-blobb` — never hardcode it; it differs per build.
- Single-core TCG emulation is slow; let boot run in the background, do not poll.
- Setup (the QEMU `omap5-uevm` target + renderer, `python3 -m idemu gui|build|run|ssh`) is IDEmu's own —
  see its repository.
- An IDEmu console **bridge** forwards a shell but does **not** pipe exec stdin (confirmed: `cat`-over-exec
  writes 0 bytes), so it can't exercise `evocode fw`'s file transfer — only its choreography
  (remount / backup / rename-over / chmod on real QNX, via `fw --modern`). `fw install` verifies the
  on-unit byte-count and aborts on mismatch, so that limitation — or a dropped transfer — can't install an
  empty file.
