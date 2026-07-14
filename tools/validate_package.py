from __future__ import annotations

import argparse
import re
import zipfile
from pathlib import Path, PurePosixPath


FORBIDDEN_DIRECTORY_NAMES = {
    ".git",
    ".venv",
    ".cache",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    "cache",
    "logs",
}

FORBIDDEN_EXACT_FILENAMES = {
    ".env",
    "voice_test_log.txt",
}

FORBIDDEN_SUFFIXES = {
    ".mp3",
    ".pyc",
}

SOURCE_ONLY_EXCLUDED_DIRECTORIES = {
    "_review_context",
    "_release_context",
}

SOURCE_ONLY_EXCLUDED_FILES = {
    ".env.sanitized",
    "astra-v1.2-last-log.txt",
}

SECRET_ASSIGNMENT_RE = re.compile(
    r"(?m)^\s*(GEMINI_API_KEY|LLM_API_KEY|OPENAI_API_KEY)\s*=\s*(.*?)\s*$"
)
TOKEN_PATTERNS = (
    ("Google API key", re.compile(r"AIza[0-9A-Za-z_-]{30,}")),
    ("OpenAI-style API key", re.compile(r"sk-[0-9A-Za-z_-]{20,}")),
)

ALLOWED_SECRET_VALUES = {
    "",
    "REMOVED",
    "REDACTED",
    "PASTE_YOUR_GEMINI_KEY_HERE",
    "YOUR_API_KEY_HERE",
}


def _normalized_member_name(raw_name: str) -> str:
    return raw_name.replace("\\", "/")


def _unsafe_path_reason(raw_name: str) -> str:
    normalized = _normalized_member_name(raw_name)
    path = PurePosixPath(normalized)

    if normalized.startswith("/"):
        return "absolute path"
    if re.match(r"^[A-Za-z]:/", normalized):
        return "drive-qualified path"
    if ".." in path.parts:
        return "path traversal"
    return ""


def _is_backup_name(name: str) -> bool:
    lowered = name.lower()
    return (
        ".backup-" in lowered
        or lowered.endswith((".bak", ".backup", ".orig", "~"))
    )


def _forbidden_file_reason(raw_name: str) -> str:
    normalized = _normalized_member_name(raw_name)
    path = PurePosixPath(normalized)
    lowered_parts = tuple(part.lower() for part in path.parts)

    for part in lowered_parts[:-1]:
        if part in FORBIDDEN_DIRECTORY_NAMES:
            return f"forbidden directory: {part}"

    filename = lowered_parts[-1] if lowered_parts else ""
    if filename in FORBIDDEN_EXACT_FILENAMES:
        return f"forbidden file: {filename}"
    if any(filename.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES):
        return f"forbidden suffix: {Path(filename).suffix}"
    if _is_backup_name(filename):
        return "backup file"
    return ""


def _decode_text(data: bytes) -> str:
    if not data or b"\x00" in data[:4096]:
        return ""
    return data.decode("utf-8-sig", errors="replace")


def _secret_findings(text: str) -> list[str]:
    findings: list[str] = []

    for match in SECRET_ASSIGNMENT_RE.finditer(text):
        key_name = match.group(1)
        value = match.group(2).strip().strip('"\'')
        if value.upper() not in ALLOWED_SECRET_VALUES and not value.upper().startswith(
            ("PASTE_", "YOUR_")
        ):
            findings.append(f"non-sanitized {key_name} assignment")

    for label, pattern in TOKEN_PATTERNS:
        if pattern.search(text):
            findings.append(label)

    return findings


def _source_file_is_packaged(relative_path: Path) -> bool:
    lowered_parts = tuple(part.lower() for part in relative_path.parts)
    if any(
        part in FORBIDDEN_DIRECTORY_NAMES or part in SOURCE_ONLY_EXCLUDED_DIRECTORIES
        for part in lowered_parts[:-1]
    ):
        return False
    filename = lowered_parts[-1] if lowered_parts else ""
    if filename in FORBIDDEN_EXACT_FILENAMES or filename in SOURCE_ONLY_EXCLUDED_FILES:
        return False
    if filename.endswith("-last-log.txt"):
        return False
    if any(filename.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES):
        return False
    return not _is_backup_name(filename)


def _source_match_findings(archive: zipfile.ZipFile, source_root: Path) -> list[str]:
    findings: list[str] = []
    archive_members = {
        _normalized_member_name(info.filename).rstrip("/"): info
        for info in archive.infolist()
        if not info.is_dir()
    }

    for source_path in sorted(source_root.rglob("*")):
        if not source_path.is_file():
            continue
        relative = source_path.relative_to(source_root)
        if not _source_file_is_packaged(relative):
            continue
        member_name = relative.as_posix()
        info = archive_members.get(member_name)
        if info is None:
            findings.append(f"{member_name}: missing compared with source root")
            continue
        if archive.read(info) != source_path.read_bytes():
            findings.append(f"{member_name}: content differs from source root")

    return findings


def validate_zip(path: str | Path, source_root: str | Path | None = None) -> list[str]:
    archive_path = Path(path)
    problems: list[str] = []

    if not archive_path.is_file():
        return [f"archive not found: {archive_path}"]
    if not zipfile.is_zipfile(archive_path):
        return [f"not a valid zip archive: {archive_path}"]

    seen_names: set[str] = set()

    with zipfile.ZipFile(archive_path) as archive:
        for info in archive.infolist():
            normalized = _normalized_member_name(info.filename)
            unsafe_reason = _unsafe_path_reason(info.filename)
            if unsafe_reason:
                problems.append(f"{normalized}: {unsafe_reason}")
                continue

            canonical = normalized.casefold()
            if canonical in seen_names:
                problems.append(f"{normalized}: duplicate archive path")
            seen_names.add(canonical)

            if info.is_dir():
                for part in PurePosixPath(normalized).parts:
                    if part.lower() in FORBIDDEN_DIRECTORY_NAMES:
                        problems.append(
                            f"{normalized}: forbidden directory: {part.lower()}"
                        )
                        break
                continue

            forbidden_reason = _forbidden_file_reason(info.filename)
            if forbidden_reason:
                problems.append(f"{normalized}: {forbidden_reason}")
                continue

            # Source/config files are small. The cap prevents a malformed archive
            # from forcing an unbounded in-memory secret scan.
            if info.file_size > 5_000_000:
                continue

            text = _decode_text(archive.read(info))
            for finding in _secret_findings(text):
                problems.append(f"{normalized}: {finding}")

        if source_root is not None:
            root = Path(source_root)
            if not root.is_dir():
                problems.append(f"source root not found: {root}")
            else:
                problems.extend(_source_match_findings(archive, root))

    if not seen_names:
        problems.append("archive is empty")

    return problems


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate an Astra review/release ZIP for forbidden files and secrets."
    )
    parser.add_argument("zip_path", help="Path to the ZIP archive to validate.")
    parser.add_argument(
        "--source-root",
        help="Also require packaged project files to match this source tree byte-for-byte.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    problems = validate_zip(args.zip_path, source_root=args.source_root)

    if problems:
        print("Astra package validation failed:")
        for problem in problems:
            print(f"[FAIL] {problem}")
        return 1

    print(f"Astra package validation passed: {args.zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
