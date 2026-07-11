<div align="center">

# multi-agent-shogun

**AIコーディング軍団統率システム — Multi-CLI対応**

*コマンド1つで、10体のAIエージェントが並列稼働 — **Claude Code / OpenAI Codex / GitHub Copilot / Kimi Code / OpenCode / Cursor / Antigravity** 混成軍*

**Talk Coding — Vibe Codingではなく、スマホに話すだけでAIが実行**

[![GitHub Stars](https://img.shields.io/github/stars/yohey-w/multi-agent-shogun?style=social)](https://github.com/yohey-w/multi-agent-shogun)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![v5.1.0 Karo Traffic Control](https://img.shields.io/badge/v5.1.0-Karo%20Traffic%20Control-ff6600?style=flat-square&logo=data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxNiIgaGVpZ2h0PSIxNiI+PHRleHQgeD0iMCIgeT0iMTIiIGZvbnQtc2l6ZT0iMTIiPuKalTwvdGV4dD48L3N2Zz4=)](https://github.com/yohey-w/multi-agent-shogun/releases/tag/v5.1.0)
[![Shell](https://img.shields.io/badge/Shell%2FBash-100%25-green)]()

[English](README.md) | [日本語](README_ja.md)

</div>

<p align="center">
  <img src="images/screenshots/hero/latest-translucent-20260210-190453.png" alt="将軍ペインでの最新半透過セッションキャプチャ" width="940">
</p>

<p align="center">
  <img src="images/screenshots/hero/latest-translucent-20260208-084602.png" alt="将軍ペインでの自然言語コマンド入力" width="420">
  <img src="images/company-creed-all-panes.png" alt="家老と足軽が全ペインで並列反応する様子" width="520">
</p>

<p align="center"><i>家老1体が足軽7体+軍師1体を統率 — 実際の稼働画面、モックデータなし</i></p>

---

## クイックスタート

**必要なもの:** tmux、bash 4+、以下のいずれか: [Claude Code](https://claude.ai/code) / Codex / Copilot / Kimi / OpenCode

```bash
git clone https://github.com/yohey-w/multi-agent-shogun
cd multi-agent-shogun
bash first_setup.sh                        # 初回セットアップ: 設定・依存関係・MCP
source ~/.bashrc                           # PATH反映
claude --dangerously-skip-permissions      # 初回のみ: OAuth認証 + Bypass承認 → /exit で退出
bash shutsujin_departure.sh                # 全エージェント起動
```

> 詳しいインストール手順（Windows含む）と「最初の30分の歩き方」は下記 [🚀 クイックスタート](#-クイックスタート) と [📖 基本的な使い方](#-基本的な使い方) を参照。

将軍ペインに命令を入力：

> 「ユーザー認証の REST API を作って」

将軍が委譲 → 家老が分解 → 足軽7体が並列実行。
あとはダッシュボードを眺めるだけ。

> **もっと詳しく知りたい方へ:** 以降のセクションでアーキテクチャ・設定・メモリ設計・Multi-CLI対応を解説しています。

---

## GitHub境界連携

Codex DesktopとShogunを独立運用し、GitHubのbranch・commit・PRと必要なDrive成果物だけを共有する場合は、[GitHub Boundary Operation](docs/github-boundary-operation.md)を参照してください。queue、認証、session、tmux、生ログはPC間で共有しません。

---

## これは何？

**multi-agent-shogun** は、複数のAIコーディングCLIインスタンスを同時に実行し、戦国時代の軍制のように統率するシステムです。**Claude Code**、**OpenAI Codex**、**GitHub Copilot**、**Kimi Code**、**OpenCode**、**Cursor**、**Antigravity** の7CLIに対応。

**なぜ使うのか？**
- 1つの命令で、7体のAIワーカー+1体の軍師が並列で実行
- 待ち時間なし - タスクがバックグラウンドで実行中も次の命令を出せる
- AIがセッションを跨いであなたの好みを記憶（Memory MCP）
- ダッシュボードでリアルタイム進捗確認

```
      あなた（上様）
           │
           ▼ 命令を出す
    ┌─────────────┐
    │   SHOGUN    │  ← 命令を受け取り、即座に委譲
    └──────┬──────┘
           │ YAMLファイル + tmux
    ┌──────▼──────┐
    │    KARO     │  ← タスクをワーカーに分配
    └──────┬──────┘
           │
  ┌─┬─┬─┬─┴─┬─┬─┬────────┐
  │1│2│3│4│5│6│7│ GUNSHI │  ← 7体のワーカー + 1体の軍師
  └─┴─┴─┴─┴─┴─┴─┴────────┘
     ASHIGARU      軍師
```

---

## なぜ Shogun なのか？

多くのマルチエージェントフレームワークは、連携のためにAPIトークンを消費します。Shogunは違います。

| | Claude Code `Task` ツール | Claude Code Agent Teams | LangGraph | CrewAI | **multi-agent-shogun** |
|---|---|---|---|---|---|
| **アーキテクチャ** | 1プロセス内のサブエージェント | リード+チームメイト（JSONメールボックス） | グラフベースの状態機械 | ロールベースエージェント | tmux経由の階層構造 |
| **並列性** | 逐次実行（1つずつ） | 複数の独立セッション | 並列ノード（v0.2+） | 限定的 | **8体の独立エージェント** |
| **連携コスト** | TaskごとにAPIコール | 高い（各チームメイト=別コンテキスト） | API + インフラ（Postgres/Redis） | API + CrewAIプラットフォーム | **ゼロ**（YAML + tmux） |
| **Multi-CLI** | Claude Codeのみ | Claude Codeのみ | 任意のLLM API | 任意のLLM API | **7 CLI**（Claude/Codex/Copilot/Kimi/OpenCode/Cursor/Antigravity） |
| **可観測性** | Claudeのログのみ | tmux分割ペインまたはインプロセス | LangSmith連携 | OpenTelemetry | **ライブtmuxペイン** + ダッシュボード |
| **スキル発見** | なし | なし | なし | なし | **ボトムアップ自動提案** |
| **セットアップ** | Claude Code内蔵 | 内蔵（実験的） | 重い（インフラ必要） | pip install | シェルスクリプト |

### 他のフレームワークとの違い

**連携コストゼロ** — エージェント間の通信はディスク上のYAMLファイル。APIコールは実際の作業にのみ使われ、オーケストレーションには使われません。8体のエージェントを動かしても、支払うのは8体分の作業コストだけです。

**完全な透明性** — すべてのエージェントが見えるtmuxペインで動作。すべての指示・報告・判断がプレーンなYAMLファイルで、読んで、diffして、バージョン管理できます。ブラックボックスなし。

**実戦で鍛えた階層構造** — 将軍→家老→足軽の指揮系統が設計レベルで衝突を防止：明確な責任分担、エージェントごとの専用ファイル、イベント駆動通信、ポーリングなし。

---

## なぜCLI（APIではなく）？

多くのAIコーディングツールはトークン従量課金。8体のOpus級エージェントをAPI経由で動かすと**$100+/時間**。CLI定額サブスクはこれを逆転させる：

| | API（従量課金） | CLI（定額制） |
|---|---|---|
| **8エージェント × Opus** | ~$100+/時間 | ~$200/月 |
| **コスト予測性** | 予測不能なスパイク | 月額固定 |
| **使用時の心理** | 1トークンが気になる | 使い放題 |
| **実験の余地** | 制約あり | 自由に投入 |

**「AIを使い倒す」思想** — 定額CLIサブスクなら、8体の足軽を気兼ねなく投入できる。1時間稼働でも24時間稼働でもコストは同じ。「まあまあ」と「徹底的に」の二択で悩む必要がない — エージェントを増やせばいい。

### Multi-CLI対応

将軍システムは特定ベンダーに依存しない。7つのCLIツールに対応し、それぞれの強みを活かす：

| CLI | 特徴 | デフォルトモデル |
|-----|------|-----------------|
| **Claude Code** | tmux統合の実績、Memory MCP、専用ファイルツール（Read/Write/Edit/Glob/Grep） | Claude Sonnet 4.6 |
| **OpenAI Codex** | サンドボックス実行、JSONL構造化出力、`codex exec` ヘッドレスモード | gpt-5.3-codex |
| **GitHub Copilot** | GitHub MCP組込、4種の特化エージェント（Explore/Task/Plan/Code-review）、`/delegate` | Claude Sonnet 4.6 |
| **Kimi Code** | 無料プランあり、多言語サポート | Kimi k2 |
| **OpenCode** | `AGENTS.md` 自動読込、`--agent` による個体別エージェント定義、`/new` でのコンテキストリセット、モデル変更は再起動のみ、決定的な対話型 TUI 起動、`--model provider/model` ルーティング | provider/model |
| **Cursor** | `CLAUDE.md`/`AGENTS.md`/`.cursor/rules/` 自動読込、組込 Web 検索、`.cursor/skills/` 経由の `inbox-write` スキル、`/model` でライブ切替、`--yolo` 自動実行 | 可変 |
| **Antigravity CLI** | Google Antigravity CLI（`agy`）連携、ホスト管理認証、`--dangerously-skip-permissions` 自動実行、`gemini`/`agy` エイリアス対応 | ホスト既定 / 最後に使用したモデル |

OpenCode の起動は `--agent` で生成済み `.opencode/agents/<agent_id>.md` を読み込み、リセットは `/new`、モデル変更は再起動で行う。ロール別の境界は生成されたエージェント frontmatter に埋め込まれており、将軍は監督のため `queue/reports/*` を読めるが書けず、家老は分配と報告集約のみ、足軽は自分の task/report のみ、軍師は足軽レポートを読み `gunshi_report.yaml` だけを書く。

統一ビルドシステムが共有テンプレートからCLI固有の指示書を自動生成：

```
instructions/
├── common/              # 共通ルール（全CLI共通）
├── cli_specific/        # CLI固有のツール説明
│   ├── claude_tools.md  # Claude Code ツール・機能
│   ├── copilot_tools.md # GitHub Copilot CLI ツール・機能
│   ├── opencode_tools.md # OpenCode ツール・エージェントfrontmatter・権限モデル
│   └── cursor_tools.md  # Cursor Agent ツール・スキル・セッションルール
└── roles/               # ロール定義（将軍、家老、足軽）
    ↓ ビルド
CLAUDE.md / AGENTS.md / .github/copilot-instructions.md / .opencode/agents/*.md / .cursor/rules/*.md
  ← CLI別に生成
```

ルールの変更は1箇所。全CLIに反映。同期ズレなし。

---

## ボトムアップスキル発見

他のフレームワークにはない機能です。

足軽がタスクを実行する中で、**再利用可能なパターンを自動的に発見**し、スキル候補として提案します。家老が提案を `dashboard.md` に集約し、殿（あなた）が正式なスキルに昇格させるか判断します。

```
足軽がタスクを完了
    ↓
気づき: 「このパターン、3つのプロジェクトで同じことをした」
    ↓
YAMLで報告:  skill_candidate:
                 found: true
                 name: "api-endpoint-scaffold"
                 reason: "3プロジェクトで同じRESTスキャフォールドパターンを使用"
    ↓
dashboard.md に掲載 → 殿が承認 → .claude/commands/ にスキル作成
    ↓
全エージェントが /api-endpoint-scaffold を呼び出し可能に
```

スキルは実際の作業から有機的に成長します — 既製のテンプレートライブラリからではなく。スキルセットは**あなた自身**のワークフローの反映になります。

---

## 🚀 クイックスタート

### 🪟 Windowsユーザー（最も一般的）

<table>
<tr>
<td width="60">

**Step 1**

</td>
<td>

📥 **リポジトリをダウンロード**

[ZIPダウンロード](https://github.com/yohey-w/multi-agent-shogun/archive/refs/heads/main.zip) して `C:\tools\multi-agent-shogun` に展開

*または git を使用:* `git clone https://github.com/yohey-w/multi-agent-shogun.git C:\tools\multi-agent-shogun`

</td>
</tr>
<tr>
<td>

**Step 2**

</td>
<td>

🖱️ **`install.bat` を実行**

右クリック→「管理者として実行」（WSL2が未インストールの場合）。WSL2 + Ubuntu をセットアップします。

</td>
</tr>
<tr>
<td>

**Step 3**

</td>
<td>

🐧 **Ubuntu を開いて以下を実行**（初回のみ）

```bash
cd /mnt/c/tools/multi-agent-shogun
./first_setup.sh
```

</td>
</tr>
<tr>
<td>

**Step 4**

</td>
<td>

✅ **出陣！**

```bash
./shutsujin_…31702 tokens truncated…ion or ["none"]
    risks = args.risk or ["none"]

    lines = [
        "---",
        f"project: {scalar(args.project)}",
        f"source: {scalar(args.source)}",
        f"task_id: {scalar(args.task_id)}",
        f"repository_url: {scalar(repo_url)}",
        f"working_branch: {scalar(branch)}",
        f"base_commit: {scalar(base)}",
        f"result_commit: {scalar(head)}",
        f"pr_url: {scalar(args.pr_url)}",
        f"drive_url: {scalar(args.drive_url)}",
        "---",
        "",
        "# Shogun Completion Summary",
        "",
        "## Changed Files",
        "",
    ]
    lines.extend(f"- `{path}`" for path in changed)
    if not changed:
        lines.append("- none")
    lines.extend(["", "## Verification", ""])
    lines.extend(f"- {item}" for item in verification)
    lines.extend(["", "## Remaining Risks", ""])
    lines.extend(f"- {item}" for item in risks)
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    try:
        output = build_summary(args)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output, encoding="utf-8")
        else:
            print(output, end="")
        return 0
    except (SummaryError, FileNotFoundError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
