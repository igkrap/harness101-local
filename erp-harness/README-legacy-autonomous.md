# Autonomous Local Feedback Harness

## 概要 (Overview)

このツールは、ローカルLLMを使用してコードを自動的に修正するための自律型フィードバックループを提供します。

## 使用方法 (Usage)

```bash
python harness/harness.py "<TASK>" --workspace <PATH> [--check python|frontend|backend] [--max-rounds <N>]
```

### 引数 (Arguments)

- `TASK`: 自然言語によるタスク指示。
- `--workspace`: 作業ディレクトリのパス。
- `--check`: 実行する検証モード (`python`, `frontend`, `backend`)。デフォルトは `python`。
- `--max-rounds`: 最大試行回数。デフォルトは `30`。
- `--llm-url`: ローカルLLMのAPIエンドポイント。デフォルトは `http://127.0.0.1:8099/v1`。
- `--model`: 使用するモデル名。デフォルトは `mlx-community/gemma-4-26B-A4B-it-OptiQ-4bit`。

## セキュリティ (Security)

- **Loopback Only**: APIホストは `127.0.0.1` または `localhost` に制限されています。
- **Path Traversal Protection**: `workspace` 外へのアクセスは拒否されます。
- **Write Protection**: `node_modules` への書き込みは禁止されています。

## 検証 (Verification)

- `python`: `unittest` によるテスト実行。
- `frontend`: `tsc --noEmit` および `vite build`。
- `backend`: Docker 内での `mvn -o test`。

## 自己デモ (Self-Demo)

意図的に壊れた Python アプリケーションを修正するプロセスをテストできます。
`python harness/tests/test_self_demo.py` を実行して、コンポーネントの整合性を確認してください。
