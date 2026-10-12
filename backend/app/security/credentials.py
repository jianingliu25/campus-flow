"""Session-only secrets by default; Windows Credential Manager is optional. Never plaintext fallback."""
import ctypes
from ctypes import wintypes
import hashlib
import os
import time
from threading import RLock

from app.security.policies import BoundaryError


class WindowsVault:
    def __init__(self):
        if os.name != "nt":
            raise BoundaryError("SECURE_STORE_UNAVAILABLE", 409)
        class Credential(ctypes.Structure):
            _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD), ("TargetName", wintypes.LPWSTR),
                        ("Comment", wintypes.LPWSTR), ("LastWritten", wintypes.FILETIME),
                        ("CredentialBlobSize", wintypes.DWORD), ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
                        ("Persist", wintypes.DWORD), ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                        ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]
        self.type = Credential
        self.api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        self.api.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
        self.api.CredWriteW.restype = wintypes.BOOL
        self.api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(Credential))]
        self.api.CredReadW.restype = wintypes.BOOL
        self.api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self.api.CredDeleteW.restype = wintypes.BOOL
        self.api.CredFree.argtypes = [ctypes.c_void_p]

    def put(self, key, secret):
        raw = secret.encode("utf-8")
        buffer = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
        entry = self.type(Type=1, TargetName=key, CredentialBlobSize=len(raw), CredentialBlob=buffer,
                          Persist=2, UserName="CampusFlow")
        if not self.api.CredWriteW(ctypes.byref(entry), 0):
            raise BoundaryError("SECURE_STORE_UNAVAILABLE", 409)

    def get(self, key):
        pointer = ctypes.POINTER(self.type)()
        if not self.api.CredReadW(key, 1, 0, ctypes.byref(pointer)):
            raise BoundaryError("CREDENTIAL_REQUIRED", 409)
        try:
            return ctypes.string_at(pointer.contents.CredentialBlob, pointer.contents.CredentialBlobSize).decode("utf-8")
        finally:
            self.api.CredFree(pointer)

    def delete(self, key):
        if not self.api.CredDeleteW(key, 1, 0) and ctypes.get_last_error() != 1168:
            raise BoundaryError("CREDENTIAL_DELETE_FAILED", 503)


class CredentialStore:
    def __init__(self, vault=None):
        self.items, self.lock, self.vault = {}, RLock(), vault

    @staticmethod
    def key(ctx):
        return f"CampusFlow/{ctx.workspace_id}/{ctx.source_id}"

    @staticmethod
    def owner(session):
        return hashlib.sha256(session.csrf_token.encode()).hexdigest()

    def put(self, ctx, session, secret, persistent=False):
        if len(secret.encode()) > 2400 or not secret:
            raise BoundaryError("INVALID_CREDENTIAL", 422)
        key = self.key(ctx)
        with self.lock:
            if persistent:
                if self.vault is None:
                    raise BoundaryError("SECURE_STORE_UNAVAILABLE", 409)
                self.vault.put(key, secret)
                self.items.pop(key, None)
                return "os-vault"
            if self.vault:
                self.vault.delete(key)
            self.items[key] = (self.owner(session), secret, getattr(session,"expires_at",float("inf")))
            return "session"

    def get(self, ctx, session, storage):
        with self.lock:
            if storage == "os-vault" and self.vault:
                return self.vault.get(self.key(ctx))
            value = self.items.get(self.key(ctx))
            if value is None or value[0] != self.owner(session) or value[2]<=time.monotonic():
                raise BoundaryError("CREDENTIAL_REQUIRED", 409)
            return value[1]

    def delete(self, ctx):
        with self.lock:
            if self.vault:
                self.vault.delete(self.key(ctx))
            self.items.pop(self.key(ctx), None)

    def clear_owner(self, session):
        with self.lock:
            self.items = {key:value for key,value in self.items.items() if value[0] != self.owner(session)}

    def clear_expired(self):
        with self.lock:
            self.items={key:value for key,value in self.items.items() if value[2]>time.monotonic()}
