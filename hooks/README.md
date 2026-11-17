# Guardrail hooks (mandatory)

Committed git hooks that refuse to **publish** private data and run the tests before a push.
Shared verbatim across `evocode`, `nbtevo-diag`, `nbtevo-id6-apps` (only `run-tests.sh` differs).

## Activate (once per clone)

```sh
git config core.hooksPath hooks
```

That is the only setup. Hooks are not auto-enabled on clone (git security), so this line is
required — it is also listed in each repo's local `AGENTS.local.md`.

## What it blocks

- **pre-commit** — refuses to commit if the staged change contains the owner's car VIN, the
  work username/email, or an absolute home-directory path; also refuses the work git identity.
- **pre-push** — re-scans the whole tracked tree, refuses any commit being pushed that is
  authored with the work identity, and runs `run-tests.sh` (push is blocked if tests fail).

The content scan always excludes this `hooks/` directory, so the literal patterns in
`_guardrail.sh` never match themselves. Tune the patterns in `_guardrail.sh` (`GUARD_RE`).

## Bypass

`git commit --no-verify` / `git push --no-verify` skip hooks. Don't — that is the whole point.
