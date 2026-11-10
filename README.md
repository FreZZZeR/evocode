# nbt-evo-coding (`evocode`)

> **Language:** English · [Русский](README.ru.md) — see [TRANSLATING.md](TRANSLATING.md) to add one.

Read, decode, sign and write the **coding** of a BMW **NBT EVO** head unit over ENET/HSFZ —
a small, dependency-free Python library and CLI.

> 🤖 **Driven by an AI agent or a technical operator at the car — not a self-serve consumer app.**
> Each command assumes someone who can read a UDS negative-response code, connect ENET and judge
> whether a change behaved on the unit. Start at **[AGENTS.md](AGENTS.md)**: the operating model, the
> two access planes (why coding and FSC need **no SSH**), and the risk map.

> **Scope: NBT EVO (QNX) only** — iDrive **ID4 / ID5 / ID6**. This is **not** for MGU / **ID7+**
> (BMW OS 7/8, Linux); that is a different head unit and a different platform. See
> [docs/scope.md](docs/scope.md).

> ⚠️ **Writing coding can brick or degrade your head unit.** Reads are safe; writes are gated,
> default to a dry run, and refuse unless the connected car's VIN matches the one you own. Always
> back up first, verify offline, and keep the backup as your revert. Use only on a car you own.

## Status

Early (0.1), but validated against real BMW data — not just internally:

- **Transport, `BMWSigVerify` signature, read, verify, sign** — the signer reproduces a real car's
  own NCD signature byte-for-byte ([examples/a4a.md](examples/a4a.md)).
- **Write** — full choreography, **dry-run by default**, gated on your VIN.
- **`recover-key`** — recovers your own NCD/L3 signing key from your own PSdZData; reproduces the
  reference key exactly (needs the `crypto` extra).
- **`decode`** — reads a backup against a per-CAFD catalog.
- **`build-catalog`** — decrypts your own `.caf` (CMS + gzip) and writes a full coordinate skeleton
  (1469 coordinates for CAFD `00001EF6`; A4A/CarPlay verified). Parameter **names** are a community
  overlay (BMW strips them); no pre-derived BMW data is shipped — the catalog in `catalogs/` is the
  named starter (A4A, CarPlay today), while the full 1469-coordinate skeleton is what `build-catalog`
  emits from your own data. Needs the `crypto` extra + an `openssl` binary.

## Install

```bash
pip install -e .          # pure stdlib; no runtime dependencies
```

## Quickstart

```bash
export NBTEVO_OWN_VIN=WBA........K465354      # the VIN of the car you own

# 1. Identify the unit (reads the SVK: BTLD + CAFD + VIN). Never assume these.
evocode identify --host 169.254.199.99

# 2. Back up the live coding to an NCD (do this every time — it is also your revert).
evocode read --host 169.254.199.99 -o backup.ncd

# See what your coding currently says, against a catalog.
evocode decode --ncd backup.ncd --catalog catalogs/cafd_00001ef6.json

# 3. Recover YOUR coding signing key from YOUR PSdZData (one time), then prove the signer
#    reproduces the car's own signature byte-for-byte.
evocode recover-key --btld 00001FFD --psdzdata /path/to/psdzdata -o key.json
evocode verify --ncd backup.ncd --key key.json

# 4. Edit a coding byte and re-sign offline (verified locally before anything goes to the car).
evocode sign backup.ncd modified.ncd --key key.json --set 0x3000,107,0x80,0x80,7

# 5. Write it (DRY RUN unless --commit; --commit re-checks VIN and the signature first).
evocode write --host 169.254.199.99 --ncd modified.ncd --key key.json --l3-key l3.json --commit

# 6. Confirm: read back and diff, and watch the HMI come up. Revert = write backup.ncd.
evocode read --host 169.254.199.99 -o after.ncd
```

## How it works (one paragraph)

The NBT EVO re-verifies a cryptographic signature over its coding **at every boot**. A raw byte
edit reverts unless you also recompute that signature with the key the bootloader (BTLD) selects.
So a durable change is: edit the datagroups, recompute the `BMWSigVerify` signature (MD5 digest,
RSA `e=3`, BMW's word-swapped big-number encoding, stored in datagroup `0x3010`), then write both
through the authenticated UDS coding session (SecurityAccess L3, `2E` per datagroup with the
signature last, `CheckCodingSignature`, CPS, reset). The maths is in
[`evocode/coding.py`](evocode/coding.py); the wire flow in [docs/protocol.md](docs/protocol.md).

## Catalogs — how a raw coordinate becomes a readable parameter

`0x3000,107,bit7` means nothing until a **catalog** says it is `A4A` on your CAFD. Catalogs are
per-CAFD maps built from **your own** PSdZData with `evocode build-catalog` (see
[catalogs/README.md](catalogs/README.md)). This keeps provenance clean and lets the community add
units by contributing catalogs, not code — the same code serves every NBT EVO build. To add or name
a parameter, follow **[catalogs/CONTRIBUTING.md](catalogs/CONTRIBUTING.md)** (for people and agents).

## FSC activations (owner-CA)

Separate capability from coding: an FSC (CarPlay, nav, A4A…) is verified against a single modulus
(**blobB**) in the firmware (`e=3`/MD5), not against BMW's coding key. On a car you own you can move
that trust to your **own** key and mint FSCs under it:

```bash
evocode fsc keygen -o owner.json --blobb owner_blobB.bin           # your e=3 anchor
evocode fsc find-blobb NBTCarHU                                    # locate the installed anchor + fingerprint
evocode fsc whosigned --fsc a.fsc --fsc b.fsc --recover           # whose anchor is on a used unit?
evocode fsc patch-blobb NBTCarHU --key owner.json --backup stock_blobB.bin -o NBTCarHU.patched
evocode fsc mint --key owner.json --appno 0x0143 -o carplay.fsc   # CarPlay (VIN-generic)
evocode fsc apply --fsc-dir ./fscs                                # dry-run; add --host/--l3-key/--commit to write
```

`verify` / `parse` / `fingerprint` / `from-log` round it out. Installing the patched `NBTCarHU` is a
firmware-replace step (brick-risk): back up the stock anchor (`--backup`) and keep it to revert.
That step needs a root shell on the unit — see **[docs/root-access.md](docs/root-access.md)** for how
root/SSH is enabled (OPT_DEBUG), why it's an ENET flash and not itself an SSH operation, and its risks.

## License & provenance

Apache License 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE). Apache 2.0 was chosen over MIT
for two protections it builds in, both in its **Section 3**:

- **Automatic patent license — protects users.** Every contributor grants a perpetual, royalty-free
  patent license over their contributions, so you can use the project without a later patent claim
  from the people who wrote it. (MIT is silent on patents; Apache grants them.)
- **Patent-retaliation "self-destruct" — protects the project and community.** If anyone starts
  patent litigation claiming this work infringes, their patent license to it **terminates
  automatically** as of the day they file — so patents can't be weaponised against the community
  while still enjoying the grant.

Apache's retaliation is scoped to **patent** litigation over this work; it does not revoke rights
for copyright or unrelated disputes. Broader defensive termination would be a non-standard add-on
on top of the canonical license — open an issue to discuss rather than editing `LICENSE`.

This is an independent re-implementation that vendors no third-party code — mostly clean-room, with
one module (`swdl.py`) shaped by an existing flasher's observed wire behaviour; see
[CREDITS.md](CREDITS.md).
