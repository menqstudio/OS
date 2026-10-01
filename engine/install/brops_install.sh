#!/usr/bin/env bash
# brops-install — the one privileged install step (docs/design/DEBIAN_INSTALL_PROVISIONING.md §4).
#
# TWO STEPS ARE BUILT: ACCOUNTS (§4 item 1) and ANCHOR (§4 item 2, by running the slice-D tool).
# Nothing else in §4 is implemented here, and this file must not be cited for any of it: no broker
# root, no deployment, no §4.5 proof.
#
# THE ONE ENTRY POINT
# -------------------
# The package's `postinst` runs `brops-install --user "${SUDO_USER:-}"` and nothing else. That
# stepless form means `all`: `accounts`, then `anchor`. Each step can also be named alone.
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
# THE ANCHOR STEP
# ---------------
# It mints nothing itself. It decides WHO the desktop account is and WHERE that account's
# application data directory is, and runs the slice-D tool with exactly those two answers:
#
#   /usr/lib/brops/brops_install_anchor --user <account> --app-data <dir>
#
# Who — the first of these that yields a name, and never a guess:
#   1. a non-empty `--user`;
#   2. `$SUDO_USER`                        (`sudo dpkg -i`, `sudo apt install`);
#   3. `$PKEXEC_UID`, resolved to a name   (a graphical install through polkit);
#   4. the ONLY human account in the passwd database — uid 1000..59999 (Debian's adduser range),
#      a shell that is not `nologin`/`false`, and not one of this installer's own accounts.
#      Zero or several is a REFUSAL that names them.
# A rule that yields a name ends the search: if that name is then refused, nothing later is tried.
# Refused whatever the source: an unknown name, root or any uid 0, and a service account from the
# table above (by name, or by holding one of its uids).
#
# Where — Tauri's `app_data_dir()` for this app: `dirs::data_dir()` joined with the bundle
# `identifier` (tauri 2.11.5 `src/path/desktop.rs`), and on Linux `dirs::data_dir()` is
# `$XDG_DATA_HOME` when that is an absolute path, else `$HOME/.local/share` (dirs 6.0.0
# `src/lin.rs`). The identifier is `apps/desktop/src-tauri/tauri.conf.json`'s, and
# `engine/tests/test_brops_install.py` holds the literal below to that file.
#
# THE LIMITATION, STATED: root at install time cannot know the desktop session's environment. This
# step uses `<home from the passwd database>/.local/share/<identifier>`. A session that sets
# `XDG_DATA_HOME`, or runs with a `$HOME` other than its passwd home, computes a DIFFERENT
# directory; the anchor binds the path as a string, so that launch refuses with "provisioned for a
# different trust store". Such an install must pass `--app-data <dir>` itself. Nothing here can
# detect the mismatch.
#
# If the tool is absent the step REFUSES, non-zero: an install that cannot provision trust must
# fail (§4.5). If the tool fails, this script exits with the tool's own status and runs nothing
# after it.
#
# ROOT: the accounts step refuses a non-root caller itself. The anchor step does not — it creates
# nothing; the tool it runs refuses a non-root caller before it reads or writes anything
# (`posix_install::refuse_unless_root`), and that is the check that counts.
#
#   sudo bash engine/install/brops_install.sh --user alice         # all: accounts, then anchor
#   sudo bash engine/install/brops_install.sh accounts
#   sudo bash engine/install/brops_install.sh --user alice anchor
#   bash engine/install/brops_install.sh --dry-run --user alice    # no root needed, changes nothing
#
# Exit: 0 done (or nothing to do) · 1 refused · 2 usage · otherwise the anchor tool's own status.
set -euo pipefail

# A root script does not inherit the caller's idea of where `useradd` lives — nor its locale: the
# account-name pattern below must mean ASCII.
PATH=/usr/sbin:/usr/bin:/sbin:/bin
LC_ALL=C
export PATH LC_ALL

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

# The bundle identifier: `"identifier"` in apps/desktop/src-tauri/tauri.conf.json.
APP_IDENTIFIER="studio.menq.brops"

# Debian adduser's FIRST_UID..LAST_UID: the accounts a person logs in as.
HUMAN_UID_MIN=1000
HUMAN_UID_MAX=59999

# What this installer will pass on as an account name. Held in a variable because an unquoted
# pattern is expanded by the shell before the match.
ACCOUNT_NAME_RE='^[A-Za-z0-9_.][A-Za-z0-9_.@-]*$'

# The slice-D tool. The variable exists so the tests can name a fake one without root; whoever
# can set a variable in root's environment can already run anything as root.
ANCHOR_BIN="${BROPS_INSTALL_ANCHOR_BIN:-/usr/lib/brops/brops_install_anchor}"

usage() {
  cat >&2 <<'EOF'
usage: brops_install.sh [--dry-run] --user NAME [--app-data DIR] [all]
       brops_install.sh [--dry-run] accounts
       brops_install.sh [--dry-run] [--user NAME] [--app-data DIR] anchor

  all         `accounts`, then `anchor`. Naming no step, with --user, means this.
  accounts    create the fixed service accounts (system users, no login shell, no home)
  anchor      run brops_install_anchor for the desktop account

  --user NAME the desktop account. Empty or absent: $SUDO_USER, else $PKEXEC_UID, else the only
              human account on the box; otherwise refused. Root and service accounts are refused.

  --app-data DIR
              the application data directory, exactly as the application computes it.
              Default: <the account's passwd home>/.local/share/studio.menq.brops — wrong for a
              session that sets XDG_DATA_HOME, which must be given here.

  --dry-run   print the plan and change nothing: one line per account — `name uid gid shell` —
              then `anchor user`, `anchor app-data` and the exact `anchor command`. Needs no root.
              Still examines the box and still refuses.

  --passwd-file F --group-file F
              (only with --dry-run) examine these files instead of the system databases.
EOF
}

DRY_RUN=0
PASSWD_FILE=""
GROUP_FILE=""
STEP=""
USER_GIVEN=0
USER_ARG=""
APP_DATA_GIVEN=0
APP_DATA_ARG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --passwd-file) [ $# -ge 2 ] || { usage; exit 2; }; PASSWD_FILE="$2"; shift ;;
    --group-file)  [ $# -ge 2 ] || { usage; exit 2; }; GROUP_FILE="$2"; shift ;;
    --user)
      # The value may be EMPTY: `postinst` passes "${SUDO_USER:-}", and an empty one means
      # "not named", not a usage error.
      [ $# -ge 2 ] || { echo "brops-install: --user needs a value (it may be empty)" >&2; usage; exit 2; }
      [ "$USER_GIVEN" = 0 ] || { echo "brops-install: --user was given more than once" >&2; usage; exit 2; }
      USER_GIVEN=1; USER_ARG="$2"; shift ;;
    --app-data)
      [ $# -ge 2 ] && [ -n "$2" ] || { echo "brops-install: --app-data needs a directory" >&2; usage; exit 2; }
      [ "$APP_DATA_GIVEN" = 0 ] || { echo "brops-install: --app-data was given more than once" >&2; usage; exit 2; }
      APP_DATA_GIVEN=1; APP_DATA_ARG="$2"; shift ;;
    -h|--help) usage; exit 0 ;;
    accounts|anchor|all)
      [ -z "$STEP" ] || { echo "brops-install: more than one step named" >&2; usage; exit 2; }
      STEP="$1" ;;
    *) echo "brops-install: unknown argument: $1" >&2; usage; exit 2 ;;
  esac
  shift
done
# `brops-install --user <name-or-empty>` is how `postinst` calls this, and it means everything.
# With neither a step nor --user there is nothing to infer.
if [ -z "$STEP" ]; then
  [ "$USER_GIVEN" = 1 ] || { usage; exit 2; }
  STEP=all
fi
# A flag a step would silently ignore is a caller who believes something this run will not do.
if [ "$STEP" = accounts ] && { [ "$USER_GIVEN" = 1 ] || [ "$APP_DATA_GIVEN" = 1 ]; }; then
  echo "brops-install: the accounts step takes neither --user nor --app-data" >&2; usage; exit 2
fi

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

refuse() { echo "brops-install: REFUSED — $*" >&2; exit 1; }

# Every passwd line the box will enumerate. The only-human rule is the one place that has to
# enumerate: it asks "is there exactly one", which no keyed lookup answers. An account a directory
# service will not enumerate is therefore not seen by that rule (and is still resolvable by name).
passwd_enumerate() {
  local out="" rc=0
  if [ -n "$PASSWD_FILE" ]; then
    cat "$PASSWD_FILE"
    return 0
  fi
  out=$(getent passwd) || rc=$?
  [ "$rc" = 0 ] || {
    echo "brops-install: FAILED — getent passwd exited $rc; the account database is unreadable" >&2
    exit 1; }
  printf '%s\n' "$out"
}

# ----- the accounts step ----------------------------------------------------------------------
step_accounts() {
  local spec name uid gid line gline other
  local -a refusals=() need_group=() need_user=() plan=()

  if [ "$DRY_RUN" != 1 ] && [ "$(id -u)" != "0" ]; then
    echo "brops-install: must run as root (it creates system accounts); use --dry-run to see the plan" >&2
    exit 1
  fi

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

# ----- the anchor step ------------------------------------------------------------------------
DESKTOP_USER=""
DESKTOP_UID=""
DESKTOP_HOME=""
DESKTOP_SOURCE=""
APP_DATA=""
APP_DATA_SOURCE=""

# Why <name> <uid> is one of this installer's own accounts, or nothing.
service_account_reason() {
  local spec
  for spec in "${ACCOUNTS[@]}"; do
    if [ "${spec%%:*}" = "$1" ]; then
      echo "$1 is one of this installer's own service accounts"; return 0
    fi
    if [ "${spec##*:}" = "$2" ]; then
      echo "$1 holds uid $2, which is the service account ${spec%%:*}'s"; return 0
    fi
  done
}

# `name:uid` for every account a person logs in as, one per line.
human_accounts() {
  local all pair
  all=$(passwd_enumerate)
  printf '%s\n' "$all" | awk -F: -v lo="$HUMAN_UID_MIN" -v hi="$HUMAN_UID_MAX" '
    $3 ~ /^[0-9]+$/ && $3 + 0 >= lo && $3 + 0 <= hi && $7 !~ /(^|\/)(nologin|false)$/ { print $1 ":" $3 }
  ' | sort -u | while IFS= read -r pair; do
    [ -z "$(service_account_reason "${pair%%:*}" "${pair##*:}")" ] || continue
    printf '%s\n' "$pair"
  done
}

# A path with exactly one spelling: absolute, not `/`, no empty, `.` or `..` component, no
# trailing slash. The anchor binds the application data directory as a STRING.
one_spelling() {
  case "$1" in /*) ;; *) return 1 ;; esac
  # With a slash appended, `/` itself and a trailing slash both show up as an empty component.
  case "$1/" in *//*|*/./*|*/../*) return 1 ;; esac
  return 0
}

# Decide the desktop account, the application data directory, and that the tool is there.
# Changes nothing and runs nothing, so `all` does it BEFORE the accounts step creates anything:
# an install that cannot name its user fails with the box exactly as it was.
anchor_resolve() {
  local name="" source="" line="" uid="" humans="" count=0 reason=""

  if [ -n "$USER_ARG" ]; then
    name="$USER_ARG"; source="--user"
  elif [ -n "${SUDO_USER:-}" ]; then
    name="$SUDO_USER"; source="SUDO_USER"
  elif [ -n "${PKEXEC_UID:-}" ]; then
    [[ "$PKEXEC_UID" =~ ^[0-9]+$ ]] || refuse "PKEXEC_UID is \"$PKEXEC_UID\", which is not a uid"
    line=$(db_lookup passwd 3 "$PKEXEC_UID")
    [ -n "$line" ] || refuse "PKEXEC_UID names uid $PKEXEC_UID, and no account in the passwd database holds it"
    name=$(field "$line" 1); source="PKEXEC_UID"
  else
    humans=$(human_accounts)
    count=$(printf '%s' "$humans" | grep -c . || true)
    if [ "$count" = 0 ]; then
      refuse "no desktop account was named (--user, SUDO_USER and PKEXEC_UID are all empty) and the" \
        "passwd database holds no human account (uid $HUMAN_UID_MIN..$HUMAN_UID_MAX with a login shell)." \
        "Name one: --user <account>. Nothing was changed"
    fi
    if [ "$count" != 1 ]; then
      refuse "no desktop account was named (--user, SUDO_USER and PKEXEC_UID are all empty) and the" \
        "passwd database holds $count human accounts: $(printf '%s' "$humans" | sed 's/^\(.*\):\(.*\)$/\1 (uid \2)/' | paste -sd, - | sed 's/,/, /g')." \
        "Choosing one would be a guess. Name it: --user <account>. Nothing was changed"
    fi
    name="${humans%%:*}"; source="the only human account in the passwd database"
  fi

  # The name goes to `getent`, to awk and onto the tool's command line.
  [[ "$name" =~ $ACCOUNT_NAME_RE ]] \
    || refuse "the desktop account from $source, \"$name\", is not an account name"

  line=$(db_lookup passwd 1 "$name")
  [ -n "$line" ] || refuse "the desktop account from $source, $name, is not in the passwd database"
  uid=$(field "$line" 3)
  [[ "$uid" =~ ^[0-9]+$ ]] || refuse "the passwd entry for $name has a uid that is not a number (\"$uid\")"
  if [ "$name" = root ] || [ "$((10#$uid))" = 0 ]; then
    refuse "the desktop account from $source, $name (uid $uid), is root. An application running as" \
      "root has no trust anchor anywhere on this machine. Name the account a person logs in as:" \
      "--user <account>. Nothing was changed"
  fi
  reason=$(service_account_reason "$name" "$uid")
  [ -z "$reason" ] || refuse "the desktop account from $source: $reason, not an account a person logs in as"

  DESKTOP_USER="$name"; DESKTOP_UID="$uid"; DESKTOP_SOURCE="$source"
  DESKTOP_HOME=$(field "$line" 6)

  if [ "$APP_DATA_GIVEN" = 1 ]; then
    one_spelling "$APP_DATA_ARG" || refuse "--app-data \"$APP_DATA_ARG\" must be an absolute path with no" \
      "empty, \`.\` or \`..\` component and no trailing slash: the anchor binds it as a string"
    APP_DATA="$APP_DATA_ARG"; APP_DATA_SOURCE="--app-data"
  else
    one_spelling "$DESKTOP_HOME" || refuse "the passwd home of $name, \"$DESKTOP_HOME\", is not an" \
      "absolute path with exactly one spelling, so no application data directory can be derived" \
      "from it. Give it: --app-data <dir>"
    APP_DATA="$DESKTOP_HOME/.local/share/$APP_IDENTIFIER"
    APP_DATA_SOURCE="the passwd home of $name; a session that sets XDG_DATA_HOME needs --app-data"
  fi

  if [ ! -e "$ANCHOR_BIN" ]; then
    [ "$DRY_RUN" = 1 ] || refuse "$ANCHOR_BIN is not installed, so trust cannot be provisioned," \
      "and an install that cannot provision trust must fail. Nothing was changed"
    echo "brops-install: dry run — $ANCHOR_BIN is not installed; a real run would REFUSE here" >&2
  elif [ ! -f "$ANCHOR_BIN" ] || [ ! -x "$ANCHOR_BIN" ]; then
    [ "$DRY_RUN" = 1 ] || refuse "$ANCHOR_BIN exists but is not an executable file, so trust cannot" \
      "be provisioned. Nothing was changed"
    echo "brops-install: dry run — $ANCHOR_BIN is not an executable file; a real run would REFUSE here" >&2
  fi
}

anchor_run() {
  local status=0
  local -a cmd=("$ANCHOR_BIN" --user "$DESKTOP_USER" --app-data "$APP_DATA")

  if [ "$DRY_RUN" = 1 ]; then
    echo "anchor user $DESKTOP_USER (uid $DESKTOP_UID; from $DESKTOP_SOURCE)"
    echo "anchor app-data $APP_DATA (from $APP_DATA_SOURCE)"
    echo "anchor command$(printf ' %q' "${cmd[@]}")"
    echo "brops-install: dry run — the anchor tool was not run; nothing was changed" >&2
    return 0
  fi

  "${cmd[@]}" || status=$?
  if [ "$status" != 0 ]; then
    echo "brops-install: FAILED — $ANCHOR_BIN exited $status: trust is NOT provisioned for $DESKTOP_USER" >&2
    exit "$status"
  fi
  echo "brops-install: anchor — $ANCHOR_BIN succeeded for $DESKTOP_USER (uid $DESKTOP_UID), application data $APP_DATA" >&2
}

case "$STEP" in
  accounts) step_accounts ;;
  anchor)   anchor_resolve; anchor_run ;;
  all)      anchor_resolve; step_accounts; anchor_run ;;
esac
