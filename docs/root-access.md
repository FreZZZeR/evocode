# Root access (OPT_DEBUG) — feasibility and design

> **Language:** English · [Русский](root-access.ru.md)

**Short answer: yes, enabling root/SSH fits this project cleanly** — it is the *same transport and
the same key* the toolkit already uses for coding and FSC. It is **not** an SSH operation and does
not presuppose SSH; it is a diagnostic-plane flash that *produces* SSH. The SWDL file-copy flash
choreography is implemented in ``swdl.py``; the OPT_DEBUG edit and CLI are in ``root.py`` / ``cli.py``.

## What "root access" means on an NBT EVO

The head unit has a developer interface — SSH (22), telnet (23), qconn (8000) — that comes up as
**root** over OBD/ENET. On a stock unit it is off. It is gated by one setting in the unit's startup
config, `/fs/sda0/opt/sys/etc/starter.cfg`: the **OPT_DEBUG** service, shipped `STOP`, flipped to
`RUN`. Enable it, reboot, and the dev ports are open.

That is the root you need for the firmware-file steps elsewhere in this project — installing the
blobB-patched `NBTCarHU` (FSC owner-CA), or an aftermarket plugin. See the two-plane model in
[../AGENTS.md](../AGENTS.md) (§1): coding and FSC ride the diagnostic plane and never
need SSH; only pushing *files* onto the unit's partitions does — and OPT_DEBUG is how you open that.

## Why it does not need SSH to begin with

Enabling OPT_DEBUG is a **flash over the diagnostic channel**, identical in shape to what evocode
already does:

```
ENET → HSFZ (TCP 6801) → enter flash bootloader
   → UDS SecurityAccess 0x27 Level 3  (BMWSigVerify: sign the seed with the owner's L3 key)
   → SWDL "no-signature file-copy" (LIVE-DIRECT) of a patched starter.cfg  (OPT_DEBUG STOP→RUN)
   → finalize → reboot → sshd(22)/telnetd(23)/qconn(8000) up as root
```

The "no-signature file-copy" container writes the file without a signature record, so the SWDL
signature check does not apply to it — which is why a *patched* config can be installed at all. The
L3 SecurityAccess is the same seed/key flow as a coding write; the key is the operator's **own**
car key, which evocode already recovers (`recover-key`, kind `l3`).

## What it builds on (all present in evocode)

| Needed | Status in evocode |
|---|---|
| HSFZ transport, discovery | ✅ `hsfz.py` |
| UDS session / SecurityAccess / routines | ✅ `uds.py` |
| L3 seed signing (BMWSigVerify, e=3) | ✅ `l3.py` |
| Recover the owner's L3 key from their PSdZData | ✅ `keys.py` (`recover-key --kind l3`) |
| **Flash bootloader entry + SWDL no-signature file-copy choreography** | ✅ `swdl.py` |
| **A version-matched patched `starter.cfg` built from the owner's own flash** | ✅ `root.py` (`root prepare`) |

So the capability is mostly *wiring together primitives that already exist* plus one new module
(the SWDL file-copy flow) and one data step (produce the patched `starter.cfg`).

## The hard constraint: version-match the config

`starter.cfg` is **build-specific**. A wrong-version config fails the **next boot** (the unit boots
`starter.cfg`; a bad one leaves it unable to start the HMI, or to boot at all). Generic one-size
unlockers inline a single config (e.g. one valid across the NBT-EVO `007.xxx` family) and explicitly
refuse other lines — which is exactly the trap this project avoids elsewhere. The clean-room,
provenance-correct way, consistent with `build-catalog` and `recover-key`:

- Take the stock `starter.cfg` from the operator's **own** unit (read it) or their **own** PSdZData
  flash container for this exact BTLD/SVK.
- Make the minimal `OPT_DEBUG STOP→RUN` edit, byte-length-preserving, to *that* file.
- Install it with the no-signature file-copy; keep the untouched original as the revert.

This unit (for reference) is software line **006.016.002** (the SWFL/BTLD line — distinct from the CAFD *coding* version `006.031.014`; separate version axes) — *not* in the `007.xxx` family a generic
unlocker targets, so a generic inlined config would be the wrong file. The config must come from this
unit's own flash.

## Risk and reversibility

- **Brick class**: boot-config. A bad write fails the next boot. Mitigation: version-match; dry-run;
  run the write **detached** (so an SSH/terminal drop can't tear it); keep the stock config.
- **Reversible**: re-flash the byte-exact stock `starter.cfg` by the same path (a `--revert`). The
  dev interface lives independently of the HMI, so even a unit that won't bring up the HMI is still
  reachable to revert — *once OPT_DEBUG is on*. Before it is on, there is no SSH backstop, only
  serial/eMMC. Treat the very first enable as the highest-risk step.
- **Gating**: same as `write`/`fsc apply` — `NBTEVO_OWN_VIN` consent gate, dry-run by default,
  `--commit` re-checks VIN. A flash additionally requires the battery on a charger.

## Usage

```bash
evocode root status  --host 169.254.199.99                 # is OPT_DEBUG on? are 22/23/8000 open?
evocode root prepare --starter-cfg stock.cfg -o patched.cfg # STOP→RUN edit + keep stock
evocode root enable  --host 169.254.199.99 --l3-key l3.json --starter-cfg stock.cfg  # DRY RUN
evocode root enable  --host 169.254.199.99 --l3-key l3.json --starter-cfg stock.cfg --commit
evocode root revert  --host 169.254.199.99 --l3-key l3.json --stock stock.cfg   # re-flash stock cfg
```

`evocode/swdl.py` handles flash bootloader entry + SWDL no-signature file-copy.
`evocode/root.py` handles the `starter.cfg` `STOP↔RUN` edit and container building.
`root enable/revert` reuse `hsfz`/`uds`/`l3`/`consent`.

## Status

**Implemented.** `swdl.py` (flash choreography) and `root.py` (starter.cfg edit) are written.
The transport, L3 auth and key recovery they depend on are proven on real data. The SWDL flash
module is adapted from the wire protocol observed in `nbt-evo-ssh-unlocker` (attribution in
[../CREDITS.md](../CREDITS.md)). **Not yet validated on a live unit** — the first live run is the
highest-risk step (see Risk and reversibility above). Run detached, have the stock config ready.
