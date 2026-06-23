# naxel

ファイルベースのリポジトリ（ローカルまたはNAS）に保存された構造化データを管理するコマンドラインツールです。データはバージョン管理されたディレクトリ構造のファイルに保存され、naxelはブラウズ・編集・検証・エクスポートを行うREPLを提供します。また、視覚的な編集のためのオプションのJTable GUIも備えています。

Rust/Tauri版（`src-rs/`）は同じREPLに加えて、組み込みウェブビューによるネイティブのテーブルウィンドウを提供します。

---

## スクリーンショット

### REPLセッション

![REPL session](readme-imgs/repl-session.png)

### JTable — メインコレクション（編集可能）

![JTable main collection](readme-imgs/jtable-main.png)

### JTable — エクスポート / cat（読み取り専用・検索付き）

![JTable export](readme-imgs/jtable-export.png)

### JTable — diff表示

![JTable diff](readme-imgs/jtable-diff.png)

---

## クイックスタート

**必要環境:** Python 3.10以上

```sh
git clone <このリポジトリ>
cd naxel
```

### サンプルリポジトリを試す

`samples/` ディレクトリにはデータが入力済みのサーバーインベントリリポジトリが含まれています。`settings.ini` はすでにそこを指しているので、すぐに起動できます：

```sh
python3 src/app.py
```

REPL内での操作例：

```
> ls systems
db-01
web-01
web-02

> cat systems web-01
🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔
👉team👈
backend
👉notes👈
Primary web server.
Handles all public traffic.
👉id👈
WEB-001
👉status👈
active
👉time👈
09:00
👉schedule👈
business-hours
👉contact👈
ops-team
...

> export systems inventory.csv --jtable
```

### 新しいリポジトリを作成する

対話形式ウィザードで新規リポジトリをセットアップします：

```sh
python3 src/app.py init /path/to/new-repo
```

ウィザードの質問内容：
- メインコレクション名とパーティショニングプロパティ（エントリ名の列）
- 任意の数の列 — 各列にバリデーションタイプ、複数行フラグ、参照コレクションへのワイヤリングを設定可能
- 列の表示順序
- 起動時に表示するイントロダクションメッセージ

`repository.ini`、`additional_properties.json`、`reference_collections.json` を生成し、コレクションディレクトリを作成します。その後、`settings.ini` で新しいディレクトリを指定してアプリを起動します。

### 既存のリポジトリを使う

1. プロジェクトルートの `settings.ini` を編集し、`repository.root` に目的のディレクトリを設定します。
2. `python3 src/app.py` を実行します。

---

## コマンド一覧

### CLIのみ（REPL起動前に実行）

| コマンド | 説明 |
|---|---|
| `init <保存先ディレクトリ>` | 対話形式ウィザードで新規リポジトリを初期化します。ディレクトリが存在しない場合は作成します |
| `update <保存先ディレクトリ>` | 対話形式ウィザードで既存リポジトリの設定を変更します |

### REPLコマンド

| コマンド | 説明 |
|---|---|
| `ls <コレクション>` | コレクション内のエントリ名を一覧表示する |
| `add <コレクション> <名前>` | 空のテンプレートで新規エントリを作成する |
| `del <コレクション> <名前>` | エントリの全バージョンをソフト削除する（ファイルをドットプレフィックスに改名；読み取りコマンドからは無視される） |
| `cat <コレクション> <名前>` | 最新バージョンを標準出力に表示する |
| `cat <コレクション> <名前> --version=N` | 指定バージョンを標準出力に表示する |
| `cat <コレクション> <名前> --jtable` | 最新バージョンを読み取り専用JTableウィンドウで開く |
| `cat <コレクション> <名前> --version=N --jtable` | 指定バージョンを読み取り専用JTableウィンドウで開く |
| `cat <コレクション> <名前> --json` | 最新バージョンをJSON形式で表示する |
| `cat <コレクション> <名前> --version=N --json` | 指定バージョンをJSON形式で表示する |
| `get <コレクション> <名前>` | 最新バージョンをダウンロードしてエディタで開く |
| `get <コレクション> <名前> --jtable` | ダウンロードして編集可能なJTableウィンドウで開く |
| `get <コレクション> <名前> -` | ダウンロード；新しい内容をstdinから読み込む（パイプライン用） |
| `clear <コレクション> <名前>` | 空のテンプレートを書き込んでエディタで開く |
| `clear <コレクション> <名前> --jtable` | 空のテンプレートを書き込んでJTableで開く |
| `len <コレクション> <名前>` | 有効レコード数を表示する |
| `push <コレクション> <名前>` | ダウンロードファイルを検証して次のバージョンとして書き込む |
| `push <コレクション> <名前> --json` | ダウンロードファイルをJSONとして解釈して変換してからpushする |
| `diff <コレクション> <名前>` | 最新の2バージョンを比較；`deleted`/`added` のJSONを表示する |
| `diff <コレクション> <名前> --jtable` | 同じ比較を色付きJTableウィンドウで表示する |
| `appenditems <コレクション> <名前>` | 空のレコードテンプレートをエディタで開き、保存・終了でエントリに追記してpushする |
| `appenditems <コレクション> <名前> --json` | 同様だが、新規レコードをJSON配列で入力する |
| `appenditems <コレクション> <名前> -` | stdinから新規レコードを読み込んでエディタを開かずに追記する |
| `searchitems <コレクション> <名前>` | フィルタクエリをエディタで入力；マッチするレコードをJSON配列として表示する |
| `searchitems <コレクション> <名前> --json` | 同様だが、フィルタクエリをJSONオブジェクトで入力する |
| `searchitems <コレクション> <名前> -` | stdinからフィルタクエリを読み込む |
| `removeitems <コレクション> <名前>` | フィルタクエリをエディタで入力；マッチするレコードを削除してpushする |
| `removeitems <コレクション> <名前> --json` | 同様だが、フィルタクエリをJSONオブジェクトで入力する |
| `removeitems <コレクション> <名前> -` | stdinからフィルタクエリを読み込む |
| `export <コレクション> <ファイル名>.csv` | 全エントリからCSVを生成してエディタで開く |
| `export <コレクション> <ファイル名>.csv --jtable` | 同様だが、JTableで開く |
| `export <コレクション> <ファイル名>.json` | 全エントリからJSONファイルを生成する |
| `fullcopy <保存先ディレクトリ>` | リポジトリ全体（全バージョン）を `<保存先>/<リポジトリ名>/` にコピーする |
| `fullcopy <保存先ディレクトリ> --json` | リポジトリのスナップショット（最新バージョンのみ）を単一JSONファイルとして保存する |
| `mkrepo <JSONファイル> <保存先ディレクトリ>` | `fullcopy --json` のスナップショットからリポジトリを復元する |
| `partialcopy <コレクション> <名前> <保存先ディレクトリ>` | リポジトリをコピーするが、指定エントリ以外を消去する |
| `partialcopy <コレクション> <名前> <保存先ディレクトリ> --json` | 同様をJSONスナップショットとして保存する |
| `cd <パス>` | 別のリポジトリに切り替える |
| `exit` | 終了する |

### バッチモード

`-c` で非対話的にコマンドを実行します：

```sh
python3 src/app.py -c 'ls systems && cat systems web-01'
```

パイプラインと組み合わせる：

```sh
cat my-edited-file.txt | python3 src/app.py -c 'get systems web-01 - && push systems web-01'
```

---

## 設定

### `settings.ini`（プロジェクトルート）

```ini
[repository]
root = /path/to/your/repo   # 相対パスも可（例: dummy-repo）

[editor]
command = mousepad          # get / clear / export で起動するエディタ
```

### `repository.ini`（リポジトリルート）

```ini
[introduction]
message = 起動時に表示されるメッセージ（任意）

[main_collection]
collection_name = systems       # メインコレクションのディレクトリ名
partitioning_property = system  # CSV先頭列のヘッダー
property_order = team,notes,id  # 先頭に表示するフィールド；他はその後に続く
```

### `additional_properties.json`

メインコレクションの各レコードに追加する任意フィールドの定義：

```json
[
  {"property_name": "notes",  "validation_type": "NONE",      "multiline": true},
  {"property_name": "id",     "validation_type": "RE:[^#]+"},
  {"property_name": "status", "validation_type": "NOT_EMPTY"},
  {"property_name": "time",   "validation_type": "HH:MM"}
]
```

| `validation_type` | push時の検証ルール |
|---|---|
| `NONE` | 制約なし（空値も可） |
| `NOT_EMPTY` | 空値を拒否 |
| `HH:MM` | `\d{2}:\d{2}` に一致すること |
| `MM/DD` | `\d{2}/\d{2}` に一致すること |
| `INT` | `[0-9]+` に一致すること |
| `YYYY` | `\d{4}` に一致すること |
| `RE:<pattern>` | 指定した正規表現に完全一致すること |

`"multiline": true` を設定すると、複数行にまたがるフィールドになります。JTableではダブルクリック時にモーダルエディタが開きます。

### `reference_collections.json`

動的参照コレクションの定義 — 各エントリが有効な値のコレクションを定義します：

```json
[
  {"collection_name": "teams",     "property_name": "team",     "type": "STRING",         "whitelist": []},
  {"collection_name": "schedules", "property_name": "schedule", "type": "DATE",         "whitelist": ["everyday", "weekends"]},
  {"collection_name": "contacts",  "property_name": "contact",  "type": "PHONE_NUMBER", "whitelist": ["none"]}
]
```

`push` 時、各 `property_name` フィールドは空でなく、対応する `collection_name` コレクションにエントリとして存在すること（または `whitelist` に含まれること）が検証されます。

| `type` | 参照コレクションエントリの形式 |
|---|---|
| `STRING` | 検証なし |
| `DATE` | カンマ区切りの `yyyy/mm/dd` |
| `PHONE_NUMBER` | カンマ区切りの `[0-9\-\+]+` |
| `EMAIL` | カンマ区切りの `user@domain.tld` |
| `YEAR` | カンマ区切りの `\d{4}` |

---

## ドキュメント形式

### メインコレクション — 編集形式（👉👈）

`get` と `cat` はこのセパレータ形式でレコードを表示します。`push` はこの形式を受け取ってJSONに変換してから書き込みます。

```
🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔
👉team👈
backend
👉notes👈
Primary web server.
Handles all public traffic.
👉id👈
WEB-001
👉status👈
active
👉time👈
09:00
👉schedule👈
business-hours
👉contact👈
ops-team
```

複数のレコードは `🏔` 行で区切られます。`add`/`clear` が書き込む空テンプレートも同じ構造で値が空になります。

### 参照コレクション

プレーンテキスト：1行にカンマ区切りの値。

```
2025/01/06,2025/01/07,2025/01/08,2025/01/09,2025/01/10
```

### CSVエクスポート

```csv
system, team, notes, id, status, time, schedule, contact
web-01, backend, Primary web server. Handles all public traffic., WEB-001, active, 09:00, business-hours, ops-team
web-01, backend, Secondary instance., WEB-001, active, 09:30, on-call, dev-team
```

参照コレクションのエクスポート：

```csv
name, values
business-hours, 2025/01/06 2025/01/07 2025/01/08 2025/01/09 2025/01/10
```

---

## appenditems / searchitems / removeitems

この3つのコマンドは、`get` → 編集 → `push` のフローを経ずにエントリ内の個々のレコードを操作します。

**`appenditems`** は空のレコードテンプレートをエディタで開きます。保存・終了すると、新しいレコードが既存エントリに追記されて自動的にpushされます。エントリが初期の全空状態の場合は、空テンプレートが置き換えられます。

**`searchitems`** はフィルタクエリをエディタで入力します。保存・終了すると、マッチしたレコードがJSON配列として標準出力に表示されます。スクリプティングに便利です。

![searchitems クエリエディタ](readme-imgs/searchitems-gui.png)

**`removeitems`** は同様に動作しますが、マッチしたレコードを削除してpushします。

### フィルタクエリ構文（デフォルト — バッククォート構文）

```
`column`='exact value'
`column` like 'prefix%'
`column` like '%suffix'
`column1`='val' and `column2` like 'pat%'
`column1`='val' or `column2`='other'
```

- `%` は任意の文字列、`_` は任意の1文字にマッチします（SQL LIKE）。
- `and` は `or` より優先度が高いです。
- 空クエリ（条件なし）はすべてにマッチします。

### フィルタクエリ構文（`--json` モード）

```json
{"column1": "exact value", "column2": "prefix%"}
```

- すべてのキーと値はAND結合されます。
- `%` または `_` を含む値は自動的にLIKEパターンとして扱われます。
- 空オブジェクト `{}` はすべてにマッチします。

### バッチモードの使用例

```sh
# ファイルから新規レコードを追記
python3 src/app.py -c 'appenditems systems web-01 -' < new-section.txt

# 検索結果をパイプで渡す
python3 src/app.py -c 'searchitems systems web-01 - --json' <<< '{"status": "active"}'

# パターンにマッチするレコードを削除
echo '`status`='"'"'deprecated'"'"'' | python3 src/app.py -c 'removeitems systems web-01 -'
```

---

## JTable検索クエリ構文

読み取り専用のJTable（`cat --jtable` および `export --jtable`）はクエリバーをサポートします：

| クエリ | 動作 |
|---|---|
| `foo bar` | すべての列に対する部分一致検索 |
| `where col = 'val'` | `col` 列の完全一致 |
| `where col like 'pat%'` | SQL LIKEパターン（`%` = 任意の文字、`_` = 任意の1文字） |
| `where 'val' in col` | `col` 列のカンマ区切りトークンに `val` が含まれるか |
| `where col.contents like 'pat'` | 参照エントリの内容文字列に対するLIKE検索 |
| `cond1 and cond2` | AND（ORより優先度が高い） |
| `cond1 or cond2` | OR |
| `select count where cond` | 表示を変えずにマッチ件数をカウントする |
| `select prop.entry.contents` | 特定の参照エントリの値をテーブルに表示する |

---

## Rust/Tauri版

```sh
cargo build --release
./target/release/naxel              # REPL
./target/release/naxel -c 'ls systems'
```

Rustバイナリは同じコマンドをサポートし、同じ設定ファイルを読み込みます。`--jtable` コマンドはネイティブのウェブビューテーブルウィンドウを開きます（fire-and-forget；REPLはすぐに続行します）。

`init` と `update` も利用できます：

```sh
./target/release/naxel init /path/to/new-repo
./target/release/naxel update /path/to/existing-repo
```

---

## リポジトリ構成

```
samples/
  repo/                           サンプルのサーバーインベントリリポジトリ
src/
  app.py                          Python REPL
  gui.py                          JTable GUI（tkinter）
src-rs/
  main.rs                         Rust REPLエントリポイント
  commands.rs                     コマンド実装
  repo.rs                         リポジトリ状態とキャッシュ同期
  ...
settings.ini                      デフォルトでsamples/repoを指定
```

---

## ドキュメント

このリポジトリには以下のドキュメントが含まれています：

| ファイル | 説明 |
|---|---|
| [README.md](README.md) | 英語版README（このファイルの英語版） |
| [README_ja.md](README_ja.md) | 日本語版README（このファイル） |
| [SPECIFICATIONS.md](SPECIFICATIONS.md) | 英語版仕様書（詳細な技術仕様） |
| [SPECIFICATIONS_ja.md](SPECIFICATIONS_ja.md) | 日本語版仕様書（詳細な技術仕様） |
