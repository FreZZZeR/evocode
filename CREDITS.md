# Credits and provenance

This is an **independent re-implementation** of BMW's own on-the-wire protocol, licensed under Apache
License 2.0 ([LICENSE](LICENSE), [NOTICE](NOTICE)). No third-party source code is vendored or copied
into this repository; the core is pure Python standard library (`pyproject.toml` declares no runtime
dependencies). Most of it is clean-room — re-derived from protocol facts; where a module was instead
shaped by an existing implementation's *observed behaviour* (not its code), that is called out below
(`swdl.py`).

What it implements is **BMW's own on-the-wire protocol** for the NBT EVO head unit — HSFZ framing,
UDS (ISO 14229) services, the coding datagroup layout, and the `BMWSigVerify` coding-signature
construction. That protocol is a matter of fact about the hardware, established over years of
community reverse-engineering of iDrive systems; this project re-derives and re-expresses it in its
own code and words. The key-recovery path (`recover-key`) likewise reproduces BMW's own PSdZ
key-derivation — the resource-image passphrase and the E-SYS keystore chain — in original code, and
embeds no BMW secret: every key, logo and password is read or derived from the owner's own licensed
install at run time. `build-catalog` likewise decrypts the owner's own CAFD `.caf` (BMW's
CMS-envelope + gzip packaging) with the owner's own keystore key and emits only factual coordinates;
parameter names are not shipped and are authored by the community.

Acknowledgements:

- The broader BMW / iDrive reverse-engineering community, whose published findings make work like
  this possible.
- Prior open-source NBT EVO tooling exists and served as a point of reference for *what the protocol
  does* — not as a source of code. This project shares none of its code and is separately licensed.
- **SWDL flash choreography** (`swdl.py`): the wire-protocol sequence (bootloader entry, transfer-data
  windowing, prog-mode teardown) is adapted from the behaviour observed in
  `nbt-evo-ssh-unlocker/nbt_optdebug_flash.py` — a standalone OPT_DEBUG flasher published without a
  LICENSE file. The implementation here is rewritten to use evocode's own `hsfz`/`uds`/`l3` primitives
  and does not inline keys or version-specific blobs.

Reference data (the per-CAFD bit **catalogs**) is **not** shipped pre-derived from anyone else's
work. It is generated from **your own** PSdZData with the catalog builder (see
[catalogs/README.md](catalogs/README.md)), so every shipped catalog traces back to an owner's own
licensed reference files.

If you believe anything here reproduces protected material rather than protocol fact, please open an
issue — correctness and clean provenance are both goals.
