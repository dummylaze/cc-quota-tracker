"""把納管目錄與檔案收緊到只有目前使用者能存取（ADR-0007）。

Windows 直接呼叫 Win32 API 讀寫 DACL，不解析 icacls 的輸出：它的帳號名稱與訊息會隨系統語系改變。
"""
import os
import stat
import sys
from pathlib import Path


def is_private(path: Path) -> bool:
    return _win_is_private(path) if sys.platform == "win32" else _posix_is_private(path)


def make_private(path: Path) -> None:
    """目錄設成子項繼承同一條規則，之後建在裡面的檔案一開始就不會外露。"""
    if sys.platform == "win32":
        _win_make_private(path)
    else:
        os.chmod(path, 0o700 if path.is_dir() else 0o600)


def _posix_is_private(path: Path) -> bool:
    st = path.stat()
    return st.st_uid == os.getuid() and stat.S_IMODE(st.st_mode) & 0o077 == 0


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _TOKEN_QUERY = 0x0008
    _TOKEN_USER = 1
    _ACL_REVISION = 2
    _FILE_ALL_ACCESS = 0x001F01FF
    _OBJECT_AND_CONTAINER_INHERIT = 0x1 | 0x2
    _ACCESS_ALLOWED_ACE_TYPE = 0
    _SE_FILE_OBJECT = 1
    _DACL_SECURITY_INFORMATION = 0x4
    _PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000
    _SE_DACL_PROTECTED = 0x1000

    class _ACL(ctypes.Structure):
        _fields_ = [("AclRevision", ctypes.c_ubyte), ("Sbz1", ctypes.c_ubyte), ("AclSize", wintypes.WORD),
                    ("AceCount", wintypes.WORD), ("Sbz2", wintypes.WORD)]

    class _ACCESS_ALLOWED_ACE(ctypes.Structure):
        _fields_ = [("AceType", ctypes.c_ubyte), ("AceFlags", ctypes.c_ubyte), ("AceSize", wintypes.WORD),
                    ("Mask", wintypes.DWORD), ("SidStart", wintypes.DWORD)]

    _kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    _advapi32.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD,
                                              ctypes.POINTER(wintypes.DWORD)]
    _advapi32.GetLengthSid.argtypes = [ctypes.c_void_p]
    _advapi32.GetLengthSid.restype = wintypes.DWORD
    _advapi32.CopySid.argtypes = [wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p]
    _advapi32.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    _advapi32.InitializeAcl.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD]
    _advapi32.AddAccessAllowedAceEx.argtypes = [ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
                                                ctypes.c_void_p]
    _advapi32.GetAce.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)]
    _advapi32.SetNamedSecurityInfoW.argtypes = [wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD, ctypes.c_void_p,
                                                ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    _advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD
    _advapi32.GetNamedSecurityInfoW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD,
                                                ctypes.c_void_p, ctypes.c_void_p,
                                                ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
                                                ctypes.POINTER(ctypes.c_void_p)]
    _advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    _advapi32.GetSecurityDescriptorControl.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.WORD),
                                                       ctypes.POINTER(wintypes.DWORD)]

    def _check(ok) -> None:
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())

    def _user_sid():
        token = wintypes.HANDLE()
        _check(_advapi32.OpenProcessToken(_kernel32.GetCurrentProcess(), _TOKEN_QUERY, ctypes.byref(token)))
        try:
            size = wintypes.DWORD()
            _advapi32.GetTokenInformation(token, _TOKEN_USER, None, 0, ctypes.byref(size))
            buf = ctypes.create_string_buffer(size.value)
            _check(_advapi32.GetTokenInformation(token, _TOKEN_USER, buf, size, ctypes.byref(size)))
            psid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]  # TOKEN_USER.User.Sid
            length = _advapi32.GetLengthSid(psid)
            sid = ctypes.create_string_buffer(length)
            _check(_advapi32.CopySid(length, sid, psid))
            return sid
        finally:
            _kernel32.CloseHandle(token)

    def _win_make_private(path: Path) -> None:
        sid = _user_sid()
        size = ctypes.sizeof(_ACL) + ctypes.sizeof(_ACCESS_ALLOWED_ACE) + len(sid.raw)
        acl = ctypes.create_string_buffer(size)
        _check(_advapi32.InitializeAcl(acl, size, _ACL_REVISION))
        flags = _OBJECT_AND_CONTAINER_INHERIT if path.is_dir() else 0
        _check(_advapi32.AddAccessAllowedAceEx(acl, _ACL_REVISION, flags, _FILE_ALL_ACCESS, sid))
        # PROTECTED：切斷從上層繼承的規則，只留上面這一條
        err = _advapi32.SetNamedSecurityInfoW(
            str(path), _SE_FILE_OBJECT, _DACL_SECURITY_INFORMATION | _PROTECTED_DACL_SECURITY_INFORMATION,
            None, None, acl, None)
        if err:
            raise ctypes.WinError(err)

    def _win_is_private(path: Path) -> bool:
        """不繼承上層，且每一條規則都是授權給目前使用者。"""
        dacl, sd = ctypes.c_void_p(), ctypes.c_void_p()
        err = _advapi32.GetNamedSecurityInfoW(str(path), _SE_FILE_OBJECT, _DACL_SECURITY_INFORMATION,
                                              None, None, ctypes.byref(dacl), None, ctypes.byref(sd))
        if err:
            raise ctypes.WinError(err)
        try:
            control, revision = wintypes.WORD(), wintypes.DWORD()
            _check(_advapi32.GetSecurityDescriptorControl(sd, ctypes.byref(control), ctypes.byref(revision)))
            if not dacl.value or not control.value & _SE_DACL_PROTECTED:
                return False  # 沒有 DACL 等於所有人都能存取
            sid = _user_sid()
            count = ctypes.cast(dacl, ctypes.POINTER(_ACL)).contents.AceCount
            for i in range(count):
                ace = ctypes.c_void_p()
                _check(_advapi32.GetAce(dacl, i, ctypes.byref(ace)))
                header = ctypes.cast(ace, ctypes.POINTER(_ACCESS_ALLOWED_ACE)).contents
                ace_sid = ace.value + _ACCESS_ALLOWED_ACE.SidStart.offset
                if header.AceType != _ACCESS_ALLOWED_ACE_TYPE or not _advapi32.EqualSid(ace_sid, sid):
                    return False
            return count > 0
        finally:
            _kernel32.LocalFree(sd)
