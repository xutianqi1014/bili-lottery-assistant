# PyInstaller onedir starting point. Run from the repository root.
from pathlib import Path

ROOT = Path(SPECPATH).parents[1]
BACKEND = ROOT / "backend"
WEB_DIST = ROOT / "web_static" / "dist"

# The launcher imports the FastAPI app object directly so PyInstaller can follow
# every production backend import. Keep test and live-contract tooling outside
# the executable by relying on that production import graph.
hiddenimports = []
datas = []
if WEB_DIST.exists():
    datas.append((str(WEB_DIST), "web_static/dist"))
datas.append((str(BACKEND / "source_adapters" / "lottery_toolman" / "interface_contracts.yaml"), "backend/source_adapters/lottery_toolman"))
datas.append((str(BACKEND / "activity_engine" / "interface_contracts.yaml"), "backend/activity_engine"))

a = Analysis(
    [str(BACKEND / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BiliLotteryAssistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
coll = COLLECT(exe, a.binaries, a.datas, name="BiliLotteryAssistant")
