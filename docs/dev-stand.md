# Dev stand (IDEmu) — a test environment for the package

> **Language:** English · [Русский](dev-stand.ru.md)

A **dev stand** runs an NBT EVO head unit's own software under emulation, so you can test changes to
evocode, write new tooling for it, or develop user programs against the real QNX/HMI — without a car. It
uses [IDEmu](https://github.com/herrbimmer/IDEmu) (QEMU-based, macOS; License: PolyForm Noncommercial —
personal / research use). The stand is a *developer convenience*, not part of evocode; the steps below
distill a working setup and, just as importantly, its boundaries.

To *use* a stand to rehearse the blobB swap and validate `fw`, see [testing.md](testing.md). This page is
about *standing one up* and what it can develop.

## What a stand can and can't develop

| ✅ On the stand | ❌ Not on the stand |
|---|---|
| `fw` **choreography** (remount / backup / rename-over / chmod) on real QNX, via `fw --modern` | The **diagnostic plane** (HSFZ 6801): `write`, `fsc apply`/`read`, `root` — IDEmu doesn't expose it |
| HMI plugins, the coding / FDL editor, QNX-layer programs (SSH / FS / services / perms / slog) | `fw`'s file **transport** — the console bridge drops exec stdin (see §4) |
| The UI side of aftermarket plugins (e.g. Android Auto UI) | Media / audio, USB, maps / navigation, network, live AA / CarPlay |

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
`omap5-uevm` ARM target, per its `src/qemu/README.md`. `<IDEmu>` below is the cloned repo path.

```bash
git clone --depth 1 https://github.com/herrbimmer/IDEmu && cd IDEmu
mkdir -p bin
zsh src/glhost/build.sh                        # -> bin/glhost (OpenGL renderer; runs headless)

W="$HOME/idemu-qemu"; mkdir -p "$W"; cd "$W"    # QEMU build tree, kept outside the repo
curl -fsSL -o qemu-11.1.2.tar.xz https://download.qemu.org/qemu-11.1.2.tar.xz
tar xf qemu-11.1.2.tar.xz; SRC="$W/qemu-11.1.2"
cp "$OLDPWD/src/qemu/omap5-uevm.c" "$SRC/hw/arm/omap5-uevm.c"
( cd "$SRC" && patch -p1 < "$OLDPWD/src/qemu/qemu-v11.1.2-idemu.patch" )   # patches Kconfig + meson.build
mkdir -p "$W/build" && cd "$W/build"
"$SRC/configure" --python="$(command -v python3.13)" --target-list=arm-softmmu \
  --disable-docs --disable-guest-agent --disable-tools --disable-gtk --disable-sdl \
  --disable-vnc --disable-curses --disable-rust --disable-user --disable-linux-user \
  --disable-bsd-user --without-default-features --enable-tcg
ninja qemu-system-arm
# macOS SIGKILLs an in-place overwrite of a running binary — copy to a new name, then mv:
cp qemu-system-arm "<IDEmu>/bin/qemu-system-arm.new"
mv "<IDEmu>/bin/qemu-system-arm.new" "<IDEmu>/bin/qemu-system-arm"
"<IDEmu>/bin/qemu-system-arm" -M help | grep omap5      # expect: omap5-uevm
```

## 2. Firmware — bring your own SWFL

IDEmu builds the disk image from **SWFL** out of **your own licensed full PSdZData** (nothing is shipped).
For NBT EVO (iDrive6) it needs **three containers, all the same version**:

| Role | File | ~size |
|---|---|---|
| OS | `swfl_0000271a.bin.<version>` | ~880 MB |
| HMI | `swfl_00002720.bin.<version>` | ~710 MB |
| brand | `swfl_00002719.bin.<version>` | ~480 MB |

**The version-pin gotcha — read this.** IDEmu's graphics shim is hardcoded to specific HMI build(s) (a
validated `HmiMain3D` hash in its `idemu/data/known_hmi.json`). So:

- For a **live HMI** (on-screen menu — plugin / UI work): all three roles must be a build IDEmu
  *validates*, or the HMI never finishes (boot stalls ~90 %) and `NBTCarHU` (gated behind the HMI) never
  starts — though the **system layer** (QNX / SSH / coding) is up.
- To **match a specific car** (e.g. an FSC rehearsal): use that car's version — then expect the system
  layer only, no rendered HMI. That is the emulator's limit, not your change.

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

- **No `scp` / `sftp` / `rsync`** — they are blocked; the bridge's file path is `idemu push` / `idemu pull`.
- It **does not pipe exec stdin** — `ssh idemu 'cat > f'` writes **0 bytes** (confirmed with both the
  system client and paramiko). Upload tricks that work against a real sshd won't work here. (That is why
  `evocode fw` validates only its *choreography* on a stand; its upload is size-verified and aborts on a
  mismatch, so the bridge limit can't produce a bad install.)
- The guest is minimal — no `/tmp`, a reduced util set (no `tr` / `head`). Don't depend on them.
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
- Two stands are handy: a validated-version one for HMI / plugin work, and a car-version one for the
  system-layer rehearsal.
- A stand reproduces the unit's software, not its wiring: anything that needs the car's buses, media,
  network, or diagnostic interface stays for the car.
