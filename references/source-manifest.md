# Source Manifest

このファイルは、Skill内に格納した公式情報の取得記録です。`references/official/` はデジタル庁配布の公式Markdown、その他の参照文書はローカル独自の要約・応用ルールです。

- Skill作成日: 2026-07-16
- 管理対象: `dads-design-system-ja`

## 現在の公式スナップショット

<!-- OFFICIAL-METADATA:START -->
- 情報確認日: 2026-07-16
- DADSサイト表示バージョン: v2.16.0
- 公式Markdown公開日: 2026-07-15
- 公式Markdown取得URL: https://design.digital.go.jp/dads/dads-markdown-20260715.zip
- ZIP SHA-256: 6ed1479f824569347ee6406d0f210b47d7695c5abee7624a462cdc0cfc9ff28c
- 公式ファイル数: 125
<!-- OFFICIAL-METADATA:END -->

## 公式参照先

- DADS公式サイト: https://design.digital.go.jp/dads/
- リソース一覧: https://design.digital.go.jp/dads/resources/
- DADSの使い方: https://design.digital.go.jp/dads/guidance/how-to-use/
- アクセシビリティ: https://design.digital.go.jp/dads/guidance/accessibility/
- 基本デザイン: https://design.digital.go.jp/dads/foundations/
- コンポーネント: https://design.digital.go.jp/dads/components/
- Figma: https://www.figma.com/community/file/1377880368787735577
- HTMLサンプル: https://github.com/digital-go-jp/design-system-example-components-html
- HTML Storybook: https://design.digital.go.jp/dads/html/
- Reactサンプル: https://github.com/digital-go-jp/design-system-example-components-react
- React Storybook: https://design.digital.go.jp/dads/react/
- Tailwindテーマ: https://github.com/digital-go-jp/tailwind-theme-plugin
- イラスト・アイコン素材: https://www.digital.go.jp/policies/servicedesign/designsystem/Illustration_Icons
- イラスト・アイコン利用規約: https://www.digital.go.jp/policies/servicedesign/designsystem/Illustration_Icons/terms_of_use
- DADS利用上の注意事項: https://design.digital.go.jp/dads/introduction/notices/
- デジタル庁コピーライトポリシー: https://www.digital.go.jp/copyright-policy

## GitHubリポジトリのライセンス

- HTMLサンプル: MIT License
- Reactサンプル: MIT License
- Tailwindテーマ: MIT License

確認根拠は各公式リポジトリの `LICENSE` とREADME、およびDADSの「利用上の注意事項」です。実際にコードを再利用する時点で、対象コミットの `LICENSE` を再確認してください。

## 公式情報と独自情報の区別

- `references/official/`: 公式ZIPを原構造のまま展開した原文。独自追記を禁止する。
- `references/source-manifest.md`: 取得・検証メタデータ。ローカル管理情報。
- `references/official-index.md`: 公式原文へのローカル索引。
- `references/decision-guide.md`、`implementation-guide.md`、`document-adaptation.md`、`licensing.md`: Codex向けの独自要約・判断・応用ルール。

## 公開リポジトリでの配布

公式Markdown原文はGit管理対象外とし、公開リポジトリへ同梱しません。利用者が `scripts/update_official_sources.py` を明示的に実行した場合だけ、公式配布元からローカルへ取得します。このファイルの取得記録は、更新スクリプトを実行したローカル環境の状態を示します。

## 最終更新方法

公式情報の更新を明示的に依頼された場合だけ、Skillルートで次を実行します。

```text
python scripts/update_official_sources.py
python scripts/validate_skill.py
```

更新スクリプトはリソース一覧から最新版を検出し、SHA-256、安全なZIPパス、必須ファイル、展開後の構造を確認してから公式ディレクトリとこのメタデータブロックを更新します。
