"""Манифест исходных данных: SHA-256, размер, нормализованное имя.

Исходники в `SOURCE_DATA_DIR` считаются immutable. Этот скрипт умеет две вещи:

    python -m scripts.source_manifest build    # создать/обновить манифест
    python -m scripts.source_manifest verify   # убедиться, что ничего не менялось

`verify` возвращает ненулевой код, если хоть один файл изменился, исчез или
появился новый. Это единственный способ доказать, что импорт не трогает
оригиналы, и одновременно — защита от «данные поехали, а мы не заметили».

Про имена файлов. Часть исходников пришла с macOS, где имена хранятся в
Unicode NFD: «й» записана как «и» + U+0306. Прямое сравнение с NFC-строкой,
которую даёт Windows-ввод, не совпадает, и файл выглядит отсутствующим, хотя
он на месте. Поэтому все имена сопоставляются через `normalize_name()`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import unicodedata
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_SOURCE_DIR = Path(r"C:\Users\erbot\Downloads\ДЭР")
DEFAULT_MANIFEST = Path(__file__).resolve().parents[2] / "data" / "source-manifest.json"

# Расширения, которые вообще считаются исходными данными.
DATA_SUFFIXES = {".xlsx", ".xls", ".docx", ".json", ".geojson", ".zip", ".csv", ".jpg", ".png"}

CHUNK = 1024 * 1024


def normalize_name(name: str) -> str:
    """Каноническая форма имени файла для сравнения.

    NFC + casefold. Без этого файлы слоёв 8.6 и 8.7 не находятся по имени,
    набранному в NFC.
    """
    return unicodedata.normalize("NFC", name).casefold()


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class SourceEntry:
    """Одна строка манифеста."""

    name: str
    """Имя файла как оно лежит на диске (может быть в NFD)."""

    normalized_name: str
    """Имя в NFC+casefold — ключ для сопоставления."""

    size_bytes: int
    sha256: str
    modified_at: str
    """mtime файла в ISO-8601 UTC. Информационно: доверяем только sha256."""

    def matches(self, other: SourceEntry) -> bool:
        return self.sha256 == other.sha256 and self.size_bytes == other.size_bytes


def scan(source_dir: Path) -> list[SourceEntry]:
    if not source_dir.is_dir():
        raise SystemExit(f"Каталог источников не найден: {source_dir}")

    entries: list[SourceEntry] = []
    for path in sorted(source_dir.iterdir(), key=lambda p: normalize_name(p.name)):
        if not path.is_file() or path.suffix.casefold() not in DATA_SUFFIXES:
            continue
        stat = path.stat()
        entries.append(
            SourceEntry(
                name=path.name,
                normalized_name=normalize_name(path.name),
                size_bytes=stat.st_size,
                sha256=sha256_of(path),
                modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
            )
        )
    return entries


def resolve_source(source_dir: Path, wanted: str) -> Path:
    """Найти файл в каталоге источников по имени, устойчиво к NFD.

    Импортёры обязаны ходить за файлами только через эту функцию, а не
    собирать путь конкатенацией — иначе слои 8.6 и 8.7 «пропадают».
    """
    target = normalize_name(wanted)
    for path in source_dir.iterdir():
        if path.is_file() and normalize_name(path.name) == target:
            return path
    available = "\n  ".join(sorted(p.name for p in source_dir.iterdir() if p.is_file()))
    raise FileNotFoundError(
        f"Файл {wanted!r} не найден в {source_dir}.\nЕсть:\n  {available}"
    )


def load_manifest(manifest_path: Path) -> dict[str, SourceEntry]:
    if not manifest_path.exists():
        return {}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {
        item["normalized_name"]: SourceEntry(**item) for item in payload.get("files", [])
    }


def write_manifest(manifest_path: Path, source_dir: Path, entries: list[SourceEntry]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "source_dir": str(source_dir),
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "file_count": len(entries),
        "files": [asdict(entry) for entry in entries],
    }
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def cmd_build(source_dir: Path, manifest_path: Path) -> int:
    entries = scan(source_dir)
    write_manifest(manifest_path, source_dir, entries)
    print(f"Манифест записан: {manifest_path}")
    print(f"Файлов: {len(entries)}, суммарно {sum(e.size_bytes for e in entries):,} байт")
    for entry in entries:
        print(f"  {entry.sha256[:12]}  {entry.size_bytes:>12,}  {entry.name}")
    return 0


def cmd_verify(source_dir: Path, manifest_path: Path) -> int:
    recorded = load_manifest(manifest_path)
    if not recorded:
        print(f"Манифест отсутствует или пуст: {manifest_path}", file=sys.stderr)
        print("Сначала выполните: python -m scripts.source_manifest build", file=sys.stderr)
        return 2

    current = {entry.normalized_name: entry for entry in scan(source_dir)}

    changed = [k for k in recorded.keys() & current.keys() if not recorded[k].matches(current[k])]
    missing = sorted(recorded.keys() - current.keys())
    added = sorted(current.keys() - recorded.keys())

    for key in sorted(changed):
        print(f"ИЗМЕНЁН: {current[key].name}", file=sys.stderr)
        was, now = recorded[key], current[key]
        print(f"  было:  {was.sha256}  {was.size_bytes:,} байт", file=sys.stderr)
        print(f"  стало: {now.sha256}  {now.size_bytes:,} байт", file=sys.stderr)
    for key in missing:
        print(f"ИСЧЕЗ:   {recorded[key].name}", file=sys.stderr)
    for key in added:
        print(f"НОВЫЙ:   {current[key].name}", file=sys.stderr)

    if changed or missing or added:
        print(
            f"\nРасхождений: изменено {len(changed)}, исчезло {len(missing)}, "
            f"новых {len(added)}",
            file=sys.stderr,
        )
        return 1

    print(f"Все {len(current)} файлов совпадают с манифестом — источники не менялись.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path(os.environ.get("SOURCE_DATA_DIR") or DEFAULT_SOURCE_DIR),
        help="каталог с исходниками (по умолчанию — $SOURCE_DATA_DIR)",
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args(argv)

    if args.command == "build":
        return cmd_build(args.source_dir, args.manifest)
    return cmd_verify(args.source_dir, args.manifest)


if __name__ == "__main__":
    raise SystemExit(main())
