# Worked example — enable A4A (Android Auto) by coding

> **Language:** English · [Русский](a4a.ru.md)

A4A (Android Auto / "Apps") on the NBT EVO is a **coding** change: one bit in datagroup `0x3000`.
This example is validated against a real car (CAFD `00001EF6`, build `006.031.014`, BTLD `00001FFD`):
`evocode`'s signer reproduces E-Sys's own A4A NCD **byte-for-byte, signature included**.

## The coordinate

| parameter | datagroup | byte | mask | shift | off → on |
|---|---|---|---|---|---|
| A4A enable | `0x3000` | `107` | `0x80` | `7` | `0x00` → `0x80` |

Flipping that one bit changes the content, so datagroup `0x3010` (the signature) must be recomputed —
which is exactly what `evocode sign` does.

## Do it

```bash
export NBTEVO_OWN_VIN=<your VIN>

# back up first (this is also your revert)
evocode read --host 169.254.199.99 -o backup.ncd

# enable A4A and re-sign (offline, self-verified)
evocode sign backup.ncd a4a.ncd --key ncd_key.json --set 0x3000,107,1,0x80,7

# rehearse, then write (gated)
evocode write --host 169.254.199.99 --ncd a4a.ncd --key ncd_key.json          # dry run
evocode write --host 169.254.199.99 --ncd a4a.ncd --key ncd_key.json --l3-key l3_key.json --commit
```

Then read back and diff, and watch the HMI come up. If the Android Auto menu doesn't appear, A4A on
this unit usually also needs its **FSC** entitlement (application `0x009C`) — coding is only half of
some features. Revert any time by writing `backup.ncd`.

## Why you can trust the signer

Reproduced from this repo's tests against the real reference NCDs:

```text
re-signed 0x3010 == E-Sys A4A signature (byte-exact): True
whole image       == E-Sys A4A NCD (content):         True
verifies under the car's coding key:                  True
```

Starting from the untouched base coding, applying the A4A edit and re-signing with the car's own
recovered key yields the exact NCD E-Sys produces — the same signature bytes. That is the strongest
check there is that the `BMWSigVerify` implementation in [`evocode/coding.py`](../evocode/coding.py)
matches the head unit's own.
