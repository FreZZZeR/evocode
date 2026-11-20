# Dev stand (IDEmu) — a test environment for the package

> **Language:** English · [Русский](dev-stand.ru.md)

A **dev stand** runs an NBT EVO head unit's own software under emulation, so you can test changes to
evocode, write new tooling for it, or develop user programs against the real QNX/HMI — without a car. It
uses [IDEmu](https://github.com/herrbimmer/IDEmu) (QEMU-based; License: PolyForm Noncommercial — personal /
research use). Upstream covers CIC and iDrive 5–8; this page concerns NBT EVO / iDrive 5/6 on macOS,
with a Linux/WSL path below. The stand is a developer convenience, not part of evocode.

Checked against upstream `main` [`d03ecd84f363`](https://github.com/herrbimmer/IDEmu/tree/d03ecd84f363)
on 2026-11-20: [Linux/WSL](https://github.com/herrbimmer/IDEmu/blob/d03ecd84f363/docs/LINUX.md) and a
validated [18-03 shim profile](https://github.com/herrbimmer/IDEmu/blob/d03ecd84f363/docs/NBT_PROFILES.md)
are merged. [PR #16](https://github.com/herrbimmer/IDEmu/pull/16) remains open and unmerged: its head
[`d73b049`](https://github.com/FreZZZeR/IDEmu/commit/d73b049d8f69e146b08018e8204a516a9bb7b501) includes main `d03ecd8`; GitHub reports
`mergeable=true`, `clean` as of 2026-11-20. The registry remains outside upstream `main`.
Four exact `007` sets (`007_051_002`, `007_001_016`, `007_030_001`, `007_039_008`) were rebuilt and
cold-booted to a live HMI on that branch on 2026-11-20, with exact companion hashes and 29 address
overrides. The older boot/SSH observations below date from 2026-11-11.

To *use* a stand to rehearse the blobB swap and validate `fw`, see [testing.md](testing.md). This page is
about *standing one up* and what it can develop.

## What a stand can and can't develop

| ✅ On the stand | ❌ Not on the stand |
|---|---|
| `fw` **choreography** (remount / backup / rename-over / chmod) on real QNX, via `fw --modern` | The **diagnostic plane** (HSFZ 6801): `write`, `fsc apply`/`read`, `root` — IDEmu doesn't expose it |
| HMI plugins, the coding / FDL editor, QNX-layer programs (SSH / FS / services / perms / slog) | `fw`'s file **transport** — the console bridge drops exec stdin (see §4) |
| The UI side of aftermarket plugins, virtual CAN/GPS and cluster/HUD, host-rendered map surface | Radio/media/audio, USB, BMW navigation/route guidance, real vehicle networks, live AA / CarPlay |

evocode's **crypto and parsing** (`sign`/`verify`/`mint`/`recover-key`/`build-catalog`/`find-blobb`/
`patch-blobb`, SREC, catalogs) need **no stand** — they are offline and covered by `pytest`. A stand is for
the on-unit filesystem / HMI / QNX slice.

## Prerequisites (macOS, Apple Silicon)

- Apple Silicon (arm64), macOS 14+.
- `brew install ninja pkg-config glib pixman`
- Python ≥3.10 to *configure* QEMU (IDEmu itself runs on the system `/usr/bin/python3`).
- clang (Xcode Command Line Tools) for the `glhost` renderer.

## 1. Build IDEmu (custom QEMU + renderer)

IDEmu's own `tools/qemu/build.sh` targets x86_64 / iDrive7; for iDrive6 / ARM (NBT EVO) build the
`omap5-uevm` ARM target, per its `src/qemu/README.md`.

```bash
git clone --depth 1 https://github.com/herrbimmer/IDEmu && cd IDEmu
IDEMU_SRC="$PWD"
mkdir -p bin
bash src/glhost/build.sh                        # -> bin/glhost (OpenGL renderer; runs headless)

W="$HOME/idemu-qemu"; mkdir -p "$W"; cd "$W"    # QEMU build tree, kept outside the repo
curl -fsSL -o qemu-11.1.2.tar.xz https://download.qemu.org/qemu-11.1.2.tar.xz
tar xf qemu-11.1.2.tar.xz; SRC="$W/qemu-11.1.2"
cp "$IDEMU_SRC/src/qemu/omap5-uevm.c" "$SRC/hw/arm/omap5-uevm.c"
( cd "$SRC" && patch -p1 < "$IDEMU_SRC/src/qemu/qemu-v11.1.2-idemu.patch" )   # patches Kconfig + meson.build
mkdir -p "$W/build" && cd "$W/build"
"$SRC/configure" --python="$(command -v python3.13)" --target-list=arm-softmmu \
  --disable-docs --disable-guest-agent --disable-tools --disable-gtk --disable-sdl \
  --disable-vnc --disable-curses --disable-rust --disable-user --disable-linux-user \
  --disable-bsd-user --without-default-features --enable-tcg
ninja qemu-system-arm
# macOS SIGKILLs an in-place overwrite of a running binary — copy to a new name, then mv:
cp qemu-system-arm "$IDEMU_SRC/bin/qemu-system-arm.new"
mv "$IDEMU_SRC/bin/qemu-system-arm.new" "$IDEMU_SRC/bin/qemu-system-arm"
"$IDEMU_SRC/bin/qemu-system-arm" -M help | grep omap5      # expect: omap5-uevm
```

For Linux/WSL, follow upstream's [Linux guide](https://github.com/herrbimmer/IDEmu/blob/d03ecd84f363/docs/LINUX.md):
Python ≥3.10, OpenGL/GLUT/libpng and the QEMU dependencies, then `bash tools/qemu/build-arm-linux.sh`
and `bash src/glhost/build.sh`. Upstream validated Ubuntu 24.04 under WSL2 with Mesa llvmpipe; use
`xvfb-run` for headless rendering and `IDEMU_NO_SNAPSHOT=1` because snapshot restore is unvalidated there.

## 2. Firmware — bring your own SWFL

IDEmu builds the disk image from **SWFL** out of **your own licensed full PSdZData** (nothing is shipped).
For NBT EVO (iDrive6) it needs **three containers, all the same version**:

| Role | File | ~size |
|---|---|---|
| OS | `swfl_0000271a.bin.<version>` | ~880 MB |
| HMI | `swfl_00002720.bin.<version>` | ~710 MB |
| brand | `swfl_00002719.bin.<version>` | ~480 MB |

**Match the shim profile, not just the version label.** Upstream now has two fixed-address profiles:

| Environment `shim_profile` | HMI SWFL | Validated scope |
|---|---|---|
| omitted / `default` | `007_051_002` (24-03) | Existing IDEmu functionality |
| `1803` | `006_017_006` (18-03) | Home screen, map-surface redirection, rotor and buttons |

The builder checks `HmiMain3D`, `libhmicom.so` and `libhmicoding.so` hashes against
`idemu/data/known_hmi.json`; `build.json` must report `hmi_validated: true`. A neighbouring firmware
version is not compatible merely because its name looks similar. Unknown builds can still be
unvalidated under the default profile; explicitly wrong profiles are rejected.

For 18-03, build separate libraries with the matching firmware's `libc.so.3`:

```bash
SHIM_PROFILE=1803 bash src/shim/build.sh /path/to/18-03/boot/lib/libc.so.3
```

With the environment stopped, set `"shim_profile": "1803"` in its `env.json` before building it.
The wizard/API create/update do not persist this field. The build-time `SHIM_PROFILE` does not select
the environment profile. Do not mix the generated `lib` and `lib-1803`
DSOs. Touch, TPM, Lua/debug hooks and snapshot restore are **not validated** for 18-03.

Our `006_016_002` is a different firmware: neither upstream 18-03 nor the four `007` registry
profiles validate its HMI/plugin ABI. A full matching SWFL set and a validated shim profile are
still missing for that exact stand. Linux/WSL and a new 18-03 boot were not rerun locally.
For PR #16 environments, old manifests without companion hashes require a full rebuild from
the original SWFL before shim refresh/coding flash; back up local image changes first.

Our 2026-11-11 tests used a live `007_051_002` HMI; `007_001_016` stalled near 90 %, and mixing its
OS/brand with the `007_051_002` HMI failed on services. Those are dated observations, not a rule that
every car-matched firmware is headless. A system-only boot can test QNX/SSH but cannot validate an
`NBTCarHU` that never started.

A Lite PSdZData (empty `swe/swfl`) will not do; you need the full one. Keep SWFL out of any repo — it is
your own licensed data.

## 3. Create, build, run

From the IDEmu repo, on `/usr/bin/python3`:

```bash
python3 -m idemu gui                 # web UI (http://127.0.0.1:8765): the "New environment" wizard
python3 -m idemu list                # environments
python3 -m idemu build <id>          # build the image from the chosen SWFL (~20–30 s)
IDEMU_NO_SNAPSHOT=1 python3 -m idemu run <id>    # cold-boot; wait for the "running" state (1–4 min on TCG)
```

The wizard (or `server.APP.create({...})`) takes the three SWFL paths, a chassis, and a VIN for decode.
Single-core TCG is slow — let boot run in the background, don't poll. Stop with Ctrl+C or
`pkill -INT -f "idemu run <id>"`; `idemu build <id>` rebuilds the image to reset it.

## 4. Connect — and the bridge's quirks

```bash
ssh -F environments/<id>/ssh/ssh_config idemu        # root console of the guest
```

The SSH endpoint is a **macOS-side console bridge** (ed25519 key), not the guest's own sshd. What that
means for tooling you write against it:

- **No `scp` / `sftp` / `rsync`** — the bridge blocks them. File transfer exists in the internal
  `idemu/sshshell.py` / `guestfs` helpers; `python3 -m idemu push` / `pull` / `ssh` are not implemented
  in this revision despite the bridge/help text suggesting them. Use the SSH config above for a shell.
- It **does not pipe exec stdin** — `ssh idemu 'cat > f'` writes **0 bytes** (confirmed with both the
  system client and paramiko). Upload tricks that work against a real sshd won't work here. (That is why
  `evocode fw` validates only its *choreography* on a stand; its upload is size-verified and aborts on a
  mismatch, so the bridge limit can't produce a bad install.)
- Our 2026-11-11 guest was minimal — no `/tmp`, `tr` or `head`; recheck the exact firmware's utilities.
- The **diagnostic HSFZ endpoint (6801) is not exposed** — the diagnostic plane isn't reachable from a stand.

## 5. Using the stand to develop evocode

- **Crypto / coding / FSC / catalog logic** → `pytest`, offline; no stand needed.
- **`fw` changes** → exercise the choreography against the bridge with `fw --modern`; confirm the transport
  on a real unit.
- **New HMI plugins, coding / FDL editor, QNX-side programs** → the live-HMI stand (a validated-version SWFL).
- **Diagnostic-plane work** (`hsfz` / `uds` / `write` / `fsc apply` / `root`) → not on IDEmu; a real unit,
  or a mock HSFZ endpoint.

## Notes

- IDEmu license: PolyForm Noncommercial 1.0.0 (personal / research use).
- Keep a known-good HMI/profile baseline and a car-matched environment when they differ.
- Virtual CAN/GPS and host-rendered maps help test UI behavior; they do not verify physical buses,
  BMW navigation, FSC acceptance or the real diagnostic interface.
