#!/usr/bin/env python3
"""Safely refresh the official DADS Markdown snapshot.

The script uses only Python's standard library. It discovers the newest
dads-markdown-YYYYMMDD.zip from the official resource page, validates the ZIP
before extraction, stages the new tree, and replaces the current snapshot only
after every validation has succeeded.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import os
import re
import shutil
import stat
import sys
import tempfile
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


SKILL_ROOT = Path(__file__).resolve().parents[1]
REFERENCES_DIR = SKILL_ROOT / "references"
OFFICIAL_DIR = REFERENCES_DIR / "official"
MANIFEST_PATH = REFERENCES_DIR / "source-manifest.md"

DADS_SITE_URL = "https://design.digital.go.jp/dads/"
RESOURCE_PAGE_URL = "https://design.digital.go.jp/dads/resources/"
ALLOWED_DOWNLOAD_HOST = "design.digital.go.jp"
USER_AGENT = "dads-design-system-ja/1.0 (local Codex skill updater)"

MAX_PAGE_BYTES = 5 * 1024 * 1024
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_FILE_COUNT = 2_000
MAX_SINGLE_FILE_BYTES = 25 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 250 * 1024 * 1024

REQUIRED_PACKAGE_FILES = {"README.md", "MANIFEST.md", "index.md"}
START_MARKER = "<!-- OFFICIAL-METADATA:START -->"
END_MARKER = "<!-- OFFICIAL-METADATA:END -->"


class UpdateError(RuntimeError):
    """Raised when an update cannot be completed safely."""


def request(url: str):
    return Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/zip,application/octet-stream;q=0.9,*/*;q=0.8",
        },
    )


def require_official_https_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != ALLOWED_DOWNLOAD_HOST:
        raise UpdateError(f"公式配布元以外のURLを拒否しました: {url}")


def fetch_bytes(url: str, limit: int) -> tuple[bytes, str]:
    try:
        with urlopen(request(url), timeout=30) as response:
            final_url = response.geturl()
            require_official_https_url(final_url)
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > limit:
                raise UpdateError(f"応答サイズが上限を超えています: {content_length} bytes")
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > limit:
                    raise UpdateError(f"応答サイズが上限 {limit} bytes を超えました")
                chunks.append(chunk)
            return b"".join(chunks), final_url
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        raise UpdateError(f"取得に失敗しました: {url}: {exc}") from exc


def decode_html(data: bytes) -> str:
    # The official pages are UTF-8. The replacement check prevents silent
    # corruption if the response unexpectedly changes encoding.
    text = data.decode("utf-8")
    if "\ufffd" in text:
        raise UpdateError("公式ページのUTF-8デコード結果に置換文字が含まれます")
    return text


def discover_latest_archive() -> tuple[str, str]:
    page_bytes, _ = fetch_bytes(RESOURCE_PAGE_URL, MAX_PAGE_BYTES)
    page = decode_html(page_bytes)
    pattern = re.compile(
        r"href\s*=\s*[\"'](?P<href>[^\"']*dads-markdown-(?P<date>\d{8})\.zip(?:\?[^\"']*)?)[\"']",
        re.IGNORECASE,
    )
    candidates: list[tuple[str, str]] = []
    for match in pattern.finditer(page):
        href = html.unescape(match.group("href"))
        url = urljoin(RESOURCE_PAGE_URL, href)
        require_official_https_url(url)
        candidates.append((match.group("date"), url))

    if not candidates:
        raise UpdateError("リソースページから dads-markdown-YYYYMMDD.zip を検出できませんでした")

    date_code, archive_url = max(candidates, key=lambda item: item[0])
    return archive_url, date_code


def detect_site_version(warnings: list[str]) -> str:
    try:
        page_bytes, _ = fetch_bytes(DADS_SITE_URL, MAX_PAGE_BYTES)
        page = decode_html(page_bytes)
        match = re.search(r"デジタル庁デザインシステム(?:β版)?\s*v(\d+\.\d+\.\d+)", page)
        if not match:
            warnings.append("DADSサイトの表示バージョンを検出できませんでした")
            return "未確認"
        return f"v{match.group(1)}"
    except UpdateError as exc:
        warnings.append(f"DADSサイトの表示バージョンを確認できませんでした: {exc}")
        return "未確認"


def download_archive(url: str, destination: Path) -> tuple[str, int]:
    require_official_https_url(url)
    digest = hashlib.sha256()
    total = 0
    try:
        with urlopen(request(url), timeout=60) as response:
            final_url = response.geturl()
            require_official_https_url(final_url)
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > MAX_ARCHIVE_BYTES:
                raise UpdateError(f"ZIPが上限を超えています: {content_length} bytes")
            with destination.open("wb") as output:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_ARCHIVE_BYTES:
                        raise UpdateError(f"ZIPが上限 {MAX_ARCHIVE_BYTES} bytes を超えました")
                    digest.update(chunk)
                    output.write(chunk)
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        raise UpdateError(f"ZIPの取得に失敗しました: {url}: {exc}") from exc

    if total == 0:
        raise UpdateError("取得したZIPが空です")
    return digest.hexdigest(), total


def normalized_member_path(info: zipfile.ZipInfo) -> PurePosixPath:
    name = info.filename
    if not name or "\\" in name or "\x00" in name:
        raise UpdateError(f"不正なZIPエントリ名です: {name!r}")
    if name.startswith("/") or re.match(r"^[A-Za-z]:", name):
        raise UpdateError(f"絶対パスのZIPエントリを拒否しました: {name}")

    relative = PurePosixPath(name)
    if any(part in {"", ".", ".."} for part in relative.parts):
        raise UpdateError(f"パストラバーサルの可能性があるZIPエントリです: {name}")

    mode = info.external_attr >> 16
    if mode and stat.S_ISLNK(mode):
        raise UpdateError(f"シンボリックリンクのZIPエントリを拒否しました: {name}")
    return relative


def inspect_archive(archive_path: Path) -> tuple[list[tuple[zipfile.ZipInfo, PurePosixPath]], int]:
    try:
        with zipfile.ZipFile(archive_path) as archive:
            if archive.testzip() is not None:
                raise UpdateError("ZIPのCRC検証に失敗しました")
            infos = [info for info in archive.infolist() if not info.is_dir()]
    except (zipfile.BadZipFile, OSError) as exc:
        raise UpdateError(f"ZIPを読み取れません: {exc}") from exc

    if not infos:
        raise UpdateError("ZIPにファイルが含まれていません")
    if len(infos) > MAX_FILE_COUNT:
        raise UpdateError(f"ZIPのファイル数が上限を超えています: {len(infos)}")

    checked: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
    seen: set[str] = set()
    uncompressed_total = 0
    for info in infos:
        relative = normalized_member_path(info)
        case_key = relative.as_posix().casefold()
        if case_key in seen:
            raise UpdateError(f"大文字小文字を無視すると重複するZIPエントリです: {relative}")
        seen.add(case_key)
        if info.file_size > MAX_SINGLE_FILE_BYTES:
            raise UpdateError(f"単一ファイルの上限を超えています: {relative}: {info.file_size} bytes")
        uncompressed_total += info.file_size
        if uncompressed_total > MAX_UNCOMPRESSED_BYTES:
            raise UpdateError("ZIP展開後サイズが上限を超えています")
        checked.append((info, relative))
    return checked, uncompressed_total


def extract_archive(archive_path: Path, destination: Path) -> None:
    checked, _ = inspect_archive(archive_path)
    destination.mkdir(parents=True, exist_ok=False)
    root = destination.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        for info, relative in checked:
            target = (destination / Path(*relative.parts)).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise UpdateError(f"展開先外を指すZIPエントリです: {relative}") from exc
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)


def locate_package_root(extracted: Path) -> Path:
    if all((extracted / name).is_file() for name in REQUIRED_PACKAGE_FILES):
        return extracted
    children = [item for item in extracted.iterdir() if item.is_dir()]
    if len(children) == 1 and all((children[0] / name).is_file() for name in REQUIRED_PACKAGE_FILES):
        return children[0]
    raise UpdateError("展開内容に README.md、MANIFEST.md、index.md が揃っていません")


def validate_package_tree(package_root: Path) -> int:
    missing = sorted(name for name in REQUIRED_PACKAGE_FILES if not (package_root / name).is_file())
    if missing:
        raise UpdateError(f"公式Markdownの必須ファイルがありません: {', '.join(missing)}")

    files = [path for path in package_root.rglob("*") if path.is_file()]
    if not files:
        raise UpdateError("展開後の公式ファイルがありません")
    if len(files) > MAX_FILE_COUNT:
        raise UpdateError(f"展開後のファイル数が上限を超えています: {len(files)}")

    root = package_root.resolve()
    for path in files:
        resolved = path.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise UpdateError(f"公式ディレクトリ外を指すファイルがあります: {path}") from exc
        if path.is_symlink():
            raise UpdateError(f"展開後にシンボリックリンクがあります: {path}")
        if path.suffix.lower() != ".md":
            raise UpdateError(f"Markdown以外のファイルを拒否しました: {path.relative_to(package_root)}")
        try:
            path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise UpdateError(f"UTF-8でない公式ファイルがあります: {path.relative_to(package_root)}") from exc
    return len(files)


def build_manifest_text(
    current: str,
    *,
    checked_date: str,
    site_version: str,
    publication_date: str,
    archive_url: str,
    sha256: str,
    file_count: int,
) -> str:
    block = "\n".join(
        [
            START_MARKER,
            f"- 情報確認日: {checked_date}",
            f"- DADSサイト表示バージョン: {site_version}",
            f"- 公式Markdown公開日: {publication_date}",
            f"- 公式Markdown取得URL: {archive_url}",
            f"- ZIP SHA-256: {sha256}",
            f"- 公式ファイル数: {file_count}",
            END_MARKER,
        ]
    )
    pattern = re.compile(re.escape(START_MARKER) + r".*?" + re.escape(END_MARKER), re.DOTALL)
    if not pattern.search(current):
        raise UpdateError("source-manifest.md に公式メタデータ更新マーカーがありません")
    return pattern.sub(block, current, count=1)


def atomic_write_text(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(content, encoding="utf-8", newline="\n")
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def field_value(manifest: str, label: str) -> str:
    match = re.search(rf"^- {re.escape(label)}:\s*(.+)$", manifest, re.MULTILINE)
    return match.group(1).strip() if match else "未確認"


def install_snapshot(stage_dir: Path, manifest_text: str) -> list[str]:
    if OFFICIAL_DIR.exists() and not OFFICIAL_DIR.is_dir():
        raise UpdateError(f"公式データの配置先がディレクトリではありません: {OFFICIAL_DIR}")

    backup_dir = REFERENCES_DIR / f".official-backup-{uuid.uuid4().hex}"
    previous_manifest = MANIFEST_PATH.read_text(encoding="utf-8")
    had_official = OFFICIAL_DIR.exists()
    installed_new = False
    cleanup_warnings: list[str] = []

    try:
        if had_official:
            os.replace(OFFICIAL_DIR, backup_dir)
        os.replace(stage_dir, OFFICIAL_DIR)
        installed_new = True
        atomic_write_text(MANIFEST_PATH, manifest_text)
    except Exception:
        if installed_new and OFFICIAL_DIR.exists():
            shutil.rmtree(OFFICIAL_DIR)
        if backup_dir.exists():
            os.replace(backup_dir, OFFICIAL_DIR)
        atomic_write_text(MANIFEST_PATH, previous_manifest)
        raise
    else:
        if backup_dir.exists():
            try:
                shutil.rmtree(backup_dir)
            except OSError as exc:
                cleanup_warnings.append(f"旧データのバックアップを削除できませんでした: {backup_dir}: {exc}")
    return cleanup_warnings


def run(check_only: bool) -> int:
    if not MANIFEST_PATH.is_file():
        raise UpdateError(f"source-manifest.md がありません: {MANIFEST_PATH}")

    warnings: list[str] = []
    archive_url, date_code = discover_latest_archive()
    publication_date = datetime.strptime(date_code, "%Y%m%d").date().isoformat()
    site_version = detect_site_version(warnings)
    checked_date = datetime.now(timezone(timedelta(hours=9))).date().isoformat()

    current_manifest = MANIFEST_PATH.read_text(encoding="utf-8")
    old_url = field_value(current_manifest, "公式Markdown取得URL")
    old_hash = field_value(current_manifest, "ZIP SHA-256")
    old_count = field_value(current_manifest, "公式ファイル数")

    with tempfile.TemporaryDirectory(prefix="dads-official-update-") as temporary_root:
        temporary = Path(temporary_root)
        archive_path = temporary / "official.zip"
        extracted = temporary / "extracted"

        sha256, archive_size = download_archive(archive_url, archive_path)
        extract_archive(archive_path, extracted)
        package_root = locate_package_root(extracted)
        file_count = validate_package_tree(package_root)

        print(f"[検出] DADSサイト表示バージョン: {site_version}")
        print(f"[検出] 公式Markdown公開日: {publication_date}")
        print(f"[検出] 取得URL: {archive_url}")
        print(f"[検証] ZIPサイズ: {archive_size} bytes")
        print(f"[検証] SHA-256: {sha256}")
        print(f"[検証] 公式ファイル数: {file_count}")

        manifest_text = build_manifest_text(
            current_manifest,
            checked_date=checked_date,
            site_version=site_version,
            publication_date=publication_date,
            archive_url=archive_url,
            sha256=sha256,
            file_count=file_count,
        )

        if check_only:
            print("[変更なし] --check-only のためファイルを更新していません")
        else:
            same_archive = old_hash == sha256 and OFFICIAL_DIR.is_dir()
            if same_archive:
                existing_count = validate_package_tree(OFFICIAL_DIR)
                if existing_count != file_count:
                    raise UpdateError(
                        f"同じSHA-256ですが既存ファイル数が一致しません: {existing_count} != {file_count}"
                    )
                atomic_write_text(MANIFEST_PATH, manifest_text)
                print("[変更] 公式データは同一のため置換せず、情報確認日だけ更新しました")
            else:
                stage_dir = REFERENCES_DIR / f".official-stage-{uuid.uuid4().hex}"
                shutil.copytree(package_root, stage_dir)
                try:
                    staged_count = validate_package_tree(stage_dir)
                    if staged_count != file_count:
                        raise UpdateError("ステージング後のファイル数が一致しません")
                    warnings.extend(install_snapshot(stage_dir, manifest_text))
                finally:
                    if stage_dir.exists():
                        shutil.rmtree(stage_dir)
                print(f"[変更] 取得URL: {old_url} -> {archive_url}")
                print(f"[変更] SHA-256: {old_hash} -> {sha256}")
                print(f"[変更] 公式ファイル数: {old_count} -> {file_count}")

    for warning in warnings:
        print(f"[警告] {warning}")
    print("[完了] 既存データを処理成功前に削除せず更新しました")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DADS公式Markdownを安全に更新します")
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="最新版を取得・検証するが、Skill内のファイルは変更しない",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        return run(args.check_only)
    except UpdateError as exc:
        print(f"[失敗] {exc}", file=sys.stderr)
        print("[保全] 既存の公式データは更新していません", file=sys.stderr)
        return 1
    except Exception as exc:  # Defensive: preserve the current tree on unknown failures.
        print(f"[失敗] 予期しないエラー: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("[保全] 既存の公式データの復元を試みました", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
