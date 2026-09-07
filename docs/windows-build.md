# Windows 编译环境

当前项目使用以下工具链：

- Visual C++ Build Tools 2022（x64，安装在 `C:\BuildTools`）
- CMake 4.4
- Windows 11 SDK 10.0.26100 便携包（位于项目 `.sdk` 目录）
- 易盛启明星 V10 交易 API 1.0.1.19
- 易盛启明星 V10 行情 API 1.0.0.7

在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build_native.ps1
```

输出目录为 `build/native`，其中包含两个桥接 DLL 和两个易盛运行时 DLL。

Python 环境初始化：

```powershell
python -m venv --system-site-packages .venv
.venv\Scripts\python.exe -m pip install --no-build-isolation -e .
```
