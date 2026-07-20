# 記事自動生成パイプライン セットアップ手順

## 仕組み
毎週月曜9時（＋手動実行）に GitHub Actions が動き、

1. `pipeline/keywords.csv` の一番上の `pending` キーワードで記事を自動生成（Claude API）
2. FAQ同期・JSON-LD・受診目安の有無などを自動検証
3. `column-○○.html` 作成＋`column.html`（一覧カード）＋`sitemap.xml` を更新して **Pull Request を作成**
4. **Gmail にレビュー用メール（記事HTML添付＋PRリンク）が届く**
5. あなたが内容確認 → **PRをMerge → Vercelが自動デプロイ＝公開**

Mergeが「薬剤師承認」のゲートです。Mergeしない限り公開されません。
公開したくない場合は PR を Close するだけです。

## 初回セットアップ（3ステップ・各自分で操作）

### 1. Anthropic APIキーを用意
- https://console.anthropic.com/ でAPIキーを作成（従量課金・記事1本あたり数十円程度）

### 2. Gmailのアプリパスワードを用意
- Googleアカウントで2段階認証を有効化
- https://myaccount.google.com/apppasswords で「アプリパスワード」を発行（16桁）
- ※通常のGmailパスワードではなくアプリパスワードを使います

### 3. GitHubリポジトリに登録
リポジトリの Settings で以下を設定:

**Settings → Secrets and variables → Actions → New repository secret** で3つ登録:
| Name | 値 |
|---|---|
| `ANTHROPIC_API_KEY` | 手順1のAPIキー |
| `GMAIL_USERNAME` | あなたのGmailアドレス |
| `GMAIL_APP_PASSWORD` | 手順2の16桁 |

**Settings → Actions → General → Workflow permissions** で:
- 「Read and write permissions」を選択
- 「Allow GitHub Actions to create and approve pull requests」にチェック

## 使い方
- **手動で今すぐ生成**: Actions タブ → 「新規コラム記事の自動生成」 → Run workflow
- **ネタの追加**: `pipeline/keywords.csv` に行を追加（statusは `pending`）
- **止めたいとき**: keywords.csv の pending が無くなると何もせず終了します。
  完全に止める場合はワークフローファイルの `schedule:` を削除

## 公開後にやること
- Search Console → URL検査 → 新記事URLの「インデックス登録をリクエスト」

## 注意
- 生成記事の成分名・数値・受診目安は **必ず薬剤師として確認してからMerge** してください
- 監修者の実名を入れる運用にする場合は、雛形（column-cold-early.html）の
  meta-line と JSON-LD を更新すれば以後の生成記事にも反映されます
