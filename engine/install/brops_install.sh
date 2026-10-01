#!/usr/bin/env bash
# brops-install — the one privileged install step (docs/design/DEBIAN_INSTALL_PROVISIONING.md §4).
#
# FIRST INCREMENT: the ACCOUNTS step only (§4 item 1). Nothing else in §4 is implemented here, and
# this file must not be cited for any of it: no anchor, no broker root, no deployment, no proof.
#
# WHY THIS EXISTS
# ---------------
# Until this file the only code that created the seven fixed service principals was a workflow:
# `.github/workflows/ci.yml` ran `useradd` inline. `engine/ci/live/run_ladder_turn.sh` only CHECKS
# them (`FAIL: the account ... is not provisioned`). No command in the product created them, so
# no install could. This is that command, and CI now calls it instead of carrying a parallel
# copy — the accounts a ladder run stands on are the installer's.
#
# THE TABLE, AND WHERE EACH VALUE COMES FROM
# ------------------------------------------
# Names: the `*_USER=` block of `engine/ci/live/run_ladder_turn.sh`.
# Uids:  `DEFAULT_UIDS` in `engine/ci/live/provision_keys.py`, which is not a default in any loose
#        sense — it writes `allowed_broker_uid` and the per-service peer allowlists from those
#        literals, so an account with another uid is an account the kit's own config refuses.
#        `brops-sidecar` is NOT in that table (the ladder kit passes its uid on argv from `id -u`);
#        5003 is the value `ci.yml` used, "the gap in the §0 principal table".
# Gid:   equal to the uid, in a group of the account's own name — what `ci.yml` created.
# Shell: /usr/sbin/nologin — what `ci.yml` created.
# `engine/tests/test_brops_install.py` reads both source files and holds this table to them.
#
# NOT HERE, DELIBERATELY: the supplementary groups `brops-store`, `brops-report`, `brops-ipc`. The
# kit creates those itself as part of its deployment step, and that step is a later increment.
#
# IDEMPOTENT, AND REFUSING RATHER THAN REPAIRING
# ----------------------------------------------
# An account already present with the right uid, primary gid and shell is left alone. One present
# with a different uid, gid or shell is a REFUSAL that names it; so is a uid or gid already held by
# some other name. Nothing is ever modified or deleted: an installer that "fixes" an account it did
# not create is an installer that takes over someone else's. Every account is examined BEFORE the
# first one is created, so a refusal leaves the box exactly as it was.
#
#   sudo bash engine/install/brops_install.sh accounts
#   bash engine/install/brops_install.sh --dry-run accounts      # no root needed, changes nothing
#
# Exit: 0 done (or nothing to do) · 1 refused · 2 usage.
set -euo pipefail

# A root script does not inherit the caller's idea of where `useradd` lives.
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH

SERVICE_SHELL=/usr/sbin/nologin
# Debian's home for a system account that has none. Never created (`--no-create-home`).
SERVICE_HOME=/nonexistent

# name:uid — gid is the uid, the group carries the account's name.
ACCOUNTS=(
  "brops-verifier_broker:5001"
  "brops-challenge:5002"
  "brops-sidecar:5003"
  "brops-supervisor:5004"
  "brops-recorder:5005"
  "brops-signer:5006"
  "brops-executor:5007"
)

usage() {
  cat >&2 <<'EOF'
usage: brops_install.sh [--dry-run] accounts

  accounts    create the fixed service accounts (system users, no login shell, no home)

  --dry-run   print the plan, one line per account — `name uid gid shell` — and change nothing.
              Needs no root. Still examines the box and still refuses a conflicting account.

  --passwd-file F --group-file F
              (only with --dry-run) examine these files instead of the system databases.
EOF
}

DRY_RUN=0
PASSWD_FILE=""
GROUP_FILE=""
STEP=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --passwd-file) [ $# -ge 2 ] || { usage; exit 2; }; PASSWD_FILE="$2"; shift ;;
    --group-file)  [ $# -ge 2 ] || { usage; exit 2; }; GROUP_FILE="$2"; shift ;;
    -h|--help) usage; exit 0 ;;
    accounts)
      [ -z "$STEP" ] || { echo "brops-install: more than one step named" >&2; usage; exit 2; }
      STEP="$1" ;;
    *) echo "brops-install: unknown argument: $1" >&2; usage; exit 2 ;;
  esac
  shift
done
[ -n "$STEP" ] || { usage; exit 2; }

# The alternate databases exist so the refusal logic can be exercised without root and without a
# single real account. They are refused outside --dry-run: a real run that believed a file handed
# to it instead of the system would be an installer told what to see.
if [ -n "$PASSWD_FILE" ] || [ -n "$GROUP_FILE" ]; then
  [ "$DRY_RUN" = 1 ] || {
    echo "brops-install: --passwd-file/--group-file are accepted only with --dry-run" >&2; exit 2; }
  [ -n "$PASSWD_FILE" ] && [ -n "$GROUP_FILE" ] || {
    echo "brops-install: --passwd-file and --group-file must be given together" >&2; exit 2; }
  [ -r "$PASSWD_FILE" ] && [ -r "$GROUP_FILE" ] || {
    echo "brops-install: cannot read $PASSWD_FILE / $GROUP_FILE" >&2; exit 2; }
fi

if [ "$DRY_RUN" != 1 ] && [ "$(id -u)" != "0" ]; then
  echo "brops-install: must run as root (it creates system accounts); use --dry-run to see the plan" >&2
  exit 1
fi

# ----- lookups: one database line, or nothing ------------------------------------------------
# <db: passwd|group> <field: 1 = name, 3 = id> <value>
# The system database is asked by KEY, not enumerated: a box whose accounts come from a directory
# service may refuse enumeration and still answer a keyed lookup. `getent` decides name-or-id by
# whether the key is all digits, so the answer is checked against the field that was asked for.
# Its exit 2 is "no such key"; any other failure is a database that could not be read, and an
# installer that read "absent" out of "unreadable" would create a duplicate.
db_lookup() {
  local db="$1" field="$2" value="$3" file="" out="" rc=0
  case "$db" in passwd) file="$PASSWD_FILE" ;; group) file="$GROUP_FILE" ;; esac
  if [ -n "$file" ]; then
    awk -F: -v f="$field" -v v="$value" '$f == v && !seen { print; seen = 1 }' "$file"
    return 0
  fi
  out=$(getent "$db" "$value") || rc=$?
  case "$rc" in
    0) printf '%s\n' "$out" | awk -F: -v f="$field" -v v="$value" '$f == v && !seen { print; seen = 1 }' ;;
    2) ;;
    *) echo "brops-install: FAILED — getent $db $value exited $rc; the account database is unreadable" >&2
       exit 1 ;;
  esac
}

field() { printf '%s\n' "$1" | cut -d: -f"$2"; }

# ----- the accounts step ----------------------------------------------------------------------
step_accounts() {
  local spec name uid gid line gline other
  local -a refusals=() need_group=() need_user=() plan=()

  # The table itself, before the box: pairwise-distinct uids (§2.6). A collapse written into
  # this file would otherwise surface as a `useradd` error about the second of two names.
  local distinct
  distinct=$(printf '%s\n' "${ACCOUNTS[@]}" | cut -d: -f2 | sort -u | wc -l)
  [ "$distinct" = "${#ACCOUNTS[@]}" ] || {
    echo "brops-install: REFUSED — the account table does not hold pairwise-distinct uids" >&2
    exit 1; }

  for spec in "${ACCOUNTS[@]}"; do
    name="${spec%%:*}"; uid="${spec##*:}"; gid="$uid"
    plan+=("$name $uid $gid $SERVICE_SHELL")

    # -- the group ------------------------------------------------------------------------------
    gline=$(db_lookup group 1 "$name")
    if [ -n "$gline" ]; then
      if [ "$(field "$gline" 3)" != "$gid" ]; then
        refusals+=("group $name exists with gid $(field "$gline" 3), not $gid")
      fi
    else
      other=$(db_lookup group 3 "$gid")
      if [ -n "$other" ]; then
        refusals+=("gid $gid, wanted for group $name, is already held by group $(field "$other" 1)")
      else
        need_group+=("$name:$gid")
      fi
    fi

    # -- the account ----------------------------------------------------------------------------
    line=$(db_lookup passwd 1 "$name")
    if [ -n "$line" ]; then
      if [ "$(field "$line" 3)" != "$uid" ]; then
        refusals+=("account $name exists with uid $(field "$line" 3), not $uid")
      fi
      if [ "$(field "$line" 4)" != "$gid" ]; then
        refusals+=("account $name exists with primary gid $(field "$line" 4), not $gid")
      fi
      if [ "$(field "$line" 7)" != "$SERVICE_SHELL" ]; then
        refusals+=("account $name exists with shell $(field "$line" 7), not $SERVICE_SHELL")
      fi
    else
      other=$(db_lookup passwd 3 "$uid")
      if [ -n "$other" ]; then
        refusals+=("uid $uid, wanted for account $name, is already held by account $(field "$other" 1)")
      else
        need_user+=("$name:$uid")
      fi
    fi
  done

  if [ "${#refusals[@]}" -gt 0 ]; then
    echo "brops-install: REFUSED — nothing was changed. The box already holds:" >&2
    printf '  %s\n' "${refusals[@]}" >&2
    exit 1
  fi

  if [ "$DRY_RUN" = 1 ]; then
    printf '%s\n' "${plan[@]}"
    echo "brops-install: dry run — ${#need_group[@]} group(s) and ${#need_user[@]} account(s) would be created; nothing was changed" >&2
    return 0
  fi

  for spec in ${need_group[@]+"${need_group[@]}"}; do
    groupadd --system --gid "${spec##*:}" "${spec%%:*}"
  done
  for spec in ${need_user[@]+"${need_user[@]}"}; do
    name="${spec%%:*}"; uid="${spec##*:}"
    useradd --system --uid "$uid" --gid "$uid" --no-create-home --home-dir "$SERVICE_HOME" \
      --shell "$SERVICE_SHELL" "$name"
  done

  # Read back what the box now says, rather than trusting two exit codes.
  for spec in "${ACCOUNTS[@]}"; do
    name="${spec%%:*}"; uid="${spec##*:}"
    line=$(db_lookup passwd 1 "$name")
    [ -n "$line" ] && [ "$(field "$line" 3)" = "$uid" ] && [ "$(field "$line" 4)" = "$uid" ] \
      && [ "$(field "$line" 7)" = "$SERVICE_SHELL" ] || {
      echo "brops-install: FAILED — account $name is not uid $uid gid $uid shell $SERVICE_SHELL after creation" >&2
      exit 1; }
    gline=$(db_lookup group 1 "$name")
    [ -n "$gline" ] && [ "$(field "$gline" 3)" = "$uid" ] || {
      echo "brops-install: FAILED — group $name is not gid $uid after creation" >&2
      exit 1; }
    echo "$name $uid $uid $SERVICE_SHELL"
  done
  echo "brops-install: accounts — ${#need_group[@]} group(s) and ${#need_user[@]} account(s) created, the rest already present" >&2
}

case "$STEP" in
  accounts) step_accounts ;;
esac
