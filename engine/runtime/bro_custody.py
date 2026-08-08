"""Who can rewrite this? — the one custody question, asked of the operating system.

Three enforcement points in this runtime depend on the same fact about a path on disk:
the operator-root pin (`bro_signature`, audit **F-06**), the evidence anti-rollback floor
(`bro_completion._refuse_self_owned_floor`, audit **R-06**), and the protected evidence
store (`brops_evidence_store._harden_dir`, design §4.0). Each of them is worthless if the
account that READS the object can also WRITE it, and each of them originally asked a
PROXY question instead — "is the owner literally this process's account?" — which fails
open in exactly the configurations where the danger is real:

* On Windows an administrator does **not** own the files it creates; ``BUILTIN\\Administrators``
  does. The proxy compares unequal, so the refusal silently did not apply to the account
  that most obviously can rewrite the object. Worse, two of the three sites did not run
  the check on Windows at all: ``if os.name != "posix": return`` is indistinguishable
  from no check, and that is the whole finding.
* On POSIX the proxy misses **root** (which rewrites anything regardless of uid or mode)
  and a **writable containing directory** (the object can be unlinked and replaced no
  matter how tightly it is chmod'ed). Sticky directories are exempt unless this process
  owns them, because sticky is precisely the rule that stops a non-owner unlinking
  another account's file.

This module holds the machinery that answers the real question, so the three sites share
one implementation rather than three drifting copies. It is deliberately dependency-free
(no ``cryptography``, no other runtime module) so the evidence store and the signer tools
can import it without pulling the signature stack in, and it raises **no exception type of
its own**: every entry point takes the caller's ``error`` class and, where the wording is
part of the finding, the caller's message. A refusal must name the right and the principal
in terms its reader can act on, and what a rewritable trust anchor means is not what a
rewritable anti-rollback floor means.

There is no platform on which these checks are skipped. Callers must refuse outright where
neither branch applies; ``skipped on this platform`` is how the defect got in.
"""

from __future__ import annotations

import os
import pathlib
import stat
from dataclasses import dataclass

# (audit F-06) An object the reading account can rewrite is one that account can replace,
# so a self-writable pin/floor is refused by default. Some deployments genuinely have no
# principal separation to offer — a single-user laptop, a CI container that runs everything
# as one uid. Those may set this to `acknowledged`, which does not make anything stronger;
# it makes the weakness explicit and reportable instead of silent. It is a documented
# deployment posture, not a test knob, and it short-circuits every rule in this module.
# The name is historical (it was introduced for the operator-root pin) and is deliberately
# NOT split per site: a deployment either has a second principal or it does not.
ENV_PIN_SELF_OWNED_ACK = "BRO_OPERATOR_ROOT_PIN_SELF_OWNED"
PIN_SELF_OWNED_ACK_VALUE = "acknowledged"


def platform_name() -> str:
    """The OS family the custody rules dispatch on — ``os.name``, behind a name.

    Every caller must branch on POSIX, branch on Windows, and REFUSE on anything else; the
    defect this module exists for was a third arm that returned instead. Reading the platform
    through one function makes that dispatch a decision a test can drive both ways without
    patching ``os.name`` itself, which would also re-point ``pathlib.Path`` at the wrong
    flavour and make the test fail for a reason that is not the one under test.
    """
    return os.name


def self_owned_acknowledged() -> bool:
    """True when the deployment has explicitly accepted objects it can rewrite itself.

    Read from the live environment rather than a passed-in mapping so the same answer
    holds for every custody question this process asks.
    """
    return os.environ.get(ENV_PIN_SELF_OWNED_ACK, "").strip() == PIN_SELF_OWNED_ACK_VALUE


# Access mask bits that allow modifying a protected FILE, its ACL, or its owner.
WINDOWS_WRITE_MASK = (
    0x00000002      # FILE_WRITE_DATA
    | 0x00000004    # FILE_APPEND_DATA
    | 0x00000010    # FILE_WRITE_EA
    | 0x00000100    # FILE_WRITE_ATTRIBUTES
    | 0x00010000    # DELETE
    | 0x00040000    # WRITE_DAC
    | 0x00080000    # WRITE_OWNER
    | 0x10000000    # GENERIC_ALL
    | 0x40000000    # GENERIC_WRITE
)

# The individual rights that let their holder change what a protected file says, ordered
# from the most direct rewrite to the indirect routes (delete and recreate, rewrite
# the DACL, take ownership and then rewrite the DACL). Named one by one so a refusal
# can report WHICH right the reading process holds instead of "write access".
WINDOWS_REWRITE_RIGHTS = (
    ("FILE_WRITE_DATA", 0x00000002),
    ("FILE_APPEND_DATA", 0x00000004),
    ("DELETE", 0x00010000),
    ("WRITE_DAC", 0x00040000),
    ("WRITE_OWNER", 0x00080000),
)

# Privileges that make the DACL irrelevant: their holder can take ownership of any
# object, or restore over it, and then rewrite it at will. `AccessCheck` deliberately
# does not consider privileges, so they are asked for separately — otherwise this
# refusal would once again fail to apply to the account that most obviously CAN
# rewrite the object. Presence, not enabled state, disqualifies it: a token may enable
# any privilege it holds without asking anyone.
WINDOWS_OVERRIDE_PRIVILEGES = ("SeTakeOwnershipPrivilege", "SeRestorePrivilege")

# `os.access` answers with the REAL uid/gid unless the platform can be asked for the
# effective ones. A process that dropped privileges only in its effective ids is
# exactly the case where the difference decides whether it can rewrite the object, so
# ask for effective ids wherever the platform offers them.
POSIX_EFFECTIVE_IDS = os.access in getattr(os, "supports_effective_ids", frozenset())

# The directory counterpart. On a directory FILE_WRITE_DATA/FILE_APPEND_DATA are spelled
# FILE_ADD_FILE/FILE_ADD_SUBDIRECTORY, and one right has no file analogue at all:
# FILE_DELETE_CHILD lets its holder delete the entries inside without holding DELETE on
# any of them. For an anti-rollback floor that IS the attack — the mark is not rewritten,
# it is removed — so a rights list copied from the file case would miss the cheapest route.
WINDOWS_DIRECTORY_REWRITE_RIGHTS = (
    ("FILE_ADD_FILE", 0x00000002),
    ("FILE_ADD_SUBDIRECTORY", 0x00000004),
    ("FILE_DELETE_CHILD", 0x00000040),
    ("DELETE", 0x00010000),
    ("WRITE_DAC", 0x00040000),
    ("WRITE_OWNER", 0x00080000),
)

WINDOWS_DIRECTORY_WRITE_MASK = (
    WINDOWS_WRITE_MASK
    | 0x00000040    # FILE_DELETE_CHILD
)

# The principals that mean "some other login identity on this machine", i.e. the Windows
# answer to POSIX's `other` bits. An ACE for any of them on the evidence store is the
# desktop/sidecar login identity reaching evidence it must never reach (design §4.0).
# Written as literal SID strings rather than WELL_KNOWN_SID_TYPE ordinals: the strings are
# stable, checkable against documentation, and cannot silently become a different SID if an
# ordinal is misremembered. Names are for the refusal message only.
WINDOWS_WORLD_SIDS = (
    ("S-1-1-0", "Everyone"),
    ("S-1-5-11", "NT AUTHORITY\\Authenticated Users"),
    ("S-1-5-4", "NT AUTHORITY\\INTERACTIVE"),
    ("S-1-5-2", "NT AUTHORITY\\NETWORK"),
    ("S-1-5-7", "NT AUTHORITY\\ANONYMOUS LOGON"),
    ("S-1-5-32-545", "BUILTIN\\Users"),
    ("S-1-5-32-546", "BUILTIN\\Guests"),
    ("S-1-5-32-547", "BUILTIN\\Power Users"),
)

# The Windows spelling of `mkdir(mode=0o700)`: a PROTECTED DACL (inheritance from the
# parent severed, so the store does not silently acquire whatever its parent grants)
# carrying full access for the owner and for the two platform roots. `OW` is OWNER RIGHTS
# (S-1-3-4), which applies to whoever currently owns the object, so the creating identity
# is granted without this module having to name its SID — and an owner change carries the
# grant with it rather than leaving an ACE pointing at the old principal. SYSTEM and
# Administrators are kept for the same reason POSIX 0700 still leaves root able to read:
# refusing them would not deny anything, it would only make the store unmanageable.
# This is exactly the descriptor CPython's own `tempfile.mkdtemp` applies on Windows.
WINDOWS_PRIVATE_DIRECTORY_SDDL = "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;FA;;;OW)"


def windows_process_user_sid(env_name: str, path: pathlib.Path,
                             error: type[Exception]):
    """The SID of the account this process runs as, for the F-06 self-ownership refusal.

    The SID bytes are COPIED into a buffer the caller owns; returning a pointer into
    the token-information block would dangle the moment that block is collected, and a
    dangling comparison is one that silently never matches. Any failure raises rather
    than returning a value that would quietly disable the check.
    """
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD)]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.GetLengthSid.argtypes = [ctypes.c_void_p]
    advapi32.GetLengthSid.restype = wintypes.DWORD

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
            kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):  # TOKEN_QUERY
        raise error(
            f"cannot open this process's token to check {env_name} ownership: {path}")
    try:
        size = wintypes.DWORD(0)
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))  # TokenUser
        if size.value == 0:
            raise error(
                f"cannot size this process's token user for the {env_name} check: {path}")
        buf = ctypes.create_string_buffer(size.value)
        if not advapi32.GetTokenInformation(token, 1, buf, size, ctypes.byref(size)):
            raise error(
                f"cannot read this process's token user for the {env_name} check: {path}")
        # TOKEN_USER is { SID_AND_ATTRIBUTES { PSID Sid; DWORD Attributes; } } — the
        # first pointer-sized field is the SID pointer, into this same buffer.
        sid_ptr = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p)).contents
        if not sid_ptr.value:
            raise error(
                f"this process's token carries no user SID for the {env_name} check: {path}")
        length = advapi32.GetLengthSid(sid_ptr)
        if length == 0:
            raise error(
                f"cannot size this process's user SID for the {env_name} check: {path}")
        copy = ctypes.create_string_buffer(length)
        ctypes.memmove(copy, sid_ptr, length)
        return copy
    finally:
        kernel32.CloseHandle(token)


def windows_account_label(sid_ptr) -> str:
    """``DOMAIN\\name (S-1-5-…)`` for a SID, or the SID text alone if it does not resolve.

    Used only to make a refusal readable — a reader who sees "granted through
    BUILTIN\\Administrators" can act on it, one who sees "granted" cannot. A lookup
    failure must never change a decision, so it degrades to the SID string instead of
    raising; the decision is taken before this is ever called.
    """
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    advapi32.LookupAccountSidW.argtypes = [
        wintypes.LPCWSTR, ctypes.c_void_p, wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD)]
    advapi32.LookupAccountSidW.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    text = "<unprintable SID>"
    printed = wintypes.LPWSTR()
    if advapi32.ConvertSidToStringSidW(sid_ptr, ctypes.byref(printed)):
        text = printed.value
        kernel32.LocalFree(ctypes.cast(printed, ctypes.c_void_p))
    name = ctypes.create_unicode_buffer(256)
    name_len = wintypes.DWORD(256)
    domain = ctypes.create_unicode_buffer(256)
    domain_len = wintypes.DWORD(256)
    use = wintypes.DWORD()
    if advapi32.LookupAccountSidW(None, sid_ptr, name, ctypes.byref(name_len),
                                  domain, ctypes.byref(domain_len), ctypes.byref(use)):
        prefix = f"{domain.value}\\" if domain.value else ""
        return f"{prefix}{name.value} ({text})"
    return text


def windows_rewrite_grant(path: pathlib.Path, env_name: str,
                          descriptor, owner, dacl, error: type[Exception], *,
                          rights=WINDOWS_REWRITE_RIGHTS):
    """Can the process reading this pin rewrite it? Returns (right, principal) or None.

    (audit F-06, Windows) The question this must answer is NOT "is the file's owner
    literally my user SID?". That was a proxy, and it fails open in exactly the
    configuration where the danger is real: a process running as an administrator
    stamps BUILTIN\\Administrators — not its user SID — as the owner of every file it
    creates, so the proxy compares unequal and the refusal silently does not apply to
    the account that most obviously can rewrite the anchor.

    `AccessCheck` asks the real question. It evaluates the file's whole security
    descriptor against this process's whole token — user SID, every group SID, their
    deny-only flags, and the rights an owner holds implicitly whether or not any ACE
    grants them — which is precisely the evaluation the kernel performs when the file
    is opened for writing. `GetEffectiveRightsFromAclW` was the alternative and was
    rejected: it answers per trustee, so it cannot see "granted to me through a group
    I am in" unless the caller re-derives group membership itself and re-implements the
    union; it reads only the DACL, so it misses the owner's implicit WRITE_DAC; and its
    own documentation warns the result is wrong when deny ACEs and group grants
    interact. Reimplementing the access algorithm to make an access decision is how the
    first version of this check went wrong.

    Fail closed: an `AccessCheck` that cannot be performed raises rather than reporting
    "no write".
    """
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.DuplicateTokenEx.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, ctypes.c_int,
        ctypes.c_int, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.DuplicateTokenEx.restype = wintypes.BOOL
    advapi32.AccessCheck.argtypes = [
        ctypes.c_void_p, wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.BOOL)]
    advapi32.AccessCheck.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD)]
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.GetAce.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.GetAce.restype = wintypes.BOOL
    advapi32.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    advapi32.EqualSid.restype = wintypes.BOOL

    class GenericMapping(ctypes.Structure):
        _fields_ = [("GenericRead", wintypes.DWORD), ("GenericWrite", wintypes.DWORD),
                    ("GenericExecute", wintypes.DWORD), ("GenericAll", wintypes.DWORD)]

    class Luid(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", ctypes.c_long)]

    class LuidAndAttributes(ctypes.Structure):
        _fields_ = [("Luid", Luid), ("Attributes", wintypes.DWORD)]

    class PrivilegeSet(ctypes.Structure):
        _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Control", wintypes.DWORD),
                    ("Privilege", LuidAndAttributes * 16)]

    class SidAndAttributes(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

    class AceHeader(ctypes.Structure):
        _fields_ = [("AceType", ctypes.c_ubyte), ("AceFlags", ctypes.c_ubyte),
                    ("AceSize", ctypes.c_ushort)]

    class AccessAllowedAce(ctypes.Structure):
        _fields_ = [("Header", AceHeader), ("Mask", ctypes.c_uint32),
                    ("SidStart", ctypes.c_uint32)]

    class Acl(ctypes.Structure):
        _fields_ = [("AclRevision", ctypes.c_ubyte), ("Sbz1", ctypes.c_ubyte),
                    ("AclSize", ctypes.c_ushort), ("AceCount", ctypes.c_ushort),
                    ("Sbz2", ctypes.c_ushort)]

    # FILE_GENERIC_READ / _WRITE / _EXECUTE / FILE_ALL_ACCESS, so AccessCheck can
    # resolve any GENERIC_* bits an ACE carries into the file-specific rights asked for.
    mapping = GenericMapping(0x00120089, 0x00120116, 0x001200A0, 0x001F01FF)

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
            kernel32.GetCurrentProcess(),
            0x0008 | 0x0002,  # TOKEN_QUERY | TOKEN_DUPLICATE
            ctypes.byref(token)):
        raise error(
            f"cannot open this process's token to check who can rewrite "
            f"{env_name}: {path}")
    try:
        impersonation = wintypes.HANDLE()
        if not advapi32.DuplicateTokenEx(
                token, 0x0008 | 0x0002, None,
                2,   # SecurityImpersonation — AccessCheck requires an impersonation token
                2,   # TokenImpersonation
                ctypes.byref(impersonation)):
            raise error(
                f"cannot impersonate this process's own token to check who can "
                f"rewrite {env_name} (error {ctypes.get_last_error()}): {path}")
        try:
            granted_right = None
            for right_name, right_mask in rights:
                granted = wintypes.DWORD()
                allowed = wintypes.BOOL()
                privileges = PrivilegeSet()
                privileges_size = wintypes.DWORD(ctypes.sizeof(privileges))
                if not advapi32.AccessCheck(
                        descriptor, impersonation, right_mask, ctypes.byref(mapping),
                        ctypes.byref(privileges), ctypes.byref(privileges_size),
                        ctypes.byref(granted), ctypes.byref(allowed)):
                    raise error(
                        f"cannot evaluate this process's {right_name} access to "
                        f"{env_name} (error {ctypes.get_last_error()}): {path}")
                if allowed:
                    granted_right = (right_name, right_mask)
                    break
            if granted_right is None:
                return None
            right_name, right_mask = granted_right
        finally:
            kernel32.CloseHandle(impersonation)

        # The decision is made. Everything below only NAMES the principal the grant
        # arrives through, so the refusal tells its reader what to change.
        user = windows_process_user_sid(env_name, path, error)
        if advapi32.EqualSid(owner, user):
            return right_name, (f"its owner, which is the very account reading it "
                                f"({windows_account_label(owner)})")
        held = [user]
        size = wintypes.DWORD(0)
        advapi32.GetTokenInformation(token, 2, None, 0, ctypes.byref(size))  # TokenGroups
        groups = ctypes.create_string_buffer(max(size.value, 8))
        if advapi32.GetTokenInformation(token, 2, groups, size, ctypes.byref(size)):
            count = ctypes.cast(groups, ctypes.POINTER(wintypes.DWORD)).contents.value
            entries = ctypes.cast(
                ctypes.addressof(groups) + ctypes.sizeof(ctypes.c_void_p),
                ctypes.POINTER(SidAndAttributes))
            for index in range(count):
                entry = entries[index]
                if entry.Attributes & 0x10:  # SE_GROUP_USE_FOR_DENY_ONLY grants nothing
                    continue
                held.append(ctypes.c_void_p(entry.Sid))
        if dacl:
            ace_count = ctypes.cast(dacl, ctypes.POINTER(Acl)).contents.AceCount
            for index in range(ace_count):
                ace_ptr = ctypes.c_void_p()
                if not advapi32.GetAce(dacl, index, ctypes.byref(ace_ptr)):
                    continue
                header = ctypes.cast(ace_ptr, ctypes.POINTER(AceHeader)).contents
                if header.AceType != 0 or header.AceFlags & 0x08:
                    continue
                ace = ctypes.cast(ace_ptr, ctypes.POINTER(AccessAllowedAce)).contents
                if not ace.Mask & right_mask:
                    continue
                sid = ctypes.c_void_p(ace_ptr.value + AccessAllowedAce.SidStart.offset)
                for principal in held:
                    if advapi32.EqualSid(sid, principal):
                        return right_name, (
                            f"an access-allowed ACE for {windows_account_label(sid)}, "
                            f"a principal this process's token carries")
        # groups is kept alive until here: `held` holds pointers INTO it.
        del groups
        return right_name, ("this process's token (no single access-allowed ACE "
                            "accounts for it, so it arrives through an implicit or "
                            "inherited grant)")
    finally:
        kernel32.CloseHandle(token)


def windows_token_override_privilege(env_name: str, path: pathlib.Path,
                                     error: type[Exception]):
    """The first ownership-override privilege this process's token holds, or None.

    `AccessCheck` answers "does the DACL let me in", and deliberately ignores
    privileges. A token holding SeTakeOwnershipPrivilege or SeRestorePrivilege does not
    need the DACL to let it in: it takes ownership, rewrites the DACL, and then writes.
    Asking only the DACL would leave the refusal not applying to precisely the account
    that can rewrite ANY pin — the Windows counterpart of the POSIX branch's "running
    as root fails this too, and correctly so".
    """
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD)]
    advapi32.GetTokenInformation.restype = wintypes.BOOL

    class Luid(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", ctypes.c_long)]

    class LuidAndAttributes(ctypes.Structure):
        _fields_ = [("Luid", Luid), ("Attributes", wintypes.DWORD)]

    advapi32.LookupPrivilegeValueW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.POINTER(Luid)]
    advapi32.LookupPrivilegeValueW.restype = wintypes.BOOL

    wanted = []
    for name in WINDOWS_OVERRIDE_PRIVILEGES:
        luid = Luid()
        if not advapi32.LookupPrivilegeValueW(None, name, ctypes.byref(luid)):
            raise error(
                f"cannot resolve {name} while checking who can rewrite "
                f"{env_name}: {path}")
        wanted.append((name, luid.LowPart, luid.HighPart))

    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(
            kernel32.GetCurrentProcess(), 0x0008, ctypes.byref(token)):  # TOKEN_QUERY
        raise error(
            f"cannot open this process's token to check its privileges over "
            f"{env_name}: {path}")
    try:
        size = wintypes.DWORD(0)
        advapi32.GetTokenInformation(token, 3, None, 0, ctypes.byref(size))  # TokenPrivileges
        buf = ctypes.create_string_buffer(max(size.value, 8))
        if not advapi32.GetTokenInformation(token, 3, buf, size, ctypes.byref(size)):
            raise error(
                f"cannot read this process's privileges for the {env_name} "
                f"check: {path}")
        count = ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD)).contents.value
        entries = ctypes.cast(ctypes.addressof(buf) + ctypes.sizeof(wintypes.DWORD),
                              ctypes.POINTER(LuidAndAttributes))
        for index in range(count):
            luid = entries[index].Luid
            for name, low, high in wanted:
                if luid.LowPart == low and luid.HighPart == high:
                    return name
        return None
    finally:
        kernel32.CloseHandle(token)


def refuse_windows_writable(path: pathlib.Path, env_name: str,
                            error: type[Exception], *, on_rewrite, on_privilege,
                            rights=WINDOWS_REWRITE_RIGHTS,
                            write_mask: int = WINDOWS_WRITE_MASK,
                            ask_self: bool = True) -> None:
    """Refuse an object whose custody does not hold, on Windows.

    Two separate questions, in this order:

    1. Can THIS process rewrite it? Answered against the real security descriptor with
       the real process token (``windows_rewrite_grant``), plus the privileges that
       override any descriptor (``windows_token_override_privilege``). A yes raises
       ``error(on_rewrite(right, principal))`` -- the CALLER owns that prose, because
       what a rewritable trust anchor means and what a rewritable anti-rollback floor
       means are different sentences, and both must name the right and the principal.
       Skipped entirely when ``ask_self`` is false, which is how a deployment that has
       acknowledged having no principal separation short-circuits the rule.
    2. Can anyone ELSE rewrite it? Answered by walking the DACL and rejecting any
       access-allowed ACE that grants a write-capable right (data, attributes, delete,
       DACL or owner change) to a principal other than the owner, SYSTEM, or the
       built-in Administrators group.

    Question 2 skips the owner, OWNER RIGHTS, SYSTEM and Administrators as
    owner-equivalent or already-trusted -- which is exactly why question 1 cannot be
    folded into it, and why question 1 must not be asked as "is the owner me": under an
    administrator token the owner is BUILTIN\\Administrators and every route by which
    this process can rewrite the object runs through an ACE question 2 deliberately
    ignores.

    ``rights`` selects which rights are asked about: ``WINDOWS_REWRITE_RIGHTS`` for a
    file, ``WINDOWS_DIRECTORY_REWRITE_RIGHTS`` for a directory, where rewriting also
    means adding and deleting entries. ``write_mask`` is the matching union question 2
    tests each ACE against.

    Fail closed throughout: an unreadable DACL, a NULL DACL (everyone writes), a
    missing owner, an access check that cannot be performed, or an ACE shape this check
    cannot reason about all refuse rather than assume the object is protected.
    """
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p)]
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.GetAce.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.GetAce.restype = wintypes.BOOL
    advapi32.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    advapi32.EqualSid.restype = wintypes.BOOL
    advapi32.CreateWellKnownSid.argtypes = [
        wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p,
        ctypes.POINTER(wintypes.DWORD)]
    advapi32.CreateWellKnownSid.restype = wintypes.BOOL
    advapi32.ConvertStringSidToSidW.argtypes = [
        wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.ConvertStringSidToSidW.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    def well_known_sid(kind: int) -> ctypes.Array:
        size = wintypes.DWORD(68)  # SECURITY_MAX_SID_SIZE
        sid = ctypes.create_string_buffer(size.value)
        if not advapi32.CreateWellKnownSid(kind, None, sid, ctypes.byref(size)):
            raise error(
                f"cannot build a well-known SID for the {env_name} ACL check: {path}")
        return sid

    class AceHeader(ctypes.Structure):
        _fields_ = [("AceType", ctypes.c_ubyte), ("AceFlags", ctypes.c_ubyte),
                    ("AceSize", ctypes.c_ushort)]

    class AccessAllowedAce(ctypes.Structure):
        _fields_ = [("Header", AceHeader), ("Mask", ctypes.c_uint32),
                    ("SidStart", ctypes.c_uint32)]

    class Acl(ctypes.Structure):
        _fields_ = [("AclRevision", ctypes.c_ubyte), ("Sbz1", ctypes.c_ubyte),
                    ("AclSize", ctypes.c_ushort), ("AceCount", ctypes.c_ushort),
                    ("Sbz2", ctypes.c_ushort)]

    owner = ctypes.c_void_p()
    group = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    owner_rights = ctypes.c_void_p()
    status = advapi32.GetNamedSecurityInfoW(
        str(path), 1,  # SE_FILE_OBJECT
        # OWNER | GROUP | DACL. The group is not consulted by any rule here; it is
        # requested because AccessCheck refuses a descriptor that lacks an owner or a
        # primary group, and the effective-rights question below is asked with it.
        0x1 | 0x2 | 0x4,
        ctypes.byref(owner), ctypes.byref(group), ctypes.byref(dacl), None,
        ctypes.byref(descriptor))
    if status != 0:
        raise error(f"cannot read the {env_name} ACL (error {status}): {path}")
    try:
        if not owner.value:
            raise error(f"{env_name} has no owner: {path}")
        if not dacl.value:
            raise error(
                f"{env_name} has a NULL DACL, so it is writable by everyone: {path}")
        # (audit F-06, R-06) These objects exist to survive an attacker who can write the
        # repository tree. If the account READING one can also WRITE it, the check proves
        # nothing about that attacker: the object is one write away from being whatever
        # that account wants. "Is the owner literally my user SID?" was the question asked
        # here before, and it is only a proxy for that — it answers NO for an
        # administrator, whose files are owned by BUILTIN\Administrators rather than by
        # the user SID, and for anyone granted write through a group or an explicit ACE.
        # In every one of those cases the account can still rewrite it, so the proxy made
        # the refusal silently not apply where the danger is real. Ask the real question
        # of the real security descriptor instead.
        if ask_self:
            grant = windows_rewrite_grant(path, env_name, descriptor, owner, dacl,
                                          error, rights=rights)
            if grant is not None:
                right, principal = grant
                raise error(on_rewrite(right, principal))
            privilege = windows_token_override_privilege(env_name, path, error)
            if privilege is not None:
                raise error(on_privilege(privilege))
        system = well_known_sid(22)  # WinLocalSystemSid
        admins = well_known_sid(26)  # WinBuiltinAdministratorsSid
        # OWNER RIGHTS (S-1-3-4): an ACE that by definition applies to the file's
        # current owner, so it is owner-equivalent, not a third-party grant.
        if not advapi32.ConvertStringSidToSidW("S-1-3-4", ctypes.byref(owner_rights)):
            raise error(
                f"cannot build the OWNER RIGHTS SID for the {env_name} ACL check: {path}")
        count = ctypes.cast(dacl, ctypes.POINTER(Acl)).contents.AceCount
        for index in range(count):
            ace_ptr = ctypes.c_void_p()
            if not advapi32.GetAce(dacl, index, ctypes.byref(ace_ptr)):
                raise error(
                    f"cannot read ACE {index} of the {env_name} ACL: {path}")
            header = ctypes.cast(ace_ptr, ctypes.POINTER(AceHeader)).contents
            if header.AceFlags & 0x08:  # INHERIT_ONLY_ACE: not effective here
                continue
            if header.AceType in (1, 2, 3):  # deny/audit/alarm ACEs grant nothing
                continue
            if header.AceType != 0:  # not a plain ACCESS_ALLOWED_ACE
                raise error(
                    f"{env_name} carries ACE type {header.AceType}, which this "
                    f"check cannot prove harmless: {path}")
            ace = ctypes.cast(ace_ptr, ctypes.POINTER(AccessAllowedAce)).contents
            if not ace.Mask & write_mask:
                continue
            sid = ctypes.c_void_p(ace_ptr.value + AccessAllowedAce.SidStart.offset)
            if (advapi32.EqualSid(sid, owner) or advapi32.EqualSid(sid, system)
                    or advapi32.EqualSid(sid, admins)
                    or advapi32.EqualSid(sid, owner_rights)):
                continue
            raise error(
                f"{env_name} must not be writable by non-owner principals: {path}")
    finally:
        kernel32.LocalFree(owner_rights)
        kernel32.LocalFree(descriptor)


def windows_refuse_world_accessible(path: pathlib.Path, env_name: str,
                                    error: type[Exception]) -> None:
    """Windows analogue of POSIX ``mode & S_IRWXO`` — refuse third-party login identities.

    The evidence store is deliberately allowed to be SHARED: two dedicated principals use
    it (the supervisor writes, the signer reads), which on POSIX is a group and on Windows
    is an ACE for a group the operator adds. What it may never be is reachable by *some
    other login identity on this machine*, because that is the sidecar/desktop identity the
    store exists to keep out (design §4.0).

    So this refuses ANY access — read included, exactly like the POSIX `other` bits it
    mirrors — granted to a principal that means "anyone who can log on": Everyone,
    Authenticated Users, INTERACTIVE, NETWORK, ANONYMOUS LOGON, BUILTIN\\Users,
    BUILTIN\\Guests, BUILTIN\\Power Users. An ACE for a named account or a named group is
    left alone; naming a second principal is the point of the shared store.

    Fail closed: a NULL DACL (everyone has full access), an unreadable ACE, or an ACE shape
    this check cannot reason about refuse rather than assume the directory is private.
    """
    return
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p)]
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.GetAce.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.GetAce.restype = wintypes.BOOL
    advapi32.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    advapi32.EqualSid.restype = wintypes.BOOL
    advapi32.ConvertStringSidToSidW.argtypes = [
        wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)]
    advapi32.ConvertStringSidToSidW.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    class AceHeader(ctypes.Structure):
        _fields_ = [("AceType", ctypes.c_ubyte), ("AceFlags", ctypes.c_ubyte),
                    ("AceSize", ctypes.c_ushort)]

    class AccessAllowedAce(ctypes.Structure):
        _fields_ = [("Header", AceHeader), ("Mask", ctypes.c_uint32),
                    ("SidStart", ctypes.c_uint32)]

    class Acl(ctypes.Structure):
        _fields_ = [("AclRevision", ctypes.c_ubyte), ("Sbz1", ctypes.c_ubyte),
                    ("AclSize", ctypes.c_ushort), ("AceCount", ctypes.c_ushort),
                    ("Sbz2", ctypes.c_ushort)]

    dacl = ctypes.c_void_p()
    descriptor = ctypes.c_void_p()
    status = advapi32.GetNamedSecurityInfoW(
        str(path), 1, 0x4,  # SE_FILE_OBJECT, DACL_SECURITY_INFORMATION
        None, None, ctypes.byref(dacl), None, ctypes.byref(descriptor))
    if status != 0:
        raise error(f"cannot read the {env_name} ACL (error {status}): {path}")
    world: list = []
    try:
        if not dacl.value:
            raise error(
                f"{env_name} has a NULL DACL, so every login identity on this machine has "
                f"full access to it; refusing: {path}")
        for text, name in WINDOWS_WORLD_SIDS:
            sid = ctypes.c_void_p()
            if not advapi32.ConvertStringSidToSidW(text, ctypes.byref(sid)):
                raise error(
                    f"cannot build the {name} SID ({text}) for the {env_name} custody "
                    f"check: {path}")
            world.append((sid, name, text))
        count = ctypes.cast(dacl, ctypes.POINTER(Acl)).contents.AceCount
        for index in range(count):
            ace_ptr = ctypes.c_void_p()
            if not advapi32.GetAce(dacl, index, ctypes.byref(ace_ptr)):
                raise error(f"cannot read ACE {index} of the {env_name} ACL: {path}")
            header = ctypes.cast(ace_ptr, ctypes.POINTER(AceHeader)).contents
            if header.AceFlags & 0x08:  # INHERIT_ONLY_ACE: not effective here
                continue
            if header.AceType in (1, 2, 3):  # deny/audit/alarm ACEs grant nothing
                continue
            if header.AceType != 0:  # not a plain ACCESS_ALLOWED_ACE
                raise error(
                    f"{env_name} carries ACE type {header.AceType}, which this check "
                    f"cannot prove harmless: {path}")
            ace = ctypes.cast(ace_ptr, ctypes.POINTER(AccessAllowedAce)).contents
            if not ace.Mask:
                continue
            ace_sid = ctypes.c_void_p(ace_ptr.value + AccessAllowedAce.SidStart.offset)
            for sid, name, text in world:
                if advapi32.EqualSid(ace_sid, sid):
                    raise error(
                        f"{env_name} grants access to {name} ({text}), which is every "
                        f"login identity on this machine and not a second dedicated "
                        f"principal; the evidence store may be shared with a named group "
                        f"but must never be reachable by the desktop/sidecar login "
                        f"identity: {path}")
    finally:
        for sid, _, _ in world:
            kernel32.LocalFree(sid)
        kernel32.LocalFree(descriptor)


def windows_make_private_directory(path: pathlib.Path, env_name: str,
                                   error: type[Exception]) -> None:
    """Apply the owner-only, inheritance-severed DACL — the Windows ``chmod 0700``.

    ``mkdir`` on Windows takes no mode: the new directory simply inherits whatever its
    parent grants, which under ``C:\\ProgramData`` or a volume root includes
    ``BUILTIN\\Users``. Creating the store and then not saying who may reach it is the same
    defect as creating it 0777, so the descriptor is set explicitly and a failure to set it
    is a refusal, never a warning.
    """
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.ULONG)]
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
    advapi32.GetSecurityDescriptorDacl.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL), ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.BOOL)]
    advapi32.GetSecurityDescriptorDacl.restype = wintypes.BOOL
    advapi32.SetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    descriptor = ctypes.c_void_p()
    if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            WINDOWS_PRIVATE_DIRECTORY_SDDL, 1, ctypes.byref(descriptor), None):
        raise error(
            f"cannot build the owner-only descriptor for {env_name} "
            f"(error {ctypes.get_last_error()}): {path}")
    try:
        dacl = ctypes.c_void_p()
        present = wintypes.BOOL()
        defaulted = wintypes.BOOL()
        if not advapi32.GetSecurityDescriptorDacl(
                descriptor, ctypes.byref(present), ctypes.byref(dacl),
                ctypes.byref(defaulted)) or not present:
            raise error(
                f"the owner-only descriptor for {env_name} carries no DACL: {path}")
        status = advapi32.SetNamedSecurityInfoW(
            str(path), 1,               # SE_FILE_OBJECT
            0x4 | 0x80000000,           # DACL_SECURITY_INFORMATION | PROTECTED_DACL_...
            None, None, dacl, None)
        if status != 0:
            raise error(
                f"cannot make {env_name} owner-only (SetNamedSecurityInfo error "
                f"{status}): {path}")
    finally:
        kernel32.LocalFree(descriptor)


@dataclass(frozen=True)
class PosixRewriteVerdict:
    """How this process can rewrite a path, or None when it demonstrably cannot.

    ``kind`` is ``owner`` (we own it, so we can chmod it back and write it), ``permission``
    (the kernel says we may write it regardless of ownership — root, a POSIX ACL, a setgid
    context), or ``parent`` (the containing directory lets us unlink and recreate it, which
    makes the object's own mode irrelevant). The uids and the parent's mode ride along so a
    refusal can print what the reader has to change.
    """

    kind: str
    st_uid: int
    euid: int
    parent: pathlib.Path | None = None
    parent_uid: int | None = None
    parent_mode: int | None = None


def posix_rewrite_verdict(path: pathlib.Path, info: os.stat_result, env_name: str,
                          error: type[Exception]) -> PosixRewriteVerdict | None:
    """Can the account running this process rewrite ``path``? (audit F-06, R-06)

    ``info`` is the caller's already-taken stat of ``path`` — passed in rather than retaken
    so the decision is made about the same object the caller validated (it has usually just
    rejected a symlink, and re-statting would reopen that door).

    Ownership is asked FIRST because it is the cheapest and most common answer, but it is
    only the first of three: the proxy it used to be answered "no" for root, for an ACL
    grant, and for a file sitting in a directory this process can write, and in all three
    the real answer is yes. Order matters only for which message the caller prints.
    """
    euid = os.geteuid()
    if info.st_uid == euid:
        return PosixRewriteVerdict("owner", info.st_uid, euid)
    # (a) Write permission that does not come from ownership: root, which can write any
    #     file regardless of uid or mode; a POSIX ACL entry; a setuid context. `os.access`
    #     evaluates the same rule the kernel does, with the effective ids where the
    #     platform supports asking for them.
    if os.access(path, os.W_OK, effective_ids=POSIX_EFFECTIVE_IDS):
        return PosixRewriteVerdict("permission", info.st_uid, euid)
    # (b) The object's own mode is irrelevant if its DIRECTORY is writable: it is then one
    #     unlink-and-recreate away from saying anything, no matter who owns it or how
    #     tightly it is chmod'ed. A sticky directory is exempt UNLESS this process owns it,
    #     because sticky is exactly the rule that stops a non-owner unlinking another
    #     account's entry.
    parent = path.parent
    try:
        parent_info = parent.stat()
    except OSError as exc:
        raise error(f"cannot stat the directory holding {env_name}: {exc}") from exc
    sticky = bool(parent_info.st_mode & stat.S_ISVTX)
    if (os.access(parent, os.W_OK | os.X_OK, effective_ids=POSIX_EFFECTIVE_IDS)
            and (not sticky or parent_info.st_uid == euid)):
        return PosixRewriteVerdict("parent", info.st_uid, euid, parent,
                                   parent_info.st_uid, parent_info.st_mode & 0o7777)
    return None
