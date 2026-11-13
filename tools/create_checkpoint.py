"""Create a verified local source checkpoint without staging or committing."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.validate_package import _forbidden_file_reason, _secret_findings, _unsafe_path_reason


def git(*arguments):
    return subprocess.check_output(["git", *arguments], cwd=ROOT)


def main():
    checkpoint = ROOT.parent / "astra-checkpoints" / datetime.now().strftime("%Y%m%d-%H%M%S")
    checkpoint.mkdir(parents=True, exist_ok=False)
    names = sorted(set(git("ls-files", "--cached", "--others", "--exclude-standard", "-z").decode("utf-8").split("\0")) - {""})
    manifest = {}
    files = {}
    suffixes = {".py", ".pyw", ".md", ".json", ".txt", ".ps1", ".vbs", ".yml", ".yaml", ".png", ".ico", ".gd", ".tscn", ".godot", ".svg"}
    text_suffixes = suffixes - {".png", ".ico"}
    for name in names:
        path = ROOT / name
        if not path.is_file() or path.is_symlink():
            continue
        if path.suffix.lower() not in suffixes and path.name not in {".env.example", ".gitignore"}:
            continue
        if _unsafe_path_reason(name) or _forbidden_file_reason(name):
            raise ValueError("Forbidden source checkpoint entry: " + name)
        if path.stat().st_size > 5_000_000:
            raise ValueError("Oversize source checkpoint entry: " + name)
        data = path.read_bytes()
        if path.suffix.lower() in text_suffixes and _secret_findings(data.decode("utf-8-sig")):
            raise ValueError("Known secret pattern in source entry: " + name)
        files[name] = data
        manifest[name] = hashlib.sha256(data).hexdigest()
    # Diffs can contain removed secrets too; scan before persisting.
    patch = git("diff", "--binary", "HEAD")
    if _secret_findings(patch.decode("utf-8", errors="replace")):
        raise ValueError("Known secret pattern in checkpoint patch")
    for name, data in files.items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != manifest[name]:
            raise ValueError("Source changed during checkpoint; retry")
    (checkpoint / "working-tree.patch").write_bytes(patch)
    metadata = {"head": git("rev-parse", "HEAD").decode().strip(), "branch": git("branch", "--show-current").decode().strip(), "status": git("status", "--short").decode("utf-8"), "sha256": manifest}
    (checkpoint / "manifest.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    target = checkpoint / "source.zip"
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        for name, expected in manifest.items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == expected
    print(f"CHECKPOINT_PASS: {checkpoint} · {len(files)} files · SHA256/CRC verified · no git mutations")


if __name__ == "__main__":
    main()
