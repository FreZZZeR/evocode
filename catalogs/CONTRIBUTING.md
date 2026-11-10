# Adding coding parameters to a catalog

> **Language:** English · [Русский](CONTRIBUTING.ru.md)

A **catalog** is what turns a raw coordinate (`datagroup, byte, mask, shift`) into a named parameter
with readable values, for one **CAFD**. The code is the same for every NBT EVO; you support a new
option, or a new car, by **adding a catalog entry, not by changing code**. This guide is for both
people and agents. Read it before you add an entry — a wrong coordinate writes the wrong bit.

## The one rule: coordinates come from *your own* skeleton; names are the community layer

- The **coordinates** (`datagroup`/`byte`/`mask`/`shift`/`default`) are produced by `build-catalog`
  from **your own** PSdZData. Never hand-type a coordinate you didn't get from a skeleton — that is
  how you end up editing the wrong byte.
- The **names and value labels** are what BMW strips out (the CAFD ships them as `"."`). They come
  from firmware tokens, known community lists, or your own experiment. This is the only part a
  contribution adds on top of the skeleton.
- **Provenance**: generate the skeleton from your own licensed reference files, and record which
  CAFD id + version it came from. Don't paste names from a source whose licence forbids redistribution.

## Field reference

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
      "values": { "0": "nicht_aktiv", "1": "aktiv" },
      "default": 0
    }
  ]
}
```

| field | meaning |
|---|---|
| `cafd` | the CAFD id this catalog is for (from `evocode identify`) |
| `version` | the CAFD version the coordinates were derived from (a different version may differ) |
| `name` | the parameter name you are adding (the community layer) |
| `datagroup` | hex datagroup, e.g. `"0x3000"` — from the skeleton |
| `byte` | byte offset within the datagroup — from the skeleton |
| `mask` | which bits this parameter occupies, hex, e.g. `"0x80"` for bit 7, `"0x03"` for the low two bits |
| `shift` | right-shift to bring the masked field down to a 0-based value: for a single bit N, `shift = N`; for a field, the position of its lowest bit |
| `values` | maps the decoded integer → label (optional; a bare coordinate still decodes to a number) |
| `default` | the CAFD default value (from the skeleton) — optional |

`datagroup`/`byte`/`mask`/`shift` address exactly what `evocode sign --set DG,OFF,VAL,MASK,SHIFT`
writes, so an entry is correct iff `decode` reads back what `sign` would set.

## Procedure (person)

```bash
# 1. Build the skeleton for YOUR CAFD from YOUR PSdZData (coordinates, masks, defaults; names blank).
pip install 'evocode[crypto]'   # needs openssl too
evocode build-catalog --caf /path/psdzdata/swe/cafd/cafd_00001ef6.caf.006_031_014 \
                      --psdzdata /path/psdzdata -o skeleton_00001EF6.json

# 2. Find the coordinate you want to name. Options, best first:
#    - a firmware token / known list gives you datagroup+byte+mask for the option by name;
#    - or experiment: pick a candidate, set it, observe the car, revert (see AGENTS.md §4).
evocode decode --ncd backup.ncd --catalog catalogs/cafd_00001ef6.json   # what's already named

# 3. Add the entry to catalogs/cafd_00001EF6.json (copy a coordinate from the skeleton, add name+values).

# 4. Validate it loads and decodes a real backup to the value you expect.
python -c "from evocode import catalog; catalog.load('catalogs/cafd_00001EF6.json'); print('ok')"
evocode decode --ncd backup.ncd --catalog catalogs/cafd_00001EF6.json --only YOUR_PARAM

# 5. Record provenance (CAFD id+version, how you learned the name) and open a PR.
```

Computing `mask`/`shift`: a single bit N → `mask = 1<<N` (bit 7 = `0x80`), `shift = N`. A multi-bit
field occupying bits 2–3 → `mask = 0x0C`, `shift = 2`, and `values` maps `0..3`.

## Procedure (agent)

Same five steps, with these obligations:

1. **Only use the operator's own skeleton** for coordinates — generate it (`build-catalog`) or ask
   for it; never invent a `datagroup/byte/mask`.
2. **Match coordinate → name** from a firmware token the operator supplied, a licence-clean list, or
   experiment. If you matched by experiment, say so.
3. **Mark confidence.** If you are not sure the name/semantics are right, say "unverified" in the PR
   and keep the `values` conservative (e.g. `{"0":"off","1":"on"}`) rather than inventing BMW's exact
   German token. Do not present a guessed name as authoritative.
4. **Validate before claiming** (step 4 above). Never report an entry as correct until `decode`
   reproduces the expected value from a real NCD.
5. **Provenance in the PR body**: CAFD id + version, and the source of the name.

## Worked example — A4A (the one proven on real data)

Android Auto's coding bit on CAFD `00001EF6`: datagroup `0x3000`, byte `107`, bit 7.

```json
{ "name": "A4A", "datagroup": "0x3000", "byte": 107, "mask": "0x80", "shift": 7,
  "values": { "0": "nicht_aktiv", "1": "aktiv" } }
```

Check it against a backup that has A4A on:

```bash
evocode decode --ncd backup.ncd --catalog catalogs/cafd_00001ef6.json --only A4A
# -> A4A = 1 (aktiv)
```

To flip it, the *same* coordinate drives the signer: `evocode sign backup.ncd out.ncd --key key.json
--set 0x3000,107,0x80,0x80,7`. If `decode` and `sign` agree on the coordinate, the entry is right.
See [../examples/a4a.md](../examples/a4a.md) for the full worked flow.
