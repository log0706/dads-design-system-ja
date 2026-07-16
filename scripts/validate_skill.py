#!/usr/bin/env python3
"""Validate the structure, metadata, links, separation, and safety of the skill."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


SKILL_ROOT = Path(__file__).resolve().parents[1]
REFERENCES_DIR = SKILL_ROOT / "references"
OFFICIAL_DIR = REFERENCES_DIR / "official"

REQUIRED_FILES = [
    "SKILL.md",
    "README.md",
    "agents/openai.yaml",
    "assets/README.md",
    "references/source-manifest.md",
    "references/official-index.md",
    "references/decision-guide.md",
    "references/implementation-guide.md",
    "references/document-adaptation.md",
    "references/licensing.md",
    "scripts/update_official_sources.py",
    "scripts/validate_skill.py",
]

TEXT_SUFFIXES = {".md", ".py", ".yaml", ".yml", ".json", ".txt"}
LINK_PATTERN = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
SECRET_PATTERNS = [
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(
        r"\b(?:api[_-]?key|client_secret|access_token|refresh_token)\s*[:=]\s*[\"']?[A-Za-z0-9_./+=-]{16,}",
        re.IGNORECASE,
    ),
    re.compile(r"\bauthorization\s*:\s*bearer\s+\S+", re.IGNORECASE),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
]
MISREPRESENTATION_PATTERNS = [
    re.compile(r"(?:この|本)Skillはデジタル庁(?:が提供する)?公式Skillです"),
    re.compile(r"デジタル庁公式(?:の)?Codex Skill"),
    re.compile(r"official skill (?:of|from) the Digital Agency", re.IGNORECASE),
]


class Report:
    def __init__(self) -> None:
        self.successes: list[str] = []
        self.warnings: list[str] = []
        self.failures: list[str] = []

    def success(self, message: str) -> None:
        self.successes.append(message)

    def warning(self, message: str) -> None:
        self.warnings.append(message)

    def failure(self, message: str) -> None:
        self.failures.append(message)

    def print(self) -> None:
        sections = [
            ("成功", "SUCCESS", self.successes),
            ("警告", "WARNING", self.warnings),
            ("失敗", "FAILURE", self.failures),
        ]
        for title, label, messages in sections:
            print(f"\n=== {title} ({len(messages)}) ===")
            if messages:
                for message in messages:
                    print(f"[{label}] {message}")
            else:
                print("(なし)")
        print(
            f"\nSUMMARY success={len(self.successes)} warning={len(self.warnings)} failure={len(self.failures)}"
        )


def read_utf8(path: Path, report: Report) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        report.failure(f"UTF-8で読めません: {path.relative_to(SKILL_ROOT)}")
    except OSError as exc:
        report.failure(f"ファイルを読めません: {path.relative_to(SKILL_ROOT)}: {exc}")
    return None


def frontmatter_fields(text: str) -> tuple[dict[str, str], list[str]]:
    match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", text, re.DOTALL)
    if not match:
        return {}, []
    fields: dict[str, str] = {}
    malformed: list[str] = []
    for line in match.group(1).splitlines():
        if not line.strip():
            continue
        if ":" not in line or line[:1].isspace():
            malformed.append(line)
            continue
        key, value = line.split(":", 1)
        fields[key.strip()] = value.strip().strip("\"'")
    return fields, malformed


def validate_structure(report: Report) -> None:
    missing = [relative for relative in REQUIRED_FILES if not (SKILL_ROOT / relative).is_file()]
    if missing:
        for relative in missing:
            report.failure(f"必須ファイルがありません: {relative}")
    else:
        report.success("必須Skill構造が揃っています")


def validate_skill_metadata(report: Report) -> None:
    skill_path = SKILL_ROOT / "SKILL.md"
    text = read_utf8(skill_path, report)
    if text is None:
        return
    fields, malformed = frontmatter_fields(text)
    if not fields:
        report.failure("SKILL.mdにYAMLフロントマターがありません")
        return
    if malformed:
        report.failure(f"YAMLフロントマターに解析できない行があります: {malformed}")
    if set(fields) != {"name", "description"}:
        report.failure(f"YAMLフロントマターはnameとdescriptionだけにしてください: {sorted(fields)}")
    else:
        report.success("YAMLフロントマターのフィールドはnameとdescriptionだけです")

    name = fields.get("name", "")
    description = fields.get("description", "")
    if name != SKILL_ROOT.name:
        report.failure(f"Skill名とディレクトリ名が一致しません: {name!r} != {SKILL_ROOT.name!r}")
    else:
        report.success("Skill名とディレクトリ名が一致しています")
    if not description:
        report.failure("descriptionが空です")
        return

    positive_terms = [
        "DADS",
        "アクセシビリティ",
        "フォーム",
        "テーブル",
        "ナビゲーション",
        "React",
        "Tailwind",
        "業務資料",
    ]
    negative_terms = ["音楽", "アート", "娯楽", "感情表現", "バックエンド", "使用しない"]
    missing_positive = [term for term in positive_terms if term not in description]
    missing_negative = [term for term in negative_terms if term not in description]
    if missing_positive:
        report.failure(f"暗黙呼び出しの正例に必要な語がdescriptionにありません: {missing_positive}")
    else:
        report.success("暗黙呼び出しの正例をdescriptionが明示しています")
    if missing_negative:
        report.failure(f"暗黙呼び出しの負例に必要な除外語がdescriptionにありません: {missing_negative}")
    else:
        report.success("暗黙呼び出しの負例をdescriptionが除外しています")


def validate_openai_yaml(report: Report) -> None:
    path = SKILL_ROOT / "agents" / "openai.yaml"
    text = read_utf8(path, report)
    if text is None:
        return
    if "$dads-design-system-ja" not in text:
        report.failure("agents/openai.yamlのdefault_promptに明示的なSkill名がありません")
    else:
        report.success("明示的呼び出し名がagents/openai.yamlにあります")
    if not re.search(r"allow_implicit_invocation:\s*true\b", text):
        report.failure("暗黙呼び出しが有効ではありません")
    else:
        report.success("暗黙呼び出しが有効です")
    if re.search(r"^\s*icon_(?:small|large):", text, re.MULTILINE):
        report.failure("公式ロゴ誤認を避けるため、このSkillにアイコンを設定しないでください")
    else:
        report.success("Skillアイコンを設定していません")


def manifest_field(text: str, label: str) -> str | None:
    match = re.search(rf"^- {re.escape(label)}:\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else None


def validate_manifest(report: Report) -> int | None:
    path = REFERENCES_DIR / "source-manifest.md"
    text = read_utf8(path, report)
    if text is None:
        return None
    required = [
        "Skill作成日",
        "情報確認日",
        "DADSサイト表示バージョン",
        "公式Markdown公開日",
        "公式Markdown取得URL",
        "ZIP SHA-256",
        "公式ファイル数",
    ]
    values = {label: manifest_field(text, label) for label in required}
    missing = [label for label, value in values.items() if not value]
    if missing:
        report.failure(f"source-manifest.mdに必須項目がありません: {missing}")
    else:
        report.success("source-manifest.mdに取得日・取得元・版・SHA-256があります")
    source = values.get("公式Markdown取得URL")
    if source and not source.startswith("https://design.digital.go.jp/dads/dads-markdown-"):
        report.failure(f"公式Markdown取得元が想定した公式URLではありません: {source}")
    sha = values.get("ZIP SHA-256")
    if sha and not re.fullmatch(r"[0-9a-f]{64}", sha):
        report.failure("ZIP SHA-256が64桁の小文字16進数ではありません")
    count = values.get("公式ファイル数")
    if count and count.isdigit():
        return int(count)
    if count:
        report.failure(f"公式ファイル数が整数ではありません: {count}")
    return None


def validate_official_tree(report: Report, expected_count: int | None) -> None:
    if not OFFICIAL_DIR.is_dir():
        report.failure("references/official/がありません")
        return
    required = ["README.md", "MANIFEST.md", "index.md"]
    missing = [name for name in required if not (OFFICIAL_DIR / name).is_file()]
    if missing:
        report.failure(f"公式Markdownの必須ファイルがありません: {missing}")
    files = [path for path in OFFICIAL_DIR.rglob("*") if path.is_file()]
    if not files:
        report.failure("公式Markdownが空です")
        return
    if expected_count is not None and len(files) != expected_count:
        report.failure(f"公式ファイル数がmanifestと一致しません: {len(files)} != {expected_count}")
    else:
        report.success(f"公式Markdownが存在します: {len(files)} files")
    non_markdown = [str(path.relative_to(OFFICIAL_DIR)) for path in files if path.suffix.lower() != ".md"]
    if non_markdown:
        report.failure(f"公式ディレクトリにMarkdown以外があります: {non_markdown[:5]}")
    custom_names = {
        "source-manifest.md",
        "official-index.md",
        "decision-guide.md",
        "implementation-guide.md",
        "document-adaptation.md",
        "licensing.md",
    }
    mixed = [name for name in custom_names if (OFFICIAL_DIR / name).exists()]
    if mixed:
        report.failure(f"独自文書が公式ディレクトリに混在しています: {mixed}")
    else:
        report.success("公式Markdownと独自文書が別ディレクトリに分離されています")


def validate_index_links(report: Report) -> None:
    index_path = REFERENCES_DIR / "official-index.md"
    text = read_utf8(index_path, report)
    if text is None:
        return
    checked = 0
    broken: list[str] = []
    escaped: list[str] = []
    root = SKILL_ROOT.resolve()
    for raw_target in LINK_PATTERN.findall(text):
        target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
        if not target or target.startswith("#"):
            continue
        parsed = urlparse(target)
        if parsed.scheme in {"http", "https", "mailto"}:
            continue
        relative_text = unquote(target.split("#", 1)[0])
        resolved = (index_path.parent / relative_text).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            escaped.append(target)
            continue
        checked += 1
        if not resolved.exists():
            broken.append(target)
    if escaped:
        report.failure(f"official-index.mdにSkill外を指すリンクがあります: {escaped}")
    if broken:
        report.failure(f"official-index.mdの相対リンクが壊れています: {broken}")
    elif checked:
        report.success(f"official-index.mdの相対リンクを確認しました: {checked} links")
    else:
        report.failure("official-index.mdに確認可能な相対リンクがありません")


def iter_text_files() -> list[Path]:
    return [
        path
        for path in SKILL_ROOT.rglob("*")
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES
    ]


def validate_secrets(report: Report) -> None:
    hits: list[str] = []
    for path in iter_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                hits.append(str(path.relative_to(SKILL_ROOT)))
                break
    if hits:
        report.failure(f"秘密情報らしい文字列を検出しました: {sorted(set(hits))}")
    else:
        report.success("秘密情報らしい文字列は検出されませんでした")


def validate_non_official_positioning(report: Report) -> None:
    hits: list[str] = []
    local_files = [path for path in iter_text_files() if OFFICIAL_DIR not in path.parents]
    for path in local_files:
        text = read_utf8(path, report)
        if text is None:
            continue
        for pattern in MISREPRESENTATION_PATTERNS:
            if pattern.search(text):
                hits.append(str(path.relative_to(SKILL_ROOT)))
                break
    if hits:
        report.failure(f"デジタル庁公式Skillと誤認させる表現があります: {sorted(set(hits))}")
    else:
        report.success("デジタル庁公式Skillと誤認させる断定表現はありません")
    readme = read_utf8(SKILL_ROOT / "README.md", report)
    if readme is not None and "公式Skillではありません" in readme:
        report.success("README.mdに非公式であることを明記しています")
    elif readme is not None:
        report.failure("README.mdに非公式であることの明記がありません")


def validate_updater_safety(report: Report) -> None:
    path = SKILL_ROOT / "scripts" / "update_official_sources.py"
    text = read_utf8(path, report)
    if text is None:
        return
    required_markers = [
        "TemporaryDirectory",
        "archive.testzip()",
        "stat.S_ISLNK",
        "os.replace",
        "--check-only",
        "MAX_UNCOMPRESSED_BYTES",
    ]
    missing = [marker for marker in required_markers if marker not in text]
    if missing:
        report.failure(f"更新スクリプトの安全機構が不足しています: {missing}")
    else:
        report.success("更新スクリプトに一時領域・ZIP検証・リンク拒否・原子的置換があります")


def main() -> int:
    report = Report()
    validate_structure(report)
    validate_skill_metadata(report)
    validate_openai_yaml(report)
    expected_count = validate_manifest(report)
    validate_official_tree(report, expected_count)
    validate_index_links(report)
    validate_secrets(report)
    validate_non_official_positioning(report)
    validate_updater_safety(report)
    report.print()
    return 1 if report.failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
