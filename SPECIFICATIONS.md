# repo-manipulator 仕様書

## 概要

repo-manipulator は、NAS上に保存されたシステム・スケジュール・連絡先などの情報をコマンドラインで管理するツールです。対話形式（REPL）で操作し、ファイルの取得・編集・登録・比較・エクスポートができます。

## コレクション

管理対象のデータは「コレクション」という単位に分類されます。組み込みコレクションは以下の3種類です。

| コレクション | 内容 |
|---|---|
| `systems` | システム情報（複数のセクションを持つ構造化ドキュメント） |
| `schedules` | スケジュール（稼働日などの日付リスト） |
| `contacts` | 連絡先（電話番号などのリスト） |

これらに加え、`additional_mandatory_properties.json` の設定によって動的コレクションを追加できます（後述）。

---

## コマンド一覧

| コマンド | 説明 |
|---|---|
| `ls <コレクション>` | コレクション内のエントリ名を一覧表示する |
| `add <コレクション> <名前>` | 新規エントリを空のテンプレートで作成する |
| `cat <コレクション> <名前>` | 最新バージョンの内容を標準出力に表示する |
| `cat systems <名前> --jtable` | 最新バージョンを表形式（読み取り専用）で表示する |
| `get <コレクション> <名前>` | 最新バージョンをローカルに取得してエディタで開く |
| `get systems <名前> --jtable` | 最新バージョンを表形式（編集可能）で開く |
| `clear <コレクション> <名前>` | ローカルの編集ファイルを空テンプレートに戻してエディタで開く |
| `len <コレクション> <名前>` | 最新バージョンの有効レコード数を表示する |
| `push <コレクション> <名前>` | ローカルの編集ファイルを検証してリポジトリに登録する |
| `export <コレクション> <ファイル名>` | 全エントリをCSVにまとめてエディタで開く |
| `export <コレクション> <ファイル名> --jtable` | 全エントリをCSVにまとめて表形式で開く |
| `diff <コレクション> <名前>` | 最新バージョンと1つ前のバージョンの差分をJSON形式で表示する |
| `diff <コレクション> <名前> --jtable` | 差分を表形式で表示する（削除行：赤、追加行：緑） |
| `exit` | ツールを終了する |

`--jtable` オプションは `cat` / `get` では `systems` コレクションのみ対応しています。

---

## バージョン管理

各エントリはバージョン管理されます。

- `add` でバージョン `0000` のファイルを新規作成します。
- `push` により、最新バージョン番号に1を加えた新しいファイルが書き込まれます。古いバージョンは削除されません。
- `ls` / `cat` / `get` / `push` などはすべて最新バージョンのファイルを対象とします。

---

## 編集フロー（systems の例）

```
get systems <名前>        # 最新版を取得しエディタで開く
  （ファイルを編集・保存）
push systems <名前>       # 検証して登録
```

`--jtable` を使う場合は表形式GUIで編集できます。

```
get systems <名前> --jtable   # 表形式GUIで開く
  （セルをダブルクリックして編集、Save ボタンで保存）
push systems <名前>           # 検証して登録
```

---

## ドキュメント形式

### systems（👉👈 形式）

`get` / `cat` / `clear` で出力されるテキスト形式です。`push` はこの形式を受け取ってリポジトリに登録します。

1つ以上のセクションで構成され、各セクションは区切り行（🏔 × 20）で始まります。

```
🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔
👉machine👈
machine_value
👉time👈
12:00
👉notes👈
ノート1行目
ノート2行目
👉id👈
id_value
👉schedule👈
schedule_value
👉contact👈
contact_value
👉prop1👈
prop1_value
```

コアフィールド（`machine`, `time`, `notes`）は常に先頭に表示されます。`id`・`schedule`・`contact` などは `additional_properties.json` または `additional_mandatory_properties.json` で定義された場合にコアフィールドの後に続きます。フィールドの表示順は `settings.ini` の `[system] property_order` で制御できます（後述）。

#### push 時の検証ルール

`push` 実行時に以下の内容が検証されます。いずれかに違反すると登録が拒否されます。

| フィールド | 検証内容 |
|---|---|
| `machine` | 空でないこと |
| `time` | 空でないこと、かつ `dd:dd`（数字2桁・コロン・数字2桁）の形式であること |
| `notes` | ラベルが存在すること（値は空でも可） |
| 追加プロパティ（任意） | ラベルが存在すること。`validation_type` に応じた入力検証が行われる（`NONE` — 制約なし; `NOT_EMPTY` — 空値を拒否; `HH:MM` — `\d{2}:\d{2}` 形式でない値を拒否; `RE:<pattern>` — 正規表現にマッチしない値を拒否） |
| 追加プロパティ（必須） | ラベルが存在し、値が空でないこと、かつ対応するコレクションに存在すること（`schedule`・`contact` も `additional_mandatory_properties.json` で定義した場合はここに含まれる） |

**例外：** すべてのセクションの全フィールドが空（`add` / `clear` 直後の状態）、またはファイル内容が空白のみの場合は検証をスキップして空テンプレートとして登録されます。

### schedules

`yyyy/mm/dd` 形式の日付をカンマ区切りで1行に記述します。

```
2024/01/01,2024/06/15,2025/03/20
```

### contacts

電話番号など `[0-9\-\+]+` にマッチする文字列をカンマ区切りで1行に記述します。

```
03-1234-5678,09012345678,+81-0100-0331
```

---

## CSVエクスポート形式

`export` コマンドで出力されるCSVの形式です。

### systems

```csv
system_name, machine_name, time, notes, id, schedule, contact, prop1, prop2
sys1, m1, 09:00, ノート内容, id1, sche1, cont1, val1, val2
sys1, m2, 12:30, , id2, sche2, cont2, ,
```

- セクションごとに1行出力されます。
- 複数行のノートはスペースで結合されます。
- すべてのセクションで `machine` が空のエントリは出力されません。
- 列の順序は `[system] property_order` の設定に従います。
- `,` / `"` / 改行を含む値はRFC 4180に従いダブルクォートで囲まれます。

### schedules

```csv
schedule_name, dates
sche1, 2024/01/01 2024/06/15 2025/03/20
```

カンマ区切りの日付がスペース区切りに変換されます。

### contacts

```csv
contact_name, numbers
cont1, 03-1234-5678 09012345678 +81-0100-0331
```

カンマ区切りの連絡先がスペース区切りに変換されます。

### 動的コレクション

```csv
name, values
teamA, value1 value2 value3
```

カンマ区切りの値がスペース区切りに変換されます。

---

## 設定ファイル（settings.ini）

| セクション | キー | デフォルト | 説明 |
|---|---|---|---|
| `[repository]` | `root` | `dummy-repo` | リポジトリ（NAS）のルートパス |
| `[downloads]` | `dir` | `downloads` | 編集ファイルの保存先ディレクトリ |
| `[cache]` | `dir` | `cache` | リポジトリのローカルキャッシュディレクトリ |
| `[editor]` | `command` | `mousepad` | `get` / `clear` / `export` で起動するエディタ |
| `[system]` | `property_order` | （空） | システムドキュメントの先頭に表示するフィールド名（カンマ区切り）。コアフィールド・追加フィールドのいずれも指定可。記載したフィールドが先頭に並び、残りはデフォルト順で続く。 |

### 設定例

```ini
[repository]
root = /mnt/nas/repo

[editor]
command = gedit

[system]
property_order = team,notes,id
```

---

## 追加プロパティの設定

### 任意プロパティ（additional_properties.json）

リポジトリルートの `additional_properties.json` に、システムの各セクションに追加するフィールドをオブジェクトの配列で記述します。

```json
[
  {"property_name": "id",    "validation_type": "RE:[^#]+"},
  {"property_name": "prop1", "validation_type": "NONE"},
  {"property_name": "prop2", "validation_type": "NOT_EMPTY"},
  {"property_name": "prop3", "validation_type": "HH:MM"}
]
```

| フィールド | 説明 |
|---|---|
| `property_name` | フィールド名 |
| `validation_type` | `push` 時の入力検証: `"NONE"` — 検証なし（値が空でも可）; `"NOT_EMPTY"` — 空値を拒否; `"HH:MM"` — `\d{2}:\d{2}` 形式でない値を拒否; `"RE:<pattern>"` — 正規表現 `<pattern>` に完全マッチしない値を拒否（`re.fullmatch` 使用）。省略時は `"NONE"` として扱われる |

オブジェクト以外のエントリは無視されます。

### 必須プロパティ・動的コレクション（additional_mandatory_properties.json）

リポジトリルートの `additional_mandatory_properties.json` に、動的コレクションの定義を記述します。

```json
[
  {"collection_name": "teams",     "property_name": "team",     "type": "NOTE",         "whitelist": []},
  {"collection_name": "schedules", "property_name": "schedule", "type": "DATE",         "whitelist": ["everyday", "weekends"]},
  {"collection_name": "contacts",  "property_name": "contact",  "type": "PHONE_NUMBER", "whitelist": ["ceo", "無用"]}
]
```

| フィールド | 説明 |
|---|---|
| `collection_name` | コレクションのディレクトリ名（コマンドでもこの名前を使用） |
| `property_name` | システムドキュメントのフィールド名。`push` 時に値が検証される |
| `type` | `push` 時のコンテンツ検証: `"DATE"` — `yyyy/mm/dd` 形式の日付をカンマ区切り; `"PHONE_NUMBER"` — `[0-9\-\+]+` 形式の文字列をカンマ区切り; `"EMAIL"` — `user@domain.tld` 形式のメールアドレスをカンマ区切り; `"NOTE"` または未指定 — 検証なし |
| `whitelist` | コレクションへの存在チェックをスキップして受け入れる値のリスト（省略または空配列 `[]` でホワイトリストなし） |

- 定義したコレクションはツール起動時に自動で利用可能になります。
- `property_name` が `machine`・`time`・`notes` 以外の場合、全システムドキュメントの必須項目として追加されます。`schedule` や `contact` もここで定義することで必須フィールドになります。
- `push` 時、各 `property_name` の値が空でないこと、かつ対応する `collection_name` コレクションに登録されていること（または `whitelist` に含まれること）が検証されます。
- `schedule` や `contact` を記載することで、これらのコレクション参照チェックを含む全検証を動的コレクション設定で管理できます。
- 動的コレクションは組み込みの `schedules` / `contacts` と同様に操作できます。

---

## 表形式GUI（JTable）について

`--jtable` オプションを指定すると、テキストエディタの代わりに表形式のGUIウィンドウが開きます。

### cat systems \<名前\> --jtable（読み取り専用）

- 内容を表形式で閲覧できます。
- 列ヘッダーのクリックでソートできます。
- 編集・保存はできません。

### get systems \<名前\> --jtable（編集可能）

- セルをダブルクリックするとその場で編集できます。
- `notes` フィールドをダブルクリックすると、複数行入力用のダイアログが開きます。
- **Save** ボタンで編集内容をファイルに保存します（リポジトリへの登録は別途 `push` が必要です）。
- **Add Row** で末尾または選択行の後に空行を追加します。
- **Duplicate Row** で選択行を複製します。
- **Delete Row** で選択行を削除します。

### diff \<コレクション\> \<名前\> --jtable（差分表示）

- 削除されたレコードを赤（`−`）、追加されたレコードを緑（`+`）で表示します。
- 列ヘッダーのクリックでソートできます。
