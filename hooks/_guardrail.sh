#!/bin/sh
# Publication guardrail — shared logic, sourced by pre-commit / pre-push (not a hook itself).
#
# Refuses to publish the owner's car VIN, the work username/email, and absolute private
# paths, and refuses the work git identity. The content scan ALWAYS excludes this hooks/
# directory, so the literal patterns below never flag themselves.
#
# Tune by editing GUARD_RE. Shared verbatim across evocode / nbtevo-diag / nbtevo-id6-apps.

# Extended-regex (ERE) of tokens that must never reach a commit or a push.
GUARD_RE='WBA8F71090K465354|ititov|@ourgapps\.com|/Users/[A-Za-z]'

# Work email domain that must not author commits in these repos.
WORK_EMAIL_RE='@ourgapps\.com'

_guard_die() {
    printf '\n\033[1;31mx GUARDRAIL: %s\033[0m\n' "$1" >&2
    [ -n "$2" ] && printf '%s\n' "$2" >&2
    exit 1
}

# Refuse the work git identity — commits here must use the personal identity.
guard_check_identity() {
    _email=$(git config user.email 2>/dev/null || true)
    case "$_email" in
        *@ourgapps.com)
            _guard_die "author email is the work identity ($_email)" \
"Use the personal identity for this repo:
    git config user.email igorfrezer@gmail.com
    git config user.name  'Igor Titov'
(see AGENTS.local.md), then retry." ;;
    esac
}

# $1 = label, $2 = text to scan. Dies if any forbidden token appears.
guard_scan_text() {
    _hits=$(printf '%s\n' "$2" | grep -nEi "$GUARD_RE" || true)
    [ -n "$_hits" ] && _guard_die "refusing to publish private data in $1" \
"Matched forbidden tokens (car VIN / work username / work email / private path):
$_hits
Remove them (use \$HOME or ~, not absolute paths). False positive? Edit hooks/_guardrail.sh."
    return 0
}
