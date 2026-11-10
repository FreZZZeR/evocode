# Catalogs — per-CAFD bit maps

> **Language:** English · [Русский](README.ru.md)

**Adding or naming a parameter?** See **[CONTRIBUTING.md](CONTRIBUTING.md)** (people and agents).

A **catalog** turns a raw coding coordinate (`datagroup, byte, mask, shift`) into a human-meaningful
parameter name and value set, for one **CAFD** (coding dataset). The code is the same for every NBT
EVO; a new car is supported by adding a catalog, not by changing code.

## Provenance

Catalogs are derived from **your own** PSdZData with `evocode build-catalog`. The project
ships no catalog pre-derived from anyone else's data — this keeps the data's provenance as clean as
the code's (see [../CREDITS.md](../CREDITS.md)). If you contribute a catalog, generate it from your
own licensed reference files and say which CAFD id and version it came from.

## Format (draft)

One JSON file per CAFD, `cafd_<id>.json`:

```json
{
  "cafd": "00001EF6",
  "version": "006.031.014",
  "parameters": [
    {
      "name": "A4A",
      "datagroup": "0x3000",
      "byte": 107,
      "mask": "0x80",
      "shift": 7,
      "values": { "0": "nicht_aktiv", "1": "aktiv" }
    }
  ]
}
```

- `datagroup`/`byte`/`mask`/`shift` address exactly what `evocode sign --set` edits.
- `values` maps the decoded integer to a label.
- A reader (`evocode decode`) applies a catalog to a read NCD to print current values; the
  signer already accepts the same coordinates directly.

## Status

`decode` and `build-catalog` are implemented. `evocode build-catalog --caf <your .caf> …` decrypts
your own CAFD (CMS + gzip, using your keystore's Codier-Encrypt key) and writes a **full skeleton** —
every coordinate, mask and default (1469 for CAFD `00001EF6`). Parameter **names** are what you add
on top: BMW ships the CAFD with names stripped, so they come from firmware tokens / community
authoring. The read / sign / write core needs no catalog — you can address coordinates directly too.
