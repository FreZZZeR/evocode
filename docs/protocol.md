# Protocol — NBT EVO coding over the wire

> **Language:** English · [Русский](protocol.ru.md)

This is the mechanism the code implements. It is BMW's own protocol, re-expressed here; see
[../CREDITS.md](../CREDITS.md).

## Transport — HSFZ

F/early-G cars speak **HSFZ** over TCP **6801** (not DoIP). A frame is
`u32 payload_len | u16 control | u8 source | u8 target | UDS…`, where `payload_len` counts the bytes
after the control word. control `0x0001` is data, `0x0002` is an ack to skip. Endpoints answer a UDP
`0x0011` broadcast on 6811. Routing is the **target** byte: `0xF4` tester, `0x10` gateway, `0x63`
the NBT EVO head unit. (`evocode/hsfz.py`)

## Identity — the SVK

Read `22 F1 01` and decode it (`evocode/uds.py`): it lists each software unit as an 8-byte SGBM id
(class, id, version). The **BTLD** (bootloader) id selects the coding signing key; the **CAFD**
(coding dataset) id selects the bit layout. Everything keys off these two — never assume them.

## The coding signature — BMWSigVerify

Coding lives in **datagroups** `0x3000…0x300F`; the **signature** is datagroup `0x3010`. The head
unit re-verifies the signature at every boot, so a durable edit must recompute it
(`evocode/coding.py`):

1. `digest = MD5( concat of datagroups 0x3000…0x300F )`.
2. `s = (int(digest, little))^d mod N` — raw RSA with the recovered private exponent, `e = 3`.
3. store `wordswap(s)` (each 32-bit word byte-reversed) in `0x3010`, prefixed by a big-endian 32-bit
   word count.

Verification runs it forwards with the public modulus. The verifier needs only the modulus; signing
needs the private exponent, recovered from your own PSdZData.

## The durable write — UDS choreography

```
10 03                 extendedDiagnosticSession
10 41                 codingSession
27 01 -> seed         SecurityAccess requestSeed (level 01)
27 02 <key>           sendKey = L3 handshake over the seed (evocode/l3.py)
2E 30 00 <bytes>      write each changed datagroup …
2E 30 10 <sig>        … signature datagroup LAST
31 01 0F 01           CheckCodingSignature — must pass, or abort before the CPS
2E 37 FE <cps>        Coding Production Stamp
11 01                 hard reset; the HU reboots and re-verifies
```

SecurityAccess here is the shared **L3** construction (the same key unlocks flashing at level 11):
`MD5([UserID][Controller][seed])` signed raw-RSA `e=3` little-endian, word-count prefix +
word-swapped signature.

## Reverting

A read backup is already correctly signed (the car produced it). Writing it back is a clean revert.
`evocode write` defaults to a dry run, verifies the signature locally first, and on `--commit` refuses
unless the connected VIN matches `NBTEVO_OWN_VIN`.
