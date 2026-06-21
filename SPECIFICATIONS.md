# repo-manipulator 仕様書

## 概要

repo-manipulator は、NAS上に保存された構造化ドキュメントや参照データをコマンドラインで管理するツールです。対話形式（REPL）で操作するほか、`-c` オプションによるバッチモードでスクリプトやパイプラインからも利用できます。ファイルの取得・編集・登録・比較・エクスポートができます。コレクションの種類や名称はすべて設定ファイルで定義します。

### 起動方法

```
python3 src/app.py                    # 対話モード（REPL）
python3 src/app.py -c 'cmd1 && cmd2' # バッチモード（コマンド実行後に終了）
```

バッチモードでは `&&` で区切ったコマンドを順番に実行して終了します。パイプラインと組み合わせて使えます。

```
cat foo_main.txt | python3 src/app.py -c 'add systems foo && get systems foo - && push systems foo && diff systems foo'
```

### プロンプト

対話モードのプロンプトには現在のリポジトリのディレクトリ名が表示されます。

```
dummy-repo > 
```

`cd` でリポジトリを切り替えると、プロンプトも自動的に更新されます。

### ダウンロード・キャッシュのディレクトリ構造

複数リポジトリを切り替えて使用できるよう、`downloads` と `cache` のファイルはリポジトリごとにサブディレクトリへ分けて保存されます。サブディレクトリ名（リポジトリID）はリポジトリの絶対パスのMD5ハッシュです。

```
downloads/
  {リポジトリID}/
    {コレクション}/    # get / clear / cat --jtable で保存されるファイル
    {ファイル名}.csv   # export の出力ファイル（コレクションサブディレクトリには入らない）
cache/
  {リポジトリID}/
    {コレクション}/    # NASリポジトリのローカルミラー
```

## コレクション

管理対象のデータは「コレクション」という単位に分類されます。コレクションはすべて設定ファイルで定義され、組み込みのコレクションはありません。

| 種別 | 説明 | 設定場所 |
|---|---|---|
| メインコレクション | 複数のセクションを持つ構造化ドキュメント（gzip圧縮） | `repository.ini [main_collection]` |
| 参照コレクション | カンマ区切りの値リスト（プレーンテキスト） | `additional_mandatory_properties.json` |

`schedules` や `contacts` なども `additional_mandatory_properties.json` に記述することで利用できます（組み込みではなく、設定次第です）。

---

## コマンド一覧

| コマンド | 説明 |
|---|---|
| `cd <パス>` | 操作対象のリポジトリを切り替える。設定・コレクション定義を読み直し、新しいリポジトリのキャッシュを同期する |
| `ls <コレクション>` | コレクション内のエントリ名を一覧表示する |
| `add <コレクション> <名前>` | 新規エントリを空のテンプレートで作成する |
| `cat <コレクション> <名前>` | 最新バージョンの内容を標準出力に表示する |
| `cat <コレクション> <名前> --jtable` | 最新バージョンを表形式（読み取り専用）で表示する |
| `get <コレクション> <名前>` | 最新バージョンをローカルに取得してエディタで開く |
| `get <コレクション> <名前> --jtable` | 最新バージョンを表形式（編集可能）で開く |
| `get <コレクション> <名前> -` | 標準入力の内容を `downloads/{リポジトリID}/{コレクション}/` に保存する（エディタは起動しない）。`-c` バッチモードのパイプラインで使用する |
| `clear <コレクション> <名前>` | ローカルの編集ファイルを空テンプレートに戻してエディタで開く |
| `len <コレクション> <名前>` | 最新バージョンの有効レコード数を表示する |
| `push <コレクション> <名前>` | ローカルの編集ファイルを検証してリポジトリに登録する |
| `export <コレクション> <ファイル名>.csv` | 全エントリをCSVにまとめてエディタで開く |
| `export <コレクション> <ファイル名>.csv --jtable` | 全エントリをCSVにまとめて表形式で開く |
| `export <コレクション> <ファイル名>.json` | 全エントリをJSONにまとめてエディタで開く |
| `export <メインコレクション> <ファイル名>.json --onefile` | メインコレクションと全参照コレクションを1つのJSONオブジェクトにまとめてエディタで開く |
| `diff <コレクション> <名前>` | 最新バージョンと1つ前のバージョンの差分をJSON形式で表示する |
| `diff <コレクション> <名前> --jtable` | 差分を表形式で表示する（削除行：赤、追加行：緑） |
| `exit` | ツールを終了する |

`--jtable` は `.json` エクスポートには使用できません。`--onefile` は `.json` エクスポートのみ対応しています。

---

## バージョン管理

各エントリはバージョン管理されます。

- `add` でバージョン `0000` のファイルを新規作成します。
- `push` により、最新バージョン番号に1を加えた新しいファイルが書き込まれます。古いバージョンは削除されません。
- `ls` / `cat` / `get` / `push` などはすべて最新バージョンのファイルを対象とします。

---

## 編集フロー（メインコレクションの例）

```
get <メインコレクション> <名前>        # 最新版を取得しエディタで開く
  （ファイルを編集・保存）
push <メインコレクション> <名前>       # 検証して登録
```

`--jtable` を使う場合は表形式GUIで編集できます。

```
get <メインコレクション> <名前> --jtable   # 表形式GUIで開く
  （セルをダブルクリックして編集、Save ボタンで保存）
push <メインコレクション> <名前>           # 検証して登録
```

パイプラインで新規エントリを一括登録する場合は `-c` バッチモードと `get … -` を使います。

```
cat file.txt | python3 src/app.py -c 'add systems foo && get systems foo - && push systems foo'
```

`get … -` は標準入力の内容をそのままダウンロードファイルに書き込みます（エディタは起動しません）。

---

## ドキュメント形式

### メインコレクション（👉👈 形式）

`get` / `cat` / `clear` で出力されるテキスト形式です。`push` はこの形式を受け取ってリポジトリに登録します。

1つ以上のセクションで構成され、各セクションは区切り行（🏔 × 20）で始まります。

```
🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔🏔
👉notes👈
ノート1行目
ノート2行目
👉machine👈
machine_value
👉time👈
12:00
👉id👈
id_value
👉schedule👈
schedule_value
👉contact👈
contact_value
👉prop1👈
prop1_value
```

ハードコードされたコアフィールドはありません。`notes`・`machine`・`time`・`id`・`schedule`・`contact` をはじめとする全フィールドは、`additional_properties.json` または `additional_mandatory_properties.json` で定義された追加プロパティです。フィールドの表示順は `repository.ini` の `[main_collection] property_order` で制御できます（後述）。

#### push 時の検証ルール

`push` 実行時に以下の内容が検証されます。いずれかに違反すると登録が拒否されます。

| フィールド | 検証内容 |
|---|---|
| 追加プロパティ（任意） | ラベルが存在すること。`validation_type` に応じた入力検証が行われる（`NONE` — 制約なし; `NOT_EMPTY` — 空値を拒否; `HH:MM` — `\d{2}:\d{2}` 形式でない値を拒否; `MM/DD` — `\d{2}/\d{2}` 形式でない値を拒否; `INT` — `[0-9]+` にマッチしない値を拒否; `YYYY` — `\d{4}` 形式でない値を拒否; `RE:<pattern>` — 正規表現にマッチしない値を拒否）。`multiline: true` のフィールドは次のラベルまでの複数行を値として読み込む |
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

### メインコレクション

```csv
system_name, notes, machine, time, id, schedule, contact, prop1, prop2
sys1, ノート内容, m1, 09:00, id1, sche1, cont1, val1, val2
sys1, , m2, 12:30, id2, sche2, cont2, ,
```

- セクションごとに1行出力されます。
- 先頭列のヘッダーは `repository.ini` の `[main_collection] partitioning_property` の値に `_name` を付けたものです（例: `partitioning_property = system` → `system_name`）。
- 残りの列名はフィールド名そのままです（リネームなし）。
- `multiline: true` のフィールド（`notes` など）は複数行がスペースで結合されます。
- すべてのセクションの全フィールドが空のエントリは出力されません。
- 列の順序は `repository.ini` の `[main_collection] property_order` の設定に従います。
- `,` / `"` / 改行を含む値はRFC 4180に従いダブルクォートで囲まれます。

### 参照コレクション

```csv
name, values
sche1, 2024/01/01 2024/06/15 2025/03/20
```

メインコレクション以外はすべて `name, values` の共通ヘッダーを使用します。カンマ区切りの値はスペース区切りに変換されます。空のエントリは出力されません。

---

## JSONエクスポート形式

`export` コマンドでファイル名が `.json` で終わる場合に出力されるJSON形式です。エディタで開きます（`--jtable` は使用できません）。

### メインコレクション

```json
[
  {"system_name": "sys1", "notes": "ノート内容", "machine": "m1", "time": "09:00", "id": "id1", "schedule": "sche1", "contact": "cont1"},
  {"system_name": "sys1", "notes": "", "machine": "m2", "time": "12:30", "id": "id2", "schedule": "sche2", "contact": "cont2"}
]
```

- セクションごとに1オブジェクト出力されます。
- 先頭キーは `{partitioning_property}_name`（例: `system_name`）です。
- 残りのキーは `field_order` に従ったフィールド名です。
- `multiline: true` のフィールドは改行 `\n` をそのまま保持します（CSVではスペースに変換されます）。
- すべてのセクションの全フィールドが空のエントリは出力されません。

### 参照コレクション

```json
[
  {"name": "sche1", "values": ["2024/01/01", "2024/06/15", "2025/03/20"]},
  {"name": "sche2", "values": ["2024/03/01"]}
]
```

- カンマ区切りの値をJSON配列に分割して出力します（CSVではスペース区切りに変換されます）。
- 空のエントリは出力されません。

### `--onefile`（メインコレクションのみ）

メインコレクションの `.json` エクスポートに `--onefile` を指定すると、メインコレクションと全参照コレクションを1つのJSONオブジェクトにまとめます。

```json
{
  "systems": [ ... ],
  "teams":   [{"name": "team1", "values": ["val1"]}, ...],
  "schedules": [{"name": "sche1", "values": ["2024/01/01"]}, ...]
}
```

- メインコレクションのキーはコレクション名（例: `systems`）です。
- 参照コレクションのキーは各 `collection_name`（例: `teams`、`schedules`）です。
- `additional_mandatory_properties.json` で定義された全参照コレクションが含まれます。
- メインコレクション以外に `--onefile` を指定しても動作は変わりません。

---

## 設定ファイル

### settings.ini

| セクション | キー | デフォルト | 説明 |
|---|---|---|---|
| `[repository]` | `root` | `dummy-repo` | リポジトリ（NAS）のルートパス |
| `[downloads]` | `dir` | `downloads` | 編集ファイルの保存先ディレクトリ |
| `[cache]` | `dir` | `cache` | リポジトリのローカルキャッシュディレクトリ |
| `[editor]` | `command` | `mousepad` | `get` / `clear` / `export` で起動するエディタ |

### repository.ini

リポジトリルート（`{repo_root}/repository.ini`）に配置します。

| セクション | キー | デフォルト | 説明 |
|---|---|---|---|
| `[main_collection]` | `collection_name` | `systems` | メインコレクション（gzip圧縮・複数セクション形式）のコレクション名 |
| `[main_collection]` | `partitioning_property` | `system` | CSVの先頭列ヘッダーのプレフィックス（`{値}_name` が列名になる） |
| `[main_collection]` | `property_order` | （空） | システムドキュメントの先頭に表示するフィールド名（カンマ区切り）。記載したフィールドが先頭に並び、残りはデフォルト順で続く |
| `[additional_properties]` | `json` | `additional_properties.json` | 任意プロパティ定義ファイルのパス（リポジトリルートからの相対パス） |
| `[reference_collections]` | `json` | `additional_mandatory_properties.json` | 動的コレクション定義ファイルのパス（リポジトリルートからの相対パス） |
| `[introduction]` | `message` | （空） | 起動時および `cd` でリポジトリを切り替えた直後に表示するメッセージ |

### 設定例

```ini
# settings.ini
[repository]
root = /mnt/nas/repo

[editor]
command = gedit
```

```ini
# repository.ini（リポジトリルートに配置）
[main_collection]
collection_name = systems
partitioning_property = system
property_order = team,notes,id

[additional_properties]
json = additional_properties.json

[reference_collections]
json = additional_mandatory_properties.json
```

---

## 追加プロパティの設定

### 任意プロパティ（additional_properties.json）

`repository.ini` の `[additional_properties] json` で指定したファイル（デフォルト: `additional_properties.json`）に、システムの各セクションに追加するフィールドをオブジェクトの配列で記述します。

```json
[
  {"property_name": "notes", "validation_type": "NONE", "multiline": true},
  {"property_name": "id",    "validation_type": "RE:[^#]+"},
  {"property_name": "prop1", "validation_type": "NONE"},
  {"property_name": "prop2", "validation_type": "NOT_EMPTY"},
  {"property_name": "prop3", "validation_type": "HH:MM"}
]
```

| フィールド | 説明 |
|---|---|
| `property_name` | フィールド名 |
| `validation_type` | `push` 時の入力検証: `"NONE"` — 検証なし（値が空でも可）; `"NOT_EMPTY"` — 空値を拒否; `"HH:MM"` — `\d{2}:\d{2}` 形式でない値を拒否; `"MM/DD"` — `\d{2}/\d{2}` 形式でない値を拒否; `"INT"` — `[0-9]+` にマッチしない値を拒否; `"YYYY"` — `\d{4}` 形式でない値を拒否; `"RE:<pattern>"` — 正規表現 `<pattern>` に完全マッチしない値を拒否（`re.fullmatch` 使用）。省略時は `"NONE"` として扱われる |
| `multiline` | `true` — 次のラベルまでの複数行を値として読み込む。JSON には `"\n"` 区切りで保存され、CSV エクスポート時はスペースで結合される。JTable の編集モードでダブルクリックするとモーダルテキストエディタが開く。`false` または省略時は1行フィールド |

オブジェクト以外のエントリは無視されます。

### 必須プロパティ・動的コレクション（additional_mandatory_properties.json）

`repository.ini` の `[reference_collections] json` で指定したファイル（デフォルト: `additional_mandatory_properties.json`）に、動的コレクションの定義を記述します。

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
| `type` | `push` 時のコンテンツ検証: `"DATE"` — `yyyy/mm/dd` 形式の日付をカンマ区切り; `"PHONE_NUMBER"` — `[0-9\-\+]+` 形式の文字列をカンマ区切り; `"EMAIL"` — `user@domain.tld` 形式のメールアドレスをカンマ区切り; `"YEAR"` — `\d{4}` 形式の年をカンマ区切り; `"NOTE"` または未指定 — 検証なし |
| `whitelist` | コレクションへの存在チェックをスキップして受け入れる値のリスト（省略または空配列 `[]` でホワイトリストなし） |

- 定義したコレクションはツール起動時に自動で利用可能になります。
- 全 `property_name` がメインコレクションドキュメントの必須項目として追加されます。
- `push` 時、各 `property_name` の値が空でないこと、かつ対応する `collection_name` コレクションに登録されていること（または `whitelist` に含まれること）が検証されます。
- `schedule` や `contact` をここで定義することで、コレクション参照チェックを含む全検証をこの設定ファイルで一元管理できます。

---

## 表形式GUI（JTable）について

`--jtable` オプションを指定すると、テキストエディタの代わりに表形式のGUIウィンドウが開きます。

### cat \<コレクション\> \<名前\> --jtable（読み取り専用）

- 内容を表形式で閲覧できます。
- 列ヘッダーのクリックでソートできます。
- 編集・保存はできません。
- ウィンドウ上部に**検索バー**が表示されます（下記「検索バー」節を参照）。

### export \<コレクション\> \<ファイル名\> --jtable（CSVエクスポートの表示）

- エクスポートされたCSVを表形式で閲覧できます。
- 編集・保存はできません。
- ウィンドウ上部に**検索バー**が表示されます（下記「検索バー」節を参照）。

### get \<メインコレクション\> \<名前\> --jtable（編集可能・メインコレクション）

- セルをダブルクリックするとその場で編集できます。
- `multiline: true` のフィールド（`notes` など）をダブルクリックすると、複数行入力用のダイアログが開きます。
- **Save** ボタンで編集内容をファイルに保存します（リポジトリへの登録は別途 `push` が必要です）。
- **Add Row** で末尾または選択行の後に空行を追加します。
- **Duplicate Row** で選択行を複製します。
- **Delete Row** で選択行を削除します。
- ウィンドウ上部に**検索バー**が表示されます（下記「編集モードの検索バー」節を参照）。

### get \<参照コレクション\> \<名前\> --jtable（編集可能・参照コレクション）

- カンマ区切りのファイルを1行1値の単一列テーブルとして表示します（列ヘッダー: `values`）。
- セルをダブルクリックするとその場で編集できます。
- **Save** ボタンで編集内容をカンマ区切り形式で保存します（空行は除外されます）。
- **Add Row** で末尾または選択行の後に空行を追加します。
- **Delete Row** で選択行を削除します（Duplicate Row はありません）。
- ウィンドウ上部に**検索バー**が表示されます（下記「編集モードの検索バー」節を参照）。

### diff \<コレクション\> \<名前\> --jtable（差分表示）

- 削除されたレコードを赤（`−`）、追加されたレコードを緑（`+`）で表示します。
- 列ヘッダーのクリックでソートできます。

### 編集モードの検索バー

`get --jtable`（編集可能）では、ウィンドウ上部に**シンプルな検索バー**が表示されます。入力した文字列をすべての列のセル値に対して大文字小文字を区別せず部分一致で検索し、一致しない行を非表示にします。右端にヒット件数（`N / 合計 rows` または `合計 rows`）が表示されます。

- 絞り込みは**表示のみ**に影響します。非表示になった行も Save 時には保存されます（データは失われません）。
- **Add Row** / **Duplicate Row** を実行すると検索がリセットされ、全行が再表示された状態で新しい行が挿入されます。
- **Delete Row** は表示中の選択行を完全に削除します（非表示行は削除されません）。
- 差分表示（`diff --jtable`）には検索バーはありません。

### 読み取り専用の検索バー

`cat --jtable`（読み取り専用）と `export --jtable`（CSV表示）では、ウィンドウ上部に**高機能な検索バー**が表示されます。入力内容に応じてリアルタイムにテーブルが絞り込まれ、右端にヒット件数が表示されます。

#### クエリ構文

キーワード・演算子はすべて大文字小文字を区別しません。

| クエリ例 | 動作 |
|---|---|
| `foo` | すべての列に対して部分一致検索。参照コレクション列は参照先の内容も対象とする（ディープサーチ） |
| `where col = 'val'` | `col` 列の値が `val` に完全一致する行を絞り込む |
| `where col like '%foo%'` | `col` 列に対してLIKEパターンで絞り込む（`%`：任意の文字列、`_`：任意の1文字）。参照コレクション列はディープサーチ |
| `where col.contents like 'pat'` | 参照コレクション列 `col` の参照先エントリの**内容文字列**（例: `"2024/01/01,2025/06/15"`）に対してLIKEパターンで検索 |
| `where 'val' in col` | メンバーシップ検索：`col` 列のセル値をカンマ区切りで分割し、`val` がその中に含まれるかを確認する（大文字小文字を区別しない）。`val` に `%` または `_` が含まれる場合は各トークンに対してLIKEマッチを行う |
| `where 'val' in col.contents` | 参照コレクション列の内容に対するメンバーシップ検索：`col` 列のエントリの内容文字列をカンマ区切りで分割し、`val`（LIKEパターン可）が含まれるかを確認する |
| `[select *] where cond` | `select *` は省略可。`where` のみでも同じ動作 |
| `select count where cond` | フィルタ条件に合致する件数のみを右端ラベルに表示する（`count: N / 合計`）。テーブルの表示行は変化しない |
| `select prop.entry.contents` | ルックアップモード：参照コレクション列 `prop` のエントリ `entry` の内容（カンマ区切り値）を1行ずつテーブルに表示する。右端ラベルは `N values — prop.entry` となり、先頭列ヘッダーが `prop.entry` に変化する（通常モードに戻ると元に戻る） |
| `cond1 and cond2` | AND 結合。OR より優先度が高い（SQL と同様） |
| `cond1 or cond2` | OR 結合 |

#### ディープサーチ（参照コレクション列）

参照コレクション列（`schedule`・`contact` など）のセルには参照先エントリの**名前**が表示されています。`like` および平文検索では、この名前だけでなく参照先エントリの**内容**も検索対象に含まれます。たとえば `2024/01/01` と入力すると、`schedule` 列のエントリがその日付を含んでいる行がヒットします。

`where col = 'val'` による完全一致検索は名前のみを対象とします（内容は展開しません）。

#### 使用例

```
where schedule like '%2024%'
  → schedule 参照先の内容に "2024" が含まれる行を絞り込む

where schedule.contents like '%/01%'
  → schedule 参照先の内容文字列中に "/01" が含まれるエントリを持つ行を絞り込む

where '2024/01/01' in schedule.contents
  → schedule 参照先の内容をカンマ区切りで分割し、"2024/01/01" が含まれる行を絞り込む

where '2044%' in schedule.contents
  → schedule 参照先の内容をカンマ区切りで分割し、"2044" で始まるトークンが含まれる行を絞り込む（LIKEパターン）

select schedule.everyday.contents
  → schedule コレクションの "everyday" エントリの内容を値ごとに表示する（先頭列ヘッダーが "schedule.everyday" に変わる）

select count where team = 'alpha' and notes like '%urgent%'
  → team が "alpha" かつ notes に "urgent" を含む行数をカウントする（表示は変えない）

where team = 'alpha' or team = 'beta'
  → team が "alpha" または "beta" の行を絞り込む
```
