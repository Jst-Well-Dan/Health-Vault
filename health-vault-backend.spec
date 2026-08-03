from pathlib import Path

root = Path(SPECPATH)

a = Analysis(
    [str(root / "backend" / "run_backend.py")],
    pathex=[str(root / "backend")],
    hiddenimports=["main", "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto", "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="health-vault-backend", console=False)
