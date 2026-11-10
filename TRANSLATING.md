# Translating the documentation

The documentation is written in **English, and English is the source of truth.** Translations are
welcome and live *beside* each English file. This page is the whole convention — there is no build
step and no framework.

## How translations are stored

A translation is a sibling file with a language code before the `.md` extension:

```
README.md            →  README.ru.md      README.de.md
AGENTS.md            →  AGENTS.ru.md
docs/scope.md        →  docs/scope.ru.md
catalogs/CONTRIBUTING.md → catalogs/CONTRIBUTING.ru.md
```

- **Code**: a short BCP-47 tag — `ru`, `de`, `fr`, `zh-CN`. Lowercase language, optional region.
- GitHub renders `*.ru.md` like any Markdown file; no tooling is required.
- `LICENSE` and `NOTICE` are **never** translated — the Apache text is canonical as published. A
  translation may be added as a convenience copy (e.g. `NOTICE.ru.md`) clearly marked "informational,
  the English LICENSE governs".

## Language switcher

Every file that has (or may have) a translation starts with one nav line, right after the H1:

```markdown
# Title

> **Language:** English · [Русский](FILE.ru.md) · [Deutsch](FILE.de.md)
```

In a translated file the line is in that language and points back to English and to siblings:

```markdown
# Заголовок

> **Язык:** [English](FILE.md) · Русский
```

Link only the translations that actually exist. When you add a language, add its link to the nav
line of each file you translate.

## What to translate, and what to keep verbatim

- **Translate** prose, headings, table text, and explanations.
- **Keep verbatim** (do not translate): code blocks, commands, flags, file paths, identifiers,
  datagroup/byte/mask values, hex, UDS service ids, key names, `evocode` subcommand names. A reader
  of any language runs the same `evocode sign --set 0x3000,107,0x80,0x80,7`.
- Keep relative links pointing at the **same language** where a translation exists (a Russian doc
  links to `scope.ru.md`), and fall back to the English target where it doesn't.

## Partial languages are fine

You do not have to translate everything. A language that covers only `README` and `AGENTS` is useful
and welcome. Untranslated pages fall back to English via the nav line. English always wins on a
conflict: if you change an English doc, its translations may lag — that is expected, not a bug.

## Adding a language — checklist

1. Pick the code (`de`, `fr`, …).
2. Copy the English file you're translating to `FILE.<code>.md` and translate the prose.
3. Add the language's nav line (and add your link to the English file's nav line).
4. Keep all code/commands/identifiers byte-for-byte.
5. Open a PR; say which pages you covered and which fall back to English.

The first language after English is **Russian (`ru`)**, already present as `*.ru.md`.
