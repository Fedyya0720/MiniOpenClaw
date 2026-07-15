"""Create a tiny offline wheelhouse with one intentionally bad combination."""
from __future__ import annotations

import base64
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path


def build_wheel(wheelhouse: Path, distribution: str, version: str, requires: tuple[str, ...] = ()) -> Path:
    normalized = distribution.replace("-", "_")
    dist_info = f"{normalized}-{version}.dist-info"
    filename = wheelhouse / f"{normalized}-{version}-py3-none-any.whl"
    files = {
        f"{normalized}/__init__.py": f"__version__ = {version!r}\n".encode(),
        f"{dist_info}/METADATA": (
            "Metadata-Version: 2.1\n"
            f"Name: {distribution}\nVersion: {version}\n"
            + "".join(f"Requires-Dist: {item}\n" for item in requires)
            + "\n"
        ).encode(),
        f"{dist_info}/WHEEL": (
            b"Wheel-Version: 1.0\nGenerator: MiniOpenClaw-PACS\n"
            b"Root-Is-Purelib: true\nTag: py3-none-any\n"
        ),
    }
    records = []
    for path, content in files.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
        records.append(f"{path},sha256={digest},{len(content)}")
    records.append(f"{dist_info}/RECORD,,")
    files[f"{dist_info}/RECORD"] = ("\n".join(records) + "\n").encode()
    with zipfile.ZipFile(filename, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return filename


def create_fixture(root: Path) -> dict[str, str]:
    if root.exists():
        shutil.rmtree(root)
    project = root / "project"
    wheelhouse = root / "wheelhouse"
    project.mkdir(parents=True)
    wheelhouse.mkdir(parents=True)
    build_wheel(wheelhouse, "demo-core", "1.0.0")
    build_wheel(wheelhouse, "demo-core", "2.0.0")
    build_wheel(wheelhouse, "demo-plugin", "1.0.0", ("demo-core (<2)",))
    (project / "requirements.txt").write_text(
        "demo-core>=1,<3\ndemo-plugin==1.0.0\n", encoding="utf-8"
    )
    catalog = root / "catalog.json"
    catalog.write_text(
        json.dumps({"demo-core": ["2.0.0", "1.0.0"], "demo-plugin": ["1.0.0"]}, indent=2),
        encoding="utf-8",
    )
    return {"project": str(project), "wheelhouse": str(wheelhouse), "catalog": str(catalog)}


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).with_name("work")).resolve()
    print(json.dumps(create_fixture(target), indent=2))
