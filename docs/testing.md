# Testing changes without a car (IDEmu)

> **Language:** English · [Русский](testing.ru.md)

Some evocode changes can be rehearsed in an emulator before you touch a real head unit.
[IDEmu](https://github.com/herrbimmer/IDEmu) runs original BMW head-unit software under QEMU, using
your own PSdZData/SWFL. Upstream covers CIC and iDrive 5–8; NBT EVO / iDrive 5/6 supports macOS and
Linux/WSL, with real HMI, SSH, coding editor, virtual CAN/GPS and cluster/HUD.
(License: PolyForm Noncommercial.)

For evocode, use it to rehearse a **blobB anchor swap** (`evocode fsc patch-blobb`) and `fw` install
choreography; it also provides an HMI/plugin development stand. An emulator pass reduces uncertainty
about that software/profile combination; it cannot establish that a change is safe on real hardware.

Checked on 2026-11-20 against upstream `main`
[`d03ecd84f363`](https://github.com/herrbimmer/IDEmu/tree/d03ecd84f363): exact-match 24-03 (`007_051_002`)
and 18-03 (`006_017_006`) shim profiles are merged; the broader multi-firmware registry in
[PR #16](https://github.com/herrbimmer/IDEmu/pull/16) is open and unmerged, head
[`d73b049`](https://github.com/FreZZZeR/IDEmu/commit/d73b049d8f69e146b08018e8204a516a9bb7b501), updated against main `d03ecd8`;
GitHub reports `mergeable=true`, `clean` as of 2026-11-20. Four `007` registry profiles were
rebuilt and cold-booted to a live HMI on that branch; this does not verify FSC acceptance.
Our `006_016_002` still lacks a full matching SWFL set and a validated profile; neighbouring
`006_017_006` does not establish its HMI/plugin ABI compatibility. Linux/WSL and a new 18-03 boot
were not rerun locally. Setup and profile selection are in [dev-stand.md](dev-stand.md);
the historical boot/SSH observations below date from 2026-11-11.

## What it can and can't test

| ✅ Rehearsable in IDEmu | ❌ Only on the car |
|---|---|
| QNX/services/SSH still boot after replacing `NBTCarHU` | Diagnostic-plane commands — `write`, `fsc apply`/`read`, `root` — IDEmu does not expose HSFZ (TCP 6801) |
| No boot regression vs. stock; a running patched `NBTCarHU` where the baseline starts it | Whether an FSC is actually **accepted** by the real unit |
| The binary stays intact / length-preserving; coding survives in its separate image | Feature activation, BMW navigation/route guidance, live Android Auto / CarPlay |
| HMI/plugins on an exact-match validated profile; virtual CAN/GPS/cluster/HUD and host-rendered map composition | Radio/media/audio, USB and physical vehicle networks |

A version/profile mismatch can leave QNX/SSH alive while the HMI or `NBTCarHU` never starts. In our
2026-11-11 setup this happened with `007_001_016`. Equal progress of stock and patched images then
proves only no earlier boot regression, **not** successful execution of the patched binary. The
host-rendered map is not the BMW navigation engine and cannot validate map FSC `0120`.

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
3. **Inject into the image.** Stop the emulator and use a disposable image (rebuild from SWFL to reset it).
   Because the patch is length-preserving, the stock 128-byte anchor appears
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
   `scp` is not an alternative on the console bridge (see [dev-stand.md](dev-stand.md) §4).
4. **Cold-boot** the patched image and verify against the baseline.

## Pass / fail

| Check | PASS | FAIL |
|---|---|---|
| Cold-boot of the patched image | reaches the baseline stage, QNX + services alive | panics / hangs **earlier** than baseline |
| SSH into the guest | answers; `uname` = QNX OMAP5 | no session |
| `NBTCarHU` process | present in `pidin a`, not crash-looping | absent / crash-loop |
| Binary size | unchanged (patch is length-preserving) | changed |
| Anchor in the image | your anchor's fingerprint (`evocode fsc fingerprint`) | stock / foreign fingerprint |

**PASS** requires the patched `NBTCarHU` to run at least as well as stock in this environment. If the
baseline never starts it, mark that check **not exercised**. This is not proof of on-car boot safety
or FSC acceptance; keep the real unit's backup and recovery path.

## What this does and does not map to

It rehearses the **firmware-file install** (that the patched `NBTCarHU` boots). It does **not** cover
the diagnostic-plane steps (`fsc apply`/`read`, coding `write`, `root enable` — no HSFZ in the
emulator), real feature/FSC verification, BMW route guidance or live Android Auto. Those stay for the
car. See
[root-access.md](root-access.md) for the firmware/filesystem plane and [../AGENTS.md](../AGENTS.md) §1
for the two-plane model.

## Notes

- Find the blobB offset with `evocode fsc find-blobb` — never hardcode it; it differs per build.
- Single-core TCG emulation is slow; let boot run in the background, do not poll.
- Standing up a stand (build IDEmu, your own version-matched SWFL + exact shim-profile matching,
  create/build/run, the console bridge's quirks, and what each kind of stand can develop) is in
  [dev-stand.md](dev-stand.md).
- An IDEmu console **bridge** forwards a shell but does **not** pipe exec stdin (confirmed: `cat`-over-exec
  writes 0 bytes), so it can't exercise `evocode fw`'s file transfer — only its choreography
  (remount / backup / rename-over / chmod on real QNX, via `fw --modern`). `fw install` verifies the
  on-unit byte-count and aborts on mismatch, so that limitation — or a dropped transfer — can't install an
  empty file.
