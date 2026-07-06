# MDC Forecast Console — クラウド閲覧専用版（日次ローリング予測）

院長がPCやスマホから、URLでいつでも「月末着地見込み」を確認するための**閲覧専用**画面です。

想定URL：`https://xxxxx.streamlit.app`

---

## この版の位置づけ（重要）

- **クラウド閲覧版は予測更新をしません。** 予測更新・`run_all.bat` 実行・raw/processed 処理・患者単位データ処理は**一切行いません。**
- **予測更新はローカル運用版で行います。** ローカルで日次予測を更新し、その結果として生成された
  **集計済みスナップショットだけ**をクラウド閲覧版に反映します。
- 表示するのは各対象月フォルダ内の集計済みファイルのみ。**raw / processed / logs / 患者単位データは一切含めません。**

| | ローカル運用版（本体） | クラウド閲覧専用版（この版） |
|---|---|---|
| 実行 | `run_daily_forecast_update.bat` | 閲覧のみ（予測更新なし） |
| 予測計算 | あり（日次ローリング） | **なし** |
| データ | ローカルの集計済み outputs | 同梱した `data/YYYY_MM/` を読む |
| 想定利用者 | 事務局（更新担当） | 院長（閲覧のみ・URLで） |

---

## 日次ローリング予測とは

月1回の月次運用ではありません。**毎日**、最新のレセコン実績とApotool予約を取り込み、月末着地予測を更新します。

```
月末着地見込み ＝ 予測基準日(as_of)までの実績 ＋ 予測基準日翌日から月末までの残り見込み
```

- 予測基準日(as_of_date)が進むほど確定実績が増え、着地見込みの確度が上がります。
- 当月レセコン実績が未取得のときは、画面上部に「**当月実績未反映**」と明示します。
- `as_of_date` より後の実績は予測に使いません（未来実績リーク防止をローカル側で検証済み）。

---

## データ構造（各対象月フォルダ）

```
cloud_deploy/
├── streamlit_app.py                アプリ本体（日次ローリングビューアー）
├── requirements.txt
├── README.md                       このファイル
├── .streamlit/config.toml          テーマ（紺×ゴールド）
└── data/
    └── 2026_07/                     対象月フォルダ（YYYY_MM）
        ├── latest.json             閲覧版が最初に読む。最新スナップショットを指す
        ├── forecast_history.csv    as_of_date ごとの予測結果（予測推移）
        └── snapshots/
            ├── 2026_07_04/         予測基準日ごとのスナップショット（YYYY_MM_DD）
            │   ├── daily_rolling_forecast.json   その基準日の予測（正データ）
            │   ├── forecast_meta.json            いつ時点の予測か
            │   ├── dashboard_v3.xlsx
            │   ├── dashboard_v3_summary.md
            │   ├── forecast_summary_v2.md
            │   ├── model_card_v2.md
            │   └── dashboard_v3.png              出力レポート（メインではない）
            └── 2026_07_05/
                └── （同上）
```

閲覧版は **`latest.json` を最初に読み**、`latest_snapshot_dir` の最新スナップショットを初期表示します。
サイドバーの「予測基準日(as_of)」セレクタで過去の基準日を選ぶと、その時点の予測と**予測推移・前回予測との差分**を確認できます。

---

## 毎日の更新手順（ローカル運用版で実行）

1. 最新のレセコン実績（`resec_data.xlsx`）とApotool予約（`apotool_*.csv`）をローカルの `raw/` に配置。
2. ローカルで日次更新バッチを実行（`cloud_deploy` ではなくプロジェクト直下）:

   ```bat
   run_daily_forecast_update.bat 2026-07 2026-07-04
   ```

   → V2予測＋dashboard＋日次ローリング予測を再計算し、
   `cloud_deploy/data/2026_07/snapshots/2026_07_04/` を作成、
   `latest.json` / `forecast_history.csv` を更新、安全チェックを実行します。
3. バッチが最後に表示する「GitHubへアップロードするファイル」を **commit / push** する:
   - `cloud_deploy/data/2026_07/latest.json`
   - `cloud_deploy/data/2026_07/forecast_history.csv`
   - `cloud_deploy/data/2026_07/snapshots/<YYYY_MM_DD>/`（6ファイル一式）
   - （初回のみ）`streamlit_app.py` / `requirements.txt` / `README.md` / `.streamlit/config.toml`
4. Streamlit Community Cloud が自動で再デプロイし、閲覧版が最新の予測基準日を表示します。

> ⚠️ **アップロード禁止（絶対に含めない）**
> `raw/` `processed/` `logs/` `backups/` `run_all.bat` /
> `resec_data.xlsx` `apotool_*.csv` `patient_day_bridge.csv` `resec_daily_master.csv` `apotool_all_master.csv` /
> 患者名・電話番号・住所・メールアドレス・メモ・患者番号・`C:\` で始まるローカルパス。
> これらは `run_daily_forecast_update.bat` の混入チェックで警告されます。

---

## ローカルでの表示確認

```bash
cd cloud_deploy
py -m streamlit run streamlit_app.py
```

初期パスワード（secrets/環境変数が未設定のとき）：`mdc202607`

---

## パスワード保護

閲覧パスワードは次の優先順で決まります。

1. `st.secrets["VIEW_PASSWORD"]`（Streamlit Community Cloud の Secrets）
2. 環境変数 `VIEW_PASSWORD`
3. どちらも無い場合は仮パスワード `mdc202607`

---

## Streamlit Community Cloud へのデプロイ

1. GitHub に `cloud_deploy` の中身をアップロード
2. [share.streamlit.io](https://share.streamlit.io/) にログイン → New app
3. Main file path：`streamlit_app.py`（サブフォルダにした場合は `cloud_deploy/streamlit_app.py`）
4. Advanced settings → Secrets に `VIEW_PASSWORD = "任意のパスワード"`
5. Deploy → 発行URLを院長に共有

---

## 院長に共有するときの注意

- 表示値は**確定値ではなく推定値**です（過去検証済みロジックによる経営判断の中心線）。
- 日次ローリング予測は「予測基準日までの実績＋残り見込み」で着地を計算します。基準日が進むほど確度が上がります。
- 当月レセコン実績が未反映のときは、画面上部に「当月実績未反映」と表示されます。
- 通常営業ベースとの差は**確定的な損失ではありません**。木曜休診影響は候補として扱い、月末後に吸収判定します。
- URL とパスワードは院内関係者のみに共有してください。
