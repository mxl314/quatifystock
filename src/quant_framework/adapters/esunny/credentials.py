"""Windows DPAPI-backed local credentials; never persist plaintext in the repository."""

from __future__ import annotations

import ctypes
import getpass
import json
import os
from ctypes import wintypes
from pathlib import Path


class _Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _path() -> Path:
    if os.name != "nt":
        raise OSError("本机加密凭据仅支持 Windows；其他系统请用环境变量")
    appdata = os.getenv("APPDATA")
    if not appdata:
        raise OSError("APPDATA 未设置")
    return Path(appdata) / "quatifystock" / "esunny-sim.dpapi"


def _crypt(payload: bytes, *, decrypt: bool) -> bytes:
    source = ctypes.create_string_buffer(payload)
    input_blob = _Blob(len(payload), ctypes.cast(source, ctypes.POINTER(ctypes.c_ubyte)))
    output_blob = _Blob()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    if decrypt:
        fn = crypt32.CryptUnprotectData
        fn.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.POINTER(_Blob),
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
        args = (ctypes.byref(input_blob), None, None, None, None, 0, ctypes.byref(output_blob))
    else:
        fn = crypt32.CryptProtectData
        fn.argtypes = [ctypes.POINTER(_Blob), ctypes.c_wchar_p, ctypes.POINTER(_Blob),
                       ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
        args = (ctypes.byref(input_blob), "quatifystock 易盛模拟账号", None,
                None, None, 0, ctypes.byref(output_blob))
    fn.restype = wintypes.BOOL
    if not fn(*args):
        raise OSError(ctypes.get_last_error(), "Windows DPAPI 加解密失败")
    try:
        return ctypes.string_at(output_blob.data, output_blob.size)
    finally:
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree(ctypes.cast(output_blob.data, ctypes.c_void_p))


def load_credentials() -> dict[str, str]:
    path = _path()
    if not path.exists():
        return {}
    data = json.loads(_crypt(path.read_bytes(), decrypt=True).decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("凭据格式错误")
    return {str(key): str(value) for key, value in data.items()}


def save_credentials(account: str, password: str, license_no: str) -> Path:
    if not account or not password or not license_no:
        raise ValueError("账号、密码和授权码不能为空")
    return _save_payload({"account": account, "password": password,
                          "license_no": license_no})


def _save_payload(data: dict[str, str]) -> Path:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data).encode("utf-8")
    encrypted = _crypt(payload, decrypt=False)
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(encrypted)
    temporary.replace(path)
    return path


def clear_license() -> bool:
    data = load_credentials()
    if "license_no" not in data:
        return False
    del data["license_no"]
    _save_payload(data)
    return True


def update_password(account: str, password: str) -> Path:
    if not password:
        raise ValueError("密码不能为空")
    data = load_credentials()
    if data.get("account") != account:
        raise ValueError("本机凭据账号与指定账号不一致")
    data["password"] = password
    return _save_payload(data)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="管理易盛模拟账号的 Windows 加密凭据")
    parser.add_argument("action", choices=["set", "set-password", "clear-license"])
    parser.add_argument("--account", default="Q1062383955")
    args = parser.parse_args()
    if args.action == "clear-license":
        print("已删除本机授权号。" if clear_license() else "本机没有保存授权号。")
        return
    if args.action == "set-password":
        password = getpass.getpass("模拟账号新密码（不会显示）: ")
        path = update_password(args.account, password)
        print(f"密码已加密更新到 {path}；授权号保持原样。")
        return
    password = getpass.getpass("模拟账号密码（不会显示）: ")
    license_no = getpass.getpass("易盛 LicenseNo（不会显示）: ")
    path = save_credentials(args.account, password, license_no)
    print(f"已保存到 {path}；仅当前 Windows 用户可解密。")


if __name__ == "__main__":
    main()
