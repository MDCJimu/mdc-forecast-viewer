# MDC AI月次着地予測システム — クラウド閲覧専用版

院長がPCやスマホから、URLでいつでも月次着地予測を確認するための**閲覧専用**画面です。

想定URL：`https://xxxxx.streamlit.app`

---

## この版の位置づけ

- **これは院内検証用のクラウド閲覧専用版です。**
- ローカル運用版（`app/forecast_console.py`）とは違い、**予測更新はできません**。
  - 予測更新ボタン／管理者モード／ログ表示／出力フォルダを開く／`run_all.bat` 実行はありません。
- 表示データは **2026年7月4日時点の集計済み outputs** です（固定のスナップショット）。
- **raw / processed / logs / 個票（患者単位）データは一切含めていません。**
  同梱しているのは集計済みの表示用ファイルだけです。

| | ローカル運用版 | クラウド閲覧専用版（この版） |
|---|---|---|
| ファイル | `app/forecast_console.py` | `cloud_deploy/streamlit_app.py` |
| 予測更新（run_all.bat） | あり | **なし** |
| データ | `C:\MDC_ANALYSIS\...\outputs` を都度読む | 同梱した `data/` の固定スナップショット |
| 想定利用者 | 事務局（更新担当） | 院長（閲覧のみ・URLで） |

---

## 同梱ファイル

```
cloud_deploy/
├── streamlit_app.py                     アプリ本体（閲覧専用）
├── requirements.txt                     依存関係
├── README.md                            このファイル
├── .gitignore
├── .streamlit/
│   └── config.toml                      テーマ（紺×ゴールド）
└── data/                                表示用データ（集計済みのみ）
    ├── dashboard_v3_2026_07.xlsx        前年比較の元データ
    ├── dashboard_v3_summary_2026_07.md
    ├── forecast_summary_v2_2026_07.md
    ├── model_card_v2_2026_07.md
    └── dashboard_v3_2026_07.png         出力レポート確認用（メインではない）
```

`raw/` `processed/` `logs/` `backups/`、`resec_*` `apotool_*` `patient_day_bridge.csv` などの
個票・生データは**含めていません**。

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

パスワードが未入力・不一致の場合、本体は表示されません。

---

## Streamlit Community Cloud へのデプロイ手順

1. **GitHub に `cloud_deploy` の中身をアップロードする**
   （`cloud_deploy` フォルダの中身がリポジトリのルート、または `streamlit_app.py` の場所を後で指定）
2. [share.streamlit.io](https://share.streamlit.io/) に GitHub アカウントでログイン
3. **New app / Create app** を選択
4. **repository / branch / Main file path** を指定
   - Main file path：`streamlit_app.py`（`cloud_deploy` をサブフォルダにした場合は `cloud_deploy/streamlit_app.py`）
5. **Advanced settings → Secrets** に閲覧パスワードを設定：

   ```toml
   VIEW_PASSWORD = "任意のパスワード"
   ```

6. **Deploy** を押す
7. 発行された URL（`https://xxxxx.streamlit.app`）を院長に共有する

---

## 院長に共有するときの注意

- 表示値は**確定値ではなく推定値**です（経営判断のための中心線）。
- 月中の予測は暫定です。自費は変動が大きく、高単価型は案件別の確認が必要です。
- 通常営業ベースとの差は**確定的な損失ではありません**。月末後に実績と比較して再検証します。
- URL とパスワードは院内関係者のみに共有してください。
