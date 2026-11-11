# Agent / operator guide

> **Language:** English · [Русский](AGENTS.ru.md)

**This toolkit is built to be driven by an AI agent or a technical operator sitting at the car — not
as a self-serve consumer app.** Every command assumes someone who can read a UDS negative-response
code, connect ENET, supply their own PSdZData, and judge whether a change behaved on the unit. There
is no "one button". If you are an agent, read this file fully before you act; if you are a person,
this is also the honest map of what each command costs.

Why it reads this way: a coding/FSC/firmware change on a live head unit is an experiment on one
specific unit. Whether it takes, does nothing, or freezes the HMI depends on the hardware fitted and
the exact software/CAFD build — a clean signature and a clean read-back do **not** settle it. That
judgement is the operator's job; the tools only make each step safe to try and cheap to revert.

---

## 0. Preconditions — confirm before any write or key recovery

In the operator's own words, confirm all three:

1. **They own the car** (or have the owner's explicit, informed permission).
2. **They are connected locally** — OBD-II/ENET to *that* car, not remote, not someone else's unit.
3. **There is a backup** of whatever you are about to change. If not, take one first: every write
   path has a read path (`read`, `fsc parse`, `patch-blobb --backup`).

The consent gate enforces this for you: write/apply refuse unless `NBTEVO_OWN_VIN` is set to the VIN
of the car the operator owns, and (on `--commit`) that VIN matches the VIN read back from the
connected car. Do not route around it — if it blocks you, that is the design working; explain it.

```bash
export NBTEVO_OWN_VIN=<your VIN>
```

---

## 1. Two access planes — the mental model that answers "do I need SSH?"

Almost every mistake here comes from confusing these two. They are different wires, different auth,
different risk.

| | **Diagnostic plane** | **Filesystem plane** |
|---|---|---|
| Transport | ENET → HSFZ (TCP **6801**, discovery UDP 6811) | **SSH** / qconn (dev shell, root) |
| Auth | UDS **SecurityAccess L3** (seed/key, `l3.py`) | root shell on the dev interface |
| What it does | reads, coding, FSC, flash | replaces files on the unit's partitions |
| Needs SSH? | **No** | — |
| evocode commands | `identify` `read` `decode` `verify` `sign` `write` `recover-key` `build-catalog` `fsc apply`/`read`/`disable` `root` | `fw pull`/`install`/`revert` — installing `NBTCarHU.patched`, a plugin |

**So: coding and FSC never touch SSH.** They ride the same diagnostic channel E-Sys uses. SSH is
only for pushing firmware *files* onto the unit (the blobB swap's `NBTCarHU`, or an aftermarket
plugin). And getting SSH in the first place — enabling OPT_DEBUG — is itself a *diagnostic-plane
flash*, not an SSH operation (see [docs/root-access.md](docs/root-access.md)). The dev interface is a
**separate Ethernet address** from the diagnostic one; on a stock unit port 22 is closed until
OPT_DEBUG is enabled.

The head unit is identified and reached by its **BTLD** and **CAFD** ids, read live from the SVK
(`22 F1 01`) — never assumed. Which signing key applies, which coding layout to decode, which
container fits: all key off those two ids *and their versions*. Read the SVK first (`identify`).

---

## 2. Reads are free; writes are not

- **Reading** — `identify`, `read`, `decode`, `fsc read`/`parse`/`whosigned`/`find-blobb` — is safe and
  reversible. Do it liberally to orient yourself.
- **Writing** — `write`, `fsc apply`, `patch-blobb` + install — can brick or degrade the unit.
  Always: read + back up first, verify the artifact offline, confirm the operator is ready (parked,
  battery on a charger so a flash can't lose power), then commit.
- Both write paths default to **dry-run**. `--commit` re-checks the VIN and re-verifies the
  signature before a single byte goes to the car.

---

**Rehearsing without a car.** Part of the firmware-file (filesystem-plane) work can be tried in an
emulator first: [IDEmu](https://github.com/herrbimmer/IDEmu) boots an NBT EVO head unit's own software
under QEMU on macOS, with SSH and a coding editor. Useful to confirm a patched `NBTCarHU` boots, the
HMI comes up, SSH works and the coding is intact *before* you go to the car. It does **not** expose
the HSFZ diagnostic endpoint (TCP 6801), so evocode's diagnostic-plane commands
(`read`/`write`/`sign`/`fsc apply`/`root`) can't be driven against it, and maps/nav don't run — it
complements on-car testing, it doesn't replace it. (License: PolyForm Noncommercial.) A step-by-step
rehearsal — what it can and can't test, the flow, pass/fail — is in [docs/testing.md](docs/testing.md).

## 3. Risk map — the places this can go wrong, and the guard for each

| Action | What can go wrong | Guard | Revert |
|---|---|---|---|
| `write` (coding) | A valid-in-the-map bit can still freeze/blank the HMI on *this* unit | dry-run, VIN gate, `verify` offline first, change one thing at a time and log it | write back `backup.ncd` |
| `sign` with wrong key | Unsigned/mis-signed NCD reverts on next boot (silent no-op) | `recover-key` from the operator's own PSdZData, then `verify` reproduces the car's own signature byte-exact before trusting it | — (nothing written) |
| `fsc apply` | Store-RCO selector (`0x07`) is read from one unit's ODX; another build may differ → `requestOutOfRange` | dry-run read-back, `--store-rco`/`--base32` escape hatches, L3 gate | `DisableFSC` per appno, or restore stock anchor |
| `patch-blobb` + install `NBTCarHU` | Firmware-file replace over SSH — brick-risk | `evocode fw install` encodes the safe sequence (keeps `NBTCarHU.orig`, uploads to a temp, rename-over a new inode — never edits in place), dry-run by default; dev/SSH lives independently of the HMI so a dead HMI is still recoverable | `evocode fw revert` (restores `.orig`) + HMI restart |
| OPT_DEBUG enable (root) | SWDL flash of `starter.cfg` — wrong-version cfg fails the **next boot** | version-match the cfg to the unit's own flash; dry-run; run detached so an SSH drop can't tear the write | re-flash stock `starter.cfg` (`--revert`); serial/eMMC is the backstop. See [docs/root-access.md](docs/root-access.md) |

**Version-variance gotchas** — the numbers are per-build; the methods transfer, the constants you
re-verify against the unit's SVK:

- **SREC width**: real NCDs are **S2** (24-bit address), not only S3. `srec.py` handles S1/S2/S3 and
  preserves the trailer verbatim — a byte-exact round-trip is the check that it parsed right.
- **blobB struct**: this build wraps the anchor in `{ver=1, e=3, len_words=32, modulus}`; the modulus
  is at **struct+12**. `find-blobb` finds the *code-referenced* struct — do not hand-pick a raw
  high-entropy blob.
- **`.caf` version**: `build-catalog` needs the CAFD `.caf` whose version matches the unit. A
  neighbouring version decrypts but may not map 1:1. Confirm the version from the SVK.
- **openssl `-legacy`**: the second keystore key (Codier-Encrypt) and the CMS decrypt need
  `openssl … -legacy`; without it the P12 load fails silently on new OpenSSL.
- **stripped names**: BMW ships the CAFD with parameter names blanked (`"."`). A coordinate is only
  a number until a catalog names it — see [catalogs/CONTRIBUTING.md](catalogs/CONTRIBUTING.md).

**Key hygiene**: `recover-key` and the L3/NCD keys it produces are secrets. They are the operator's
own car keys — never commit them, never paste their values into a report or a chat, and keep them out
of the repo (`.gitignore` the key files). Reference them by path.

---

## 4. How to drive a coding change (the loop)

```bash
evocode identify --host 169.254.199.99                 # read SVK: BTLD + CAFD + VIN. never assume.
evocode read --host 169.254.199.99 -o backup.ncd       # back up live coding (this is your revert)
evocode decode --ncd backup.ncd --catalog catalogs/cafd_00001ef6.json   # what does it say now?
evocode recover-key --btld 00001FFD --psdzdata /path -o key.json        # one time
evocode verify --ncd backup.ncd --key key.json         # gold check: signer matches the car
evocode sign backup.ncd modified.ncd --key key.json --set 0x3000,107,1,0x80,7   # edit + re-sign offline
evocode write --host 169.254.199.99 --ncd modified.ncd --key key.json --l3-key l3.json   # DRY RUN
evocode write --host 169.254.199.99 --ncd modified.ncd --key key.json --l3-key l3.json --commit
evocode read --host 169.254.199.99 -o after.ncd        # read back + diff; watch the HMI come up
```

Decide *before* the first write what failure looks like (UI doesn't load / freezes / reboot-loops).
On failure: **revert first** (write `backup.ncd`), then investigate. Snapshot logs before the reset —
they likely don't survive it.

## 5. Adding a new coding parameter

When a coordinate isn't named in a catalog yet, you add it to the catalog, not to the code. The
exact procedure for both people and agents (build the skeleton, locate the coordinate, name it,
validate, contribute) is in **[catalogs/CONTRIBUTING.md](catalogs/CONTRIBUTING.md)**.

## 6. Report faithfully

- If a write fails, say so with the actual UDS negative-response code.
- Never report a change as *applied* until you have read it back and a validator confirms it; never
  as *working* until you have seen it behave on the car.
- Say which findings you verified from firmware, which you found by experiment, and which didn't work
  on this unit. If a doc says "not verified", respect it — don't upgrade a plausibility to a proof.
- If a capability isn't implemented yet, say so plainly instead of inventing the missing step. (The
  OPT_DEBUG root flasher now *is* implemented — see [docs/root-access.md](docs/root-access.md) — but it
  is not yet validated on a live unit; report it as that, not as proven.)
