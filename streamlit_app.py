# -*- coding: utf-8 -*-
"""
MDC Forecast Console — クラウド閲覧専用版（日次ローリング予測ビューアー）
========================================================================
院長がURLで最新の月末着地見込みを確認するための閲覧専用画面です。
- 予測更新なし / run_all.bat 実行なし / raw・processed・患者単位データ処理なし
- 表示するのは、ローカル運用版で生成した「集計済みスナップショット」だけ
- 正データ = daily_rolling_forecast.json（と forecast_history.csv）。
  dashboard_v3.png / .xlsx は「出力レポート確認（参考表示）」に残す（主役ではない）。
- 画面主役 = 日次ローリング予測の詳細カードUI（dashboard_v3風・紺×ゴールド）

データ構造（各対象月フォルダ）:
  data/<YYYY_MM>/
    latest.json / forecast_history.csv
    snapshots/<YYYY_MM_DD>/
        daily_rolling_forecast.json  … その基準日の予測（正データ）
        forecast_meta.json
        dashboard_v3.png / .xlsx / _summary.md / forecast_summary_v2.md /
        model_card_v2.md   … 共有・保存用の出力レポート（参考表示）

過去実績ビュー:
  data/history/
    monthly_actuals.csv  … 月次の確定実績（集計済み・患者情報なし）
    history_meta.json    … 収録期間・生成日時などのメタ情報
  ローカルの scripts/build_history_aggregates.py が生成する。当月（未確定月）は含まない。

起動: py -m streamlit run streamlit_app.py
"""
import os
import re
import json
import csv
import html as _html
import streamlit as st

# deploy-marker: portfolio current-month forecast (2026-07-10e) — redeploy trigger

# 本文上部に表示するビルド識別子。Cloud が古いビルドを配信していないか
# 画面から即座に確認できるようにするための目印。サイドバーが折りたたまれて
# いても見えるよう、ページ切替の直下に置く。
APP_BUILD = "2026-07-10e portfolio-forecast"

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
FALLBACK_PW = "mdc202607"

F_XLSX = "dashboard_v3.xlsx"
F_SUMMARY = "dashboard_v3_summary.md"
F_FORECAST = "forecast_summary_v2.md"
F_MODELCARD = "model_card_v2.md"
F_PNG = "dashboard_v3.png"
F_META = "forecast_meta.json"
F_ROLL = "daily_rolling_forecast.json"
F_LATEST = "latest.json"
F_HISTORY = "forecast_history.csv"

HIST_DIR = "history"
F_MONTHLY_ACTUALS = "monthly_actuals.csv"
F_HISTORY_META = "history_meta.json"
F_PORTFOLIO = "portfolio_monthly.csv"
F_PORTFOLIO_META = "portfolio_meta.json"
F_PF_FORECAST = "portfolio_forecast.json"

PF_DATA_ACTUAL = "確定実績"
PF_DATA_FORECAST = "当月見込み"

MONTH_RE = re.compile(r"^(\d{4})_(\d{2})$")
ASOF_RE = re.compile(r"^(\d{4})_(\d{2})_(\d{2})$")

PAGE_FORECAST = "今月の予測"
PAGE_HISTORY = "過去実績"
PAGE_PORTFOLIO = "売上ポートフォリオ"

# 分類コード → (表示名, 色, 積み上げ順。0がグラフの最下段)
PF_BUCKETS = [
    ("stock", "ストック型売上", "#0B1F3A", 0),
    ("spot", "スポット型売上", "#2F6BD6", 1),
    ("high_value", "高単価型売上", "#B08A4E", 2),
    ("unclassified", "混合・未分類", "#9AA3B0", 3),
]
PF_LABELS = [n for _, n, _, _ in PF_BUCKETS]
PF_COLORS = [c for _, _, c, _ in PF_BUCKETS]

st.set_page_config(page_title="MDC Forecast Console（日次ローリング予測）",
                   page_icon="📈", layout="wide")


# ======================================================================
# 表示ヘルパー
# ======================================================================
def man(v):
    try:
        return f"{round(float(v) / 10000):,}万円"
    except Exception:
        return "取得不可"


def manv(v):
    try:
        return f"{round(float(v) / 10000):,}"
    except Exception:
        return "—"


def sman(v):
    try:
        n = round(float(v) / 10000)
        return (f"▲{abs(n):,}万円" if n < 0 else (f"+{n:,}万円" if n > 0 else "±0万円"))
    except Exception:
        return "取得不可"


def smanv(v):
    try:
        n = round(float(v) / 10000)
        return (f"▲{abs(n):,}" if n < 0 else (f"+{n:,}" if n > 0 else "±0"))
    except Exception:
        return "—"


def signclass(v):
    try:
        n = float(v)
        return "dn" if n < 0 else ("up" if n > 0 else "fl")
    except Exception:
        return "fl"


def intv(v):
    try:
        return f"{round(float(v)):,}"
    except Exception:
        return "—"


def sint(v):
    try:
        n = round(float(v))
        return (f"▲{abs(n):,}" if n < 0 else (f"+{n:,}" if n > 0 else "±0"))
    except Exception:
        return "—"


def pct_of(a, b):
    """(a-b)/b*100 の符号付き％表示。b が無ければ空。"""
    try:
        a = float(a); b = float(b)
        if b == 0:
            return ""
        r = (a - b) / b * 100
        return (f"（▲{abs(r):.1f}%）" if r < 0 else (f"（+{r:.1f}%）" if r > 0 else "（±0%）"))
    except Exception:
        return ""


def fnum(v):
    try:
        return float(v)
    except Exception:
        return None


def ym_label(folder):
    m = MONTH_RE.match(folder)
    return f"{int(m.group(1))}年{int(m.group(2))}月" if m else folder


def asof_label(folder):
    m = ASOF_RE.match(folder)
    return f"{int(m.group(1))}年{int(m.group(2))}月{int(m.group(3))}日" if m else folder


def asof_from_dir(folder):
    m = ASOF_RE.match(folder)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else folder


# ======================================================================
# データ読み込み
# ======================================================================
def list_months():
    if not os.path.isdir(DATA):
        return []
    months = [n for n in os.listdir(DATA)
              if MONTH_RE.match(n) and os.path.isdir(os.path.join(DATA, n))]
    return sorted(months, reverse=True)


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def read_text(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return None


def list_snapshots(month):
    d = os.path.join(DATA, month, "snapshots")
    if not os.path.isdir(d):
        return []
    snaps = [n for n in os.listdir(d)
             if ASOF_RE.match(n) and os.path.isdir(os.path.join(d, n))]
    return sorted(snaps, reverse=True)


def read_history(month):
    """forecast_history.csv を list[dict] で返す（対象月ぶんのみ・as_of昇順）。"""
    p = os.path.join(DATA, month, F_HISTORY)
    rows = []
    try:
        with open(p, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("target_month") == month.replace("_", "-"):
                    rows.append(r)
    except Exception:
        return []
    rows.sort(key=lambda r: r.get("as_of_date", ""))
    return rows


def parse_actions_from_md(text):
    if not text:
        return []
    acts, capture = [], False
    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("##"):
            capture = ("経営アクション" in s) or ("確認すること" in s) or ("打ち手" in s)
            continue
        if capture:
            m = re.match(r"^\d+[\.\)、]\s*(.+)$", s)
            if m:
                acts.append(m.group(1).strip())
    return acts


# ======================================================================
# パスワード保護
# ======================================================================
def expected_password():
    try:
        if "VIEW_PASSWORD" in st.secrets:
            return str(st.secrets["VIEW_PASSWORD"])
    except Exception:
        pass
    return os.environ.get("VIEW_PASSWORD") or FALLBACK_PW


def check_password():
    if st.session_state.get("_authed"):
        return True
    st.markdown(
        "<div style='max-width:460px;margin:8vh auto 0;text-align:center;'>"
        "<div style='font-size:22px;font-weight:800;color:#0B1F3A;'>MDC Forecast Console</div>"
        "<div style='font-size:13px;color:#6b7686;margin:8px 0 18px;'>"
        "日次ローリング予測・クラウド閲覧専用画面</div></div>",
        unsafe_allow_html=True)
    c = st.columns([1, 2, 1])[1]
    with c:
        pw = st.text_input("閲覧パスワード", type="password", key="_pw_input")
        if st.button("表示する", type="primary", width="stretch"):
            if pw == expected_password():
                st.session_state["_authed"] = True
                st.rerun()
            else:
                st.error("パスワードが違います。")
        st.caption("パスワードは院長・事務局にご確認ください。")
    return False


# ======================================================================
# CSS（紺×ゴールド・落ち着いた赤・dashboard_v3風の詳細カード）
# ======================================================================
CSS = """
<style>
:root{
  --navy:#0B1F3A;--navy2:#16305a;--ink:#161C26;--muted:#697180;--faint:#9AA3B0;
  --line:#E8EBF1;--bg:#F4F5F8;--card:#FFFFFF;--gold:#B08A4E;--gold2:#CBA968;
  --green:#2E8B57;--blue:#2F6BD6;--red:#BC5548;
  --shadow:0 10px 30px -18px rgba(18,28,48,.35);
}
html,body{background:var(--bg);}
.stApp,[data-testid="stAppViewContainer"]{background:var(--bg);
  font-family:"Segoe UI","Hiragino Kaku Gothic ProN","Yu Gothic UI",Meiryo,system-ui,-apple-system,sans-serif;
  color:var(--ink);}
[data-testid="stDecoration"]{display:none;}
[data-testid="stHeader"]{background:transparent;height:0;}
[data-testid="stToolbar"],[data-testid="stAppDeployButton"],#MainMenu{display:none;}
[data-testid="stSidebar"]{background:#fff;border-right:1px solid var(--line);}
.block-container{max-width:1120px;padding-top:2.4rem !important;padding-bottom:4rem;}
*{font-feature-settings:"palt";}
hr{display:none;}
/* ---- ヘッダー ---- */
.mfc-title{font-size:42px;font-weight:800;color:var(--navy);letter-spacing:-.8px;line-height:1.08;margin:0 0 8px;text-wrap:balance;}
.mfc-vchip{display:inline-block;font-size:10.5px;font-weight:800;letter-spacing:1.5px;color:var(--gold);
  border:1px solid var(--gold);border-radius:20px;padding:3px 12px;margin-left:13px;vertical-align:middle;text-transform:uppercase;}
.mfc-sub{font-size:15px;color:var(--muted);margin:0 0 4px;line-height:1.7;max-width:770px;}
.mfc-meta{font-size:13px;color:var(--faint);margin:12px 0 0;}
.mfc-meta b{color:var(--navy);font-weight:700;}
.mfc-warn{background:#FBF3E4;border:1px solid #ECD9B0;border-radius:12px;
  padding:13px 18px;margin:18px 0 4px;font-size:14px;color:#836018;font-weight:600;line-height:1.6;}
.mfc-colkey{display:flex;gap:16px;flex-wrap:wrap;align-items:center;font-size:12px;color:var(--faint);margin:16px 0 2px;}
.mfc-colkey .d{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:0;}
/* ---- ラベルチップ ---- */
.lab{display:inline-block;font-size:10.5px;font-weight:800;border-radius:6px;padding:2px 8px;margin-left:8px;
  vertical-align:middle;letter-spacing:.4px;}
.lab-act{background:#E7F2EC;color:#22694A;}
.lab-mdl{background:#E9F0FB;color:#295BB8;}
.lab-est{background:#F6EFDE;color:#8A6A24;}
.lab-ref{background:#EFF1F5;color:#6B7686;}
/* ---- 大見出し（階層＝主役・見出し文字が主役）---- */
.mfc-tier{margin:58px 0 8px;font-size:31px;font-weight:800;color:var(--navy);letter-spacing:-.5px;line-height:1.15;text-wrap:balance;}
.mfc-tier .n{display:block;font-size:11px;font-weight:800;letter-spacing:2.5px;color:var(--gold);
  text-transform:uppercase;margin-bottom:8px;}
.mfc-tier .ln{display:none;}
/* ---- 小見出し ---- */
.mfc-sec{font-size:21px;font-weight:800;color:var(--navy);margin:34px 0 16px;letter-spacing:-.3px;line-height:1.25;}
/* ---- 今日の結論（ヒーロー）---- */
.mfc-conc{display:grid;grid-template-columns:1.45fr 1fr;gap:34px;align-items:center;
  background:radial-gradient(120% 140% at 88% 6%,rgba(203,169,104,.16),transparent 42%),
    linear-gradient(155deg,#0a1b31 0%,#122f57 60%,#16386c 100%);
  border-radius:22px;padding:36px 42px;color:#fff;box-shadow:0 24px 56px -24px rgba(11,31,58,.62);}
.mfc-conc .cLbl{font-size:12px;color:var(--gold2);font-weight:800;letter-spacing:2px;text-transform:uppercase;}
.mfc-conc .cBig{font-size:62px;font-weight:800;line-height:1;margin:12px 0 18px;letter-spacing:-1.5px;font-variant-numeric:tabular-nums;}
.mfc-conc .cBig span{font-size:22px;color:#aeb9c9;margin-left:7px;font-weight:700;letter-spacing:0;}
.mfc-conc .cV{display:inline-flex;align-items:center;font-size:14.5px;font-weight:800;border-radius:30px;padding:8px 18px;}
.mfc-conc .cV.up{background:rgba(120,214,160,.13);color:#8FE3B0;border:1px solid rgba(120,214,160,.42);}
.mfc-conc .cV.dn{background:rgba(232,150,150,.12);color:#FFB3B3;border:1px solid rgba(232,150,150,.42);}
.mfc-conc .cRight{display:grid;grid-template-columns:1fr 1fr;gap:20px 22px;align-content:center;
  border-left:1px solid rgba(255,255,255,.14);padding-left:30px;}
.mfc-conc .cItem{font-size:12.5px;color:#a9b5c6;line-height:1.35;}
.mfc-conc .cItem b{display:block;font-size:23px;color:#fff;font-weight:800;margin-top:3px;letter-spacing:-.4px;font-variant-numeric:tabular-nums;}
.mfc-conc .cItem small{display:block;color:#8494a8;font-weight:600;font-size:11.5px;margin-top:2px;}
/* ---- 今日の見立て ---- */
.mfc-take{background:var(--card);border:1px solid var(--line);border-left:3px solid var(--gold);
  border-radius:14px;padding:20px 24px;margin:16px 0 0;font-size:16px;color:var(--ink);line-height:1.65;font-weight:600;box-shadow:var(--shadow);}
.mfc-take .k{display:block;font-size:11px;font-weight:800;letter-spacing:2px;color:var(--gold);text-transform:uppercase;margin-bottom:9px;}
.mfc-take b{color:var(--navy);font-weight:800;}
.mfc-take ul{margin:13px 0 0;padding:0;list-style:none;display:grid;gap:8px;font-weight:500;font-size:14px;color:var(--muted);}
.mfc-take li{padding-left:20px;position:relative;line-height:1.5;}
.mfc-take li:before{content:"→";position:absolute;left:0;color:var(--gold);font-weight:800;}
/* ---- ヒーロー追補（プレミアム）---- */
.mfc-conc{padding:40px 44px;gap:40px;}
.mfc-conc .cBig{font-size:66px;margin:14px 0 20px;}
.mfc-conc .cRow{display:flex;align-items:center;gap:16px;flex-wrap:wrap;}
.mfc-conc .cBadge{display:inline-flex;align-items:center;font-size:14px;font-weight:800;letter-spacing:.3px;
  border-radius:30px;padding:9px 20px;background:linear-gradient(135deg,#d8bd86,#b0894e);color:#241a06;
  box-shadow:0 8px 20px -8px rgba(176,138,78,.75);}
.mfc-conc .cBadge.dn{background:linear-gradient(135deg,#e2b4b0,#b5544a);color:#2a0f0c;box-shadow:0 8px 20px -8px rgba(181,84,74,.6);}
.mfc-conc .cYoY{font-size:15px;color:#c4cedd;font-weight:700;}
.mfc-conc .cYoY em{font-style:normal;color:#8FE3B0;}
.mfc-conc .cRight{grid-template-columns:1fr;gap:20px;padding-left:34px;}
.mfc-conc .cItem b small{font-size:13px;color:#aeb9c9;margin-left:3px;font-weight:700;}
/* ---- 経営アクションカード ---- */
.mfc-act{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:22px 26px;margin:16px 0 0;box-shadow:var(--shadow);}
.mfc-act .k{font-size:11px;font-weight:800;letter-spacing:2px;color:var(--gold);text-transform:uppercase;margin-bottom:11px;}
.mfc-act .lead{font-size:16.5px;font-weight:700;color:var(--navy);line-height:1.55;margin-bottom:17px;}
.mfc-act .lead b{color:var(--navy);}
.mfc-act .rows{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;}
.mfc-act .r{background:#FAFBFC;border:1px solid var(--line);border-radius:12px;padding:15px 17px;}
.mfc-act .r .t{display:block;font-size:14px;font-weight:800;color:var(--navy);margin-bottom:5px;}
.mfc-act .r .t:before{content:"→ ";color:var(--gold);}
.mfc-act .r .d{font-size:12.5px;color:var(--muted);line-height:1.55;}
/* ---- 比較チップ（暦同日/同営業日）---- */
.mfc-cmp{display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin:16px 2px 0;}
.mfc-cmp .chip{display:inline-flex;align-items:center;gap:8px;font-size:13.5px;font-weight:700;color:var(--muted);
  border-radius:30px;padding:9px 17px;border:1px solid var(--line);background:var(--card);box-shadow:var(--shadow);}
.mfc-cmp .chip .lbl{color:var(--navy);font-weight:800;}
.mfc-cmp .chip b{font-size:16px;font-weight:800;font-variant-numeric:tabular-nums;}
.mfc-cmp .chip em{font-style:normal;font-size:12px;}
.mfc-cmp .chip.green b,.mfc-cmp .chip.green em{color:var(--green);}
.mfc-cmp .chip.red b,.mfc-cmp .chip.red em{color:var(--red);}
.mfc-cmp .muted{font-size:12.5px;color:var(--faint);line-height:1.5;flex:1;min-width:230px;}
/* ---- チャートカード ---- */
.mfc-charthead{font-size:15px;font-weight:800;color:var(--navy);margin:6px 2px 10px;}
.mfc-charthead .sub{font-size:12.5px;color:var(--muted);font-weight:600;margin-left:10px;}
[data-testid="stImage"]{background:#fff;border:1px solid var(--line);border-radius:16px;padding:16px 18px;box-shadow:var(--shadow);}
[data-testid="stImage"] img{border-radius:6px;}
[data-testid="stVegaLiteChart"]{background:#fff;border:1px solid var(--line);border-radius:16px;padding:18px 20px 12px;box-shadow:var(--shadow);}
[data-testid="stElementToolbar"]{display:none!important;}
.vega-embed .vega-actions,.vega-embed summary{display:none!important;}
[data-testid="stElementToolbarButton"]{display:none!important;}
.mfc-clegend{display:flex;gap:18px;flex-wrap:wrap;font-size:12px;color:var(--muted);margin:11px 2px 0;}
.mfc-clegend span:before{content:"";display:inline-block;width:14px;height:3px;border-radius:2px;margin-right:6px;vertical-align:3px;}
.mfc-clegend .l1:before{background:#0B1F3A;}
.mfc-clegend .l2:before{height:0;border-top:2px dashed #B08A4E;}
.mfc-clegend .l3:before{background:rgba(11,31,58,.13);height:9px;}
/* ---- カード共通 ---- */
.mfc-cards{display:grid;grid-template-columns:repeat(3,1fr);gap:18px;}
.mfc-cards4{display:grid;grid-template-columns:repeat(4,1fr);gap:18px;}
.mfc-prog{display:grid;grid-template-columns:repeat(4,1fr);gap:18px;}
.mfc-card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:22px;box-shadow:var(--shadow);}
.mfc-card .lb{font-size:14px;font-weight:800;color:var(--navy);margin-bottom:12px;display:flex;align-items:center;flex-wrap:wrap;line-height:1.3;}
.mfc-card .big{font-size:36px;font-weight:800;color:var(--navy);line-height:1;letter-spacing:-.7px;font-variant-numeric:tabular-nums;}
.mfc-card .big .u{font-size:14px;color:var(--faint);margin-left:4px;font-weight:700;letter-spacing:0;}
.mfc-card .py{font-size:13px;color:var(--muted);margin-top:12px;line-height:1.65;}
.mfc-card .py b{color:var(--navy);font-weight:700;}
.mfc-card .na{font-size:18px;font-weight:800;color:var(--faint);}
.mfc-card .cardsw{display:none;}
/* 上部アクセント（控えめ・色の意味）*/
.mfc-card.tp-g{box-shadow:var(--shadow),inset 0 3px 0 var(--green);}
.mfc-card.tp-b{box-shadow:var(--shadow),inset 0 3px 0 var(--blue);}
.mfc-card.tp-o{box-shadow:var(--shadow),inset 0 3px 0 var(--gold);}
.mfc-card.tp-r{box-shadow:var(--shadow),inset 0 3px 0 var(--red);}
.mfc-card.tp-n{box-shadow:var(--shadow),inset 0 3px 0 #cfd6e1;}
/* ---- 予約補正チップ ---- */
.mfc-split{display:flex;gap:14px;flex-wrap:wrap;}
.mfc-chip{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 18px;font-size:12.5px;
  color:var(--muted);box-shadow:var(--shadow);min-width:150px;}
.mfc-chip b{color:var(--navy);font-size:18px;display:block;margin-top:4px;font-weight:800;font-variant-numeric:tabular-nums;}
.mfc-chip.key{background:linear-gradient(150deg,#102a4c,#16386c);border:none;color:#a9b5c6;}
.mfc-chip.key b{color:#fff;}
/* ---- 注記 ---- */
.mfc-note{font-size:14px;color:var(--muted);margin:16px 2px 0;line-height:1.75;}
.mfc-note b{color:var(--navy);font-weight:700;}
/* ---- 折りたたみ内（判断/差分/打ち手）---- */
.mfc-judge{font-size:14.5px;color:var(--ink);line-height:1.75;}
.mfc-judge b{color:var(--navy);}.mfc-judge ul{margin:10px 0 0;padding-left:20px;}.mfc-judge li{margin:5px 0;}
.mfc-diff{font-size:14.5px;color:var(--ink);line-height:1.75;}
.mfc-diff b{color:var(--navy);}
.mfc-actions ul{list-style:none;margin:0;padding:0;}
.mfc-actions li{font-size:14.5px;color:var(--ink);padding:12px 0 12px 28px;position:relative;border-bottom:1px solid var(--line);line-height:1.55;}
.mfc-actions li:last-child{border-bottom:none;}
.mfc-actions li:before{content:"→";position:absolute;left:2px;color:var(--gold);font-weight:800;}
.mfc-actions .h{display:none;}
/* ---- Streamlit expander ---- */
[data-testid="stExpander"]{border:1px solid var(--line)!important;border-radius:14px!important;
  background:var(--card);box-shadow:var(--shadow);margin-bottom:14px;overflow:hidden;}
[data-testid="stExpander"] summary{font-size:15px;font-weight:700;color:var(--navy);padding:14px 18px;}
[data-testid="stExpander"] summary:hover{color:var(--gold);}
/* ---- レスポンシブ ---- */
@media (max-width:900px){
  .mfc-title{font-size:32px;}.mfc-tier{font-size:25px;}.mfc-sec{font-size:19px;}
  .mfc-conc{grid-template-columns:1fr;gap:22px;padding:26px 24px;}
  .mfc-conc .cBig{font-size:48px;}
  .mfc-conc .cRight{border-left:none;border-top:1px solid rgba(255,255,255,.14);padding-left:0;padding-top:20px;
    grid-template-columns:1fr 1fr;}
  .mfc-cards,.mfc-cards4,.mfc-prog{grid-template-columns:1fr 1fr;}
  .mfc-act .rows{grid-template-columns:1fr;}
}
@media (max-width:560px){.mfc-cards,.mfc-cards4,.mfc-prog{grid-template-columns:1fr;}}
</style>
"""


# ======================================================================
# ページ切替（本文上部）専用CSS
#   サイドバーは環境によって折りたたまれて見えないことがあるため、
#   ページ切替は本文上部（タイトル直下・メタ情報の上）に置くのを正とする。
#   本体CSSには radio を隠すルールは無いが、Streamlit 本体の更新や
#   将来のCSS追記で消えないよう、ここで可視化を !important で固定する。
#   セレクタはサイドバー限定にせず、アプリ内の radio 全体に効かせる
#   （このアプリの radio はページ切替の1つだけ）。
# ======================================================================
NAV_CSS = """
<style>
[data-testid="stRadio"]{
  display:block !important; visibility:visible !important; opacity:1 !important;
  height:auto !important; overflow:visible !important;
  background:#F7F8FA; border:1px solid #E8EBF1; border-left:3px solid #B08A4E;
  border-radius:12px; padding:12px 18px 10px; margin:14px 0 18px;
}
[data-testid="stRadio"] label{
  visibility:visible !important; opacity:1 !important;
}
[data-testid="stRadio"] [data-testid="stWidgetLabel"] p{
  font-size:11px !important; font-weight:800 !important; letter-spacing:1.6px;
  color:#B08A4E !important; text-transform:uppercase; margin-bottom:8px !important;
}
[data-testid="stRadio"] div[role="radiogroup"]{
  display:flex !important; flex-direction:row !important; flex-wrap:wrap;
  gap:6px 28px; visibility:visible !important; opacity:1 !important;
  height:auto !important;
}
[data-testid="stRadio"] div[role="radiogroup"] > label{
  display:flex !important; align-items:center; margin:0 !important; padding:2px 0;
}
[data-testid="stRadio"] div[role="radiogroup"] p{
  font-size:15px !important; font-weight:700 !important; color:#0B1F3A !important;
  visibility:visible !important; opacity:1 !important;
}
.mdc-build{
  font-size:10.5px; color:#9AA3B0; letter-spacing:.3px; margin-top:18px;
}
.mdc-navnote{
  font-size:12px; color:#9AA3B0; margin:-8px 2px 16px;
}
</style>
"""


def page_nav():
    """ページ切替。本文上部（タイトル直下・メタ情報の上）に描画する。
    ウィジェットは session_state['nav_page'] を唯一の正とする。"""
    st.markdown(NAV_CSS, unsafe_allow_html=True)
    st.radio("表示する画面", [PAGE_FORECAST, PAGE_HISTORY, PAGE_PORTFOLIO],
             key="nav_page", horizontal=True,
             help="「今月の予測」は当月の着地見込み、「過去実績」は確定した過去の実績、"
                  "「売上ポートフォリオ」は売上構造の内訳です。")
    st.markdown(f"<div class='mdc-navnote'>build: {_html.escape(APP_BUILD)}</div>",
                unsafe_allow_html=True)


def lab(kind):
    m = {"act": ("lab-act", "実績"), "mdl": ("lab-mdl", "推定"),
         "est": ("lab-est", "見込"), "ref": ("lab-ref", "参考")}
    cls, txt = m.get(kind, ("lab-ref", "参考"))
    return f"<span class='lab {cls}'>{txt}</span>"


def hc(lb, num, unit="万円", cls="", numcls="", sub=""):
    sb = f"<div class='sb'>{sub}</div>" if sub else ""
    return (f"<div class='mfc-hc {cls}'><div class='lb'>{lb}</div>"
            f"<div class='vl {numcls}'>{num}<span class='u'>{unit}</span></div>{sb}</div>")


def sowhat(text):
    return f"<div class='mfc-sowhat'><span class='sw'>So What</span>{text}</div>"


def trend_chart(hist, py_actual):
    """日次予測の推移グラフ（Altair＝Streamlit同梱・外部CDN不使用）。
    基準予測ライン＋80%レンジ帯＋前年同月ベースライン。凡例はHTML側で表示。"""
    import pandas as pd
    import altair as alt

    pts = [r for r in hist if fnum(r.get("current_forecast_total"))]
    if not pts:
        return None
    df = pd.DataFrame([{
        "as_of": r.get("as_of_date"),
        "基準予測": (fnum(r.get("current_forecast_total")) or 0) / 1e4,
        "lo": (fnum(r.get("forecast_low_80")) or 0) / 1e4,
        "hi": (fnum(r.get("forecast_high_80")) or 0) / 1e4,
    } for r in pts])
    NAVY, GOLD = "#0B1F3A", "#B08A4E"
    x = alt.X("as_of:T", axis=alt.Axis(format="%m-%d", title=None, labelAngle=0, tickCount=len(df)))
    ys = alt.Scale(zero=False, nice=True)
    band = alt.Chart(df).mark_area(color=NAVY, opacity=0.10).encode(
        x=x, y=alt.Y("lo:Q", scale=ys, title=None), y2="hi:Q")
    line = alt.Chart(df).mark_line(color=NAVY, strokeWidth=3, interpolate="monotone",
        point=alt.OverlayMarkDef(color=NAVY, fill="white", strokeWidth=2, size=70)).encode(
        x=x, y=alt.Y("基準予測:Q", scale=ys, title=None),
        tooltip=[alt.Tooltip("as_of:T", title="基準日", format="%Y-%m-%d"),
                 alt.Tooltip("基準予測:Q", title="着地見込み(万円)", format=",.0f")])
    layers = [band, line]
    if py_actual:
        rule = alt.Chart(pd.DataFrame({"y": [py_actual / 1e4]})).mark_rule(
            color=GOLD, strokeDash=[6, 4], size=2).encode(y="y:Q")
        layers = [band, rule, line]
    return (alt.layer(*layers).properties(height=250)
            .configure_view(strokeWidth=0)
            .configure_axis(grid=True, gridColor="#EDEFF3", domainColor="#E8EBF1",
                            tickColor="#E8EBF1", labelColor="#8A94A3", labelFontSize=12))


# ======================================================================
# 本体描画
# ======================================================================
def render(month, snap, nav=None):
    st.markdown(CSS, unsafe_allow_html=True)
    ym_jp = ym_label(month)
    snap_dir = os.path.join(DATA, month, "snapshots", snap)

    meta = read_json(os.path.join(snap_dir, F_META)) or {}
    roll = read_json(os.path.join(snap_dir, F_ROLL)) or {}
    summary_md = read_text(os.path.join(snap_dir, F_SUMMARY))
    forecast_md = read_text(os.path.join(snap_dir, F_FORECAST))
    modelcard_md = read_text(os.path.join(snap_dir, F_MODELCARD))
    png_path = os.path.join(snap_dir, F_PNG)

    as_of = meta.get("as_of_date") or asof_from_dir(snap)
    gen_at = meta.get("generated_at") or roll.get("generated_at") or "—"
    resec_status = meta.get("resec_data_status") or roll.get("resec_data_status") or "不明"
    apo_status = meta.get("apotool_data_status") or roll.get("apotool_data_status") or "不明"
    actual_through = meta.get("actual_data_through") or roll.get("actual_data_through")
    res_through = meta.get("reservation_data_through") or roll.get("reservation_data_through")

    # ---------- タイトル + 凡例 ----------
    st.markdown('<div class="mfc-title">MDC Forecast Console'
                '<span class="mfc-vchip">正データ</span></div>', unsafe_allow_html=True)
    st.markdown(
        "<div class='mfc-sub'><b style='color:#0B1F3A;font-weight:800'>日次ローリング予測｜経営ダッシュボード</b>　"
        "表示値は確定値ではなく、経営判断の中心線（推定値）です。月末後に実績と照合して検証します。</div>",
        unsafe_allow_html=True)

    if nav:
        nav()

    st.markdown(
        f"<div class='mfc-meta'>対象月 <b>{ym_jp}</b>　·　予測基準日 <b>{as_of}</b>　·　"
        f"{meta.get('forecast_mode','日次ローリング予測')}　·　"
        f"{roll.get('model_version','MDC Forecast Model v2.0')}　·　生成 {gen_at}　·　院内検証用・閲覧専用</div>",
        unsafe_allow_html=True)
    st.markdown(
        "<div class='mfc-colkey'>"
        "<span><span class='d' style='background:#2E8B57'></span>実績</span>"
        "<span><span class='d' style='background:#2F6BD6'></span>推定</span>"
        "<span><span class='d' style='background:#B08A4E'></span>見込</span>"
        "<span><span class='d' style='background:#BC5548'></span>注意</span>"
        "<span><span class='d' style='background:#9AA3B0'></span>参考</span>"
        "</div>", unsafe_allow_html=True)

    # ---------- 当月実績未反映の警告 ----------
    if resec_status != "反映済み":
        st.markdown(
            "<div class='mfc-warn'>⚠ 当月レセコン実績が未反映です。"
            "経過分も<b>推定値（②）</b>で表示しています（確定実績＝①は0）。"
            "当月分を含む最新レセコンを取り込み、日次更新を再実行すると①が増え、確度が上がります。</div>",
            unsafe_allow_html=True)

    if not roll:
        st.warning("このスナップショットの予測データ（daily_rolling_forecast.json）が読み込めません。"
                   "ローカル運用版で再生成してください。")
        return

    cur = fnum(roll.get("current_forecast_total"))
    base = fnum(roll.get("normal_baseline_forecast"))
    gap = fnum(roll.get("gap_to_normal_baseline"))
    py = fnum(roll.get("previous_year_actual"))
    yoy = fnum(roll.get("yoy_diff"))
    yoy_rate = roll.get("yoy_rate")
    lo = fnum(roll.get("forecast_low_80"))
    hi = fnum(roll.get("forecast_high_80"))
    actual_td = fnum(roll.get("actual_to_date_total")) or 0
    elapsed = fnum(roll.get("elapsed_unrecorded_total")) or 0
    remaining = fnum(roll.get("remaining_forecast_total")) or 0
    sup = roll.get("supplementary") or {}

    # ===== 第1階層：経営サマリー（今日の結論）=====
    prog = roll.get("progress_through_yesterday") or {}
    p_cur = prog.get("current") or {}
    p_py = prog.get("prev_year_same_day") or {}
    p_biz = prog.get("prev_year_same_bizdays") or {}
    cur_td = fnum(p_cur.get("total"))
    py_td = fnum(p_py.get("total"))
    yoy_td = fnum(prog.get("yoy_to_date_diff"))
    yoy_td_rate = prog.get("yoy_to_date_rate")
    cur_cut = prog.get("current_cutoff") or actual_through
    py_cut = prog.get("prev_year_cutoff") or "—"
    cur_days = p_cur.get("clinic_days")
    py_days = p_py.get("clinic_days")
    biz_days = p_biz.get("clinic_days")
    biz_diff = fnum(p_biz.get("diff_vs_current"))
    biz_rate = p_biz.get("rate")
    beats = bool(roll.get("landing_beats_prevyear"))
    cons = fnum(roll.get("conservative_forecast"))
    td_pct = f"（{yoy_td_rate:+.1f}%）" if isinstance(yoy_td_rate, (int, float)) else ""
    biz_pct = f"（{biz_rate:+.1f}%）" if isinstance(biz_rate, (int, float)) else ""
    beats_word = "前年を上回る見込み" if beats else "前年に届かない見込み"
    r80 = f"{manv(lo)}〜{manv(hi)}" if (lo is not None and hi is not None) else "取得不可"
    yoy_pct = f"（{yoy_rate:+.1f}%）" if isinstance(yoy_rate, (int, float)) else ""
    below = (cur is not None and py is not None and cur < py)
    yoy_word = "下回る" if below else ("上回る" if (cur is not None and py is not None and cur > py) else "ほぼ並ぶ")
    verdict_cls = "dn" if below else "up"
    foot_word = "弱め" if (yoy_td is not None and yoy_td < 0) else "堅調"
    biz_word = "上回り" if (biz_diff is not None and biz_diff >= 0) else "下回り"
    month_word = "前年超え見込み" if beats else "前年に届かない見込み"
    takeaway = (f"足元は前年同日比では<b>{foot_word}</b>だが、"
                f"実績日数基準の前年比較では<b>{biz_word}</b>、月末は<b>{month_word}</b>。")

    actual_days = roll.get("actual_days_count") or 0
    remaining_days_count = roll.get("remaining_days_count") or 0
    planned_days = 21
    unplanned_actual_days = 2
    actual_daily_avg = (actual_td / actual_days) if actual_days else 0.0
    remaining_daily_avg = (remaining / remaining_days_count) if remaining_days_count else 0.0
    pace_gap = ((remaining_daily_avg / actual_daily_avg - 1) if actual_daily_avg else 0.0)
    vc = fnum(roll.get("visit_care_forecast_total"))

    st.markdown('<div class="mfc-tier"><span class="n">SUMMARY</span>今日の結論'
                '<span class="ln"></span></div>', unsafe_allow_html=True)
    st.markdown(
        "<div class='mfc-conc'><div class='cLeft'>"
        f"<div class='cLbl'>今月着地見込み（{ym_jp}）</div>"
        f"<div class='cBig'>{manv(cur)}<span>万円</span></div>"
        "<div class='cRow'>"
        f"<span class='cBadge {verdict_cls}'>{beats_word}</span>"
        f"<span class='cYoY'>前年同月比 {sman(yoy)} <em>{yoy_pct}</em></span>"
        "</div></div>"
        "<div class='cRight'>"
        f"<div class='cItem'>前年同月<b>{man(py)}</b></div>"
        f"<div class='cItem'>保守ライン<b>{man(cons)}</b></div>"
        f"<div class='cItem'>80%予測レンジ<b>{r80}<small>万円</small></b></div>"
        "</div></div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='mfc-act'><div class='k'>今日のアクション</div>"
        f"<div class='lead'>{takeaway}</div>"
        "<div class='rows'>"
        "<div class='r'><span class='t'>自費売上化</span><span class='d'>高単価型の月内売上化を確認</span></div>"
        "<div class='r'><span class='t'>来院充足</span><span class='d'>空き枠・キャンセル枠の再充填</span></div>"
        "<div class='r'><span class='t'>訪問介護</span><span class='d'>入力遅れ分は月末見込みで別建て反映</span></div>"
        "</div></div>", unsafe_allow_html=True)

    st.markdown('<div class="mfc-sec">この見込みの前提</div>', unsafe_allow_html=True)
    st.markdown(
        "<div class='mfc-cards4'>"
        "<div class='mfc-card tp-g'><div class='lb'>診療日数の前提</div>"
        f"<div class='py'>予定診療日数 <b>{planned_days}日</b><br>実績のある日数 <b>{actual_days}日</b><br>予定外実績日 <b>{unplanned_actual_days}日</b><br>残り予定診療日数 <b>{remaining_days_count}日</b></div></div>"
        "<div class='mfc-card tp-n'><div class='lb'>売上ペースの前提</div>"
        f"<div class='py'>現時点平均 <b>{actual_daily_avg/10000:.1f}万円/日</b><br>残り見込み <b>{remaining_daily_avg/10000:.1f}万円/日</b><br>残り期間は現時点平均より <b>{pace_gap*100:+.0f}%</b> 高いペース</div></div>"
        "<div class='mfc-card tp-o'><div class='lb'>押し上げ要素</div>"
        f"<div class='py'>訪問・介護見込み <b>{manv(vc)}</b>万円<br>予約増加倍率 <b>{roll.get('reservation_growth_multiplier'):.2f}x</b><br>予約ペース補正 <b>{roll.get('reservation_factor_final', roll.get('reservation_factor')):.2f}x</b></div></div>"
        "<div class='mfc-card tp-r'><div class='lb'>注意</div>"
        f"<div class='py'>現在の着地見込みは、残り{remaining_days_count}診療日で1日あたり約<b>{remaining_daily_avg/10000:.1f}万円</b>を積む前提です。<br>これは現時点平均約<b>{actual_daily_avg/10000:.1f}万円/日</b>を約<b>{pace_gap*100:.0f}%</b>上回るペースです。<br>前年同月実績には現時点では届かない見込みです。</div></div>"
        "</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='mfc-note'>実績のある日数には、予定外に実績が入った日を含みます。予定診療日数とは一致しない場合があります。</div>",
        unsafe_allow_html=True)

    # ===== 昨日〆時点の進捗（当年 → 前年同日 → 前年差 → 月末着地）=====
    st.markdown('<div class="mfc-sec">昨日〆時点の進捗（当年 → 前年同日 → 前年差 → 月末着地）</div>',
                unsafe_allow_html=True)
    st.markdown(
        "<div class='mfc-cards4'>"
        f"<div class='mfc-card tp-g'><div class='lb'>① 昨日〆 当月実績{lab('act')}</div>"
        f"<div class='big'>{manv(cur_td)}<span class='u'>万円</span></div>"
        f"<div class='py'>外来保険 {man(p_cur.get('insurance_outpatient'))}／自費 {man(p_cur.get('selfpay'))}"
        f"／物販 {man(p_cur.get('product'))}<br>{cur_cut}〆・{cur_days}診療日</div></div>"
        f"<div class='mfc-card tp-n'><div class='lb'>② 前年同日〆 実績{lab('ref')}</div>"
        f"<div class='big'>{manv(py_td)}<span class='u'>万円</span></div>"
        f"<div class='py'>外来保険 {man(p_py.get('insurance_outpatient'))}／自費 {man(p_py.get('selfpay'))}"
        f"／物販 {man(p_py.get('product'))}<br>{py_cut}〆・{py_days}診療日</div></div>"
        f"<div class='mfc-card tp-n'><div class='lb'>③ 暦同日ベース 前年差</div>"
        f"<div class='big'>{smanv(yoy_td)}<span class='u'>万円</span></div>"
        f"<div class='py'>増減率 {td_pct or '—'}<br>外来保険+自費+物販ベース</div></div>"
        f"<div class='mfc-card tp-o'><div class='lb'>④ 月末着地見込み{lab('mdl')}</div>"
        f"<div class='big'>{manv(cur)}<span class='u'>万円</span></div>"
        f"<div class='py'>保守 {man(cons)}／前年月末 {man(py)}<br>{beats_word}</div></div>"
        "</div>", unsafe_allow_html=True)
    cal_cls = "red" if (yoy_td is not None and yoy_td < 0) else "green"
    biz_cls = "green" if (biz_diff is not None and biz_diff >= 0) else "red"
    st.markdown(
        "<div class='mfc-cmp'>"
        f"<span class='chip {cal_cls}'><span class='lbl'>暦同日</span><b>{smanv(yoy_td)}万円</b><em>{td_pct}</em></span>"
        f"<span class='chip {biz_cls}'><span class='lbl'>実績日数基準</span><b>{smanv(biz_diff)}万円</b><em>{biz_pct}</em></span>"
        f"<span class='muted'>暦同日は当年{cur_days}／前年{py_days}診療日（木曜休診）でズレるため、"
        f"実績日数基準の前年比較を補助指標として表示します。予定診療日数21日とは別軸です。訪問・介護は月末着地で別建て。</span>"
        "</div>", unsafe_allow_html=True)

    # ===== 第2階層：着地根拠 / 月末着地見込みの比較 =====
    v2ms = fnum(roll.get("v2_month_start_forecast"))
    rvis = roll.get("reservation_visible_remaining_as_of")
    rproj = roll.get("reservation_projected_final_remaining")
    st.markdown('<div class="mfc-tier"><span class="n">EVIDENCE</span>着地の根拠'
                '<span class="ln"></span></div>', unsafe_allow_html=True)
    # ----- 日次予測の推移グラフ -----
    _ch = trend_chart(read_history(month), py)
    if _ch is not None:
        st.markdown("<div class='mfc-charthead'>日次予測の推移"
                    "<span class='sub'>予測基準日ごとの月末着地見込み（万円）</span></div>",
                    unsafe_allow_html=True)
        st.altair_chart(_ch, width="stretch")
        st.markdown(
            "<div class='mfc-clegend'>"
            "<span class='l1'>基準予測（着地見込み）</span>"
            "<span class='l3'>80%予測レンジ</span>"
            f"<span class='l2'>前年同月 {man(py)}</span>"
            "</div>", unsafe_allow_html=True)
    st.markdown('<div class="mfc-sec">月末着地見込みの比較（基準・保守・参考・前年）</div>', unsafe_allow_html=True)
    st.markdown(
        "<div class='mfc-cards4'>"
        f"<div class='mfc-card tp-o'><div class='lb'>基準予測{lab('mdl')}</div>"
        f"<div class='big'>{manv(cur)}<span class='u'>万円</span></div>"
        "<div class='py'>訪問・介護＋予約増加補正</div></div>"
        f"<div class='mfc-card tp-b'><div class='lb'>保守ライン{lab('mdl')}</div>"
        f"<div class='big'>{manv(cons)}<span class='u'>万円</span></div>"
        "<div class='py'>予約増加を織り込まない下限</div></div>"
        f"<div class='mfc-card tp-n'><div class='lb'>月初参考{lab('ref')}</div>"
        f"<div class='big'>{manv(v2ms)}<span class='u'>万円</span></div>"
        "<div class='py'>V2月初型の参考値</div></div>"
        f"<div class='mfc-card tp-g'><div class='lb'>前年同月{lab('act')}</div>"
        f"<div class='big'>{manv(py)}<span class='u'>万円</span></div>"
        "<div class='py'>2025年7月実績</div></div>"
        "</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='mfc-note'>"
        f"基準予測＝残り予約 <b>{rvis:,}件</b> を月中増加込み <b>{rproj:,}件</b> で見込み。"
        "保守ライン＝予約増加を織り込まない下限。いずれも推定値で、日々更新されます。</div>",
        unsafe_allow_html=True)

    # ===== 着地の内訳（①＋②＋③＋④）=====
    vc = fnum(roll.get("visit_care_forecast_total"))
    st.markdown('<div class="mfc-sec">着地の内訳（① 確定 ＋ ② 経過 ＋ ③ 残り ＋ ④ 訪問・介護）</div>',
                unsafe_allow_html=True)
    st.markdown(
        "<div class='mfc-prog'>"
        f"<div class='mfc-card tp-g'><div class='lb'>① 確定実績{lab('act')}</div>"
        f"<div class='big'>{manv(actual_td)}<span class='u'>万円</span></div>"
        f"<div class='py'>〜{as_of}・外来保険＋自費＋物販（取込済み）</div></div>"
        f"<div class='mfc-card tp-b'><div class='lb'>② 経過分の推定{lab('mdl')}</div>"
        f"<div class='big'>{manv(elapsed)}<span class='u'>万円</span></div>"
        f"<div class='py'>経過したが実績未取込の診療日</div></div>"
        f"<div class='mfc-card tp-o'><div class='lb'>③ 残り期間の見込み{lab('est')}</div>"
        f"<div class='big'>{manv(remaining)}<span class='u'>万円</span></div>"
        f"<div class='py'>{as_of}翌日〜月末（木曜休診反映）</div></div>"
        f"<div class='mfc-card tp-o'><div class='lb'>④ 訪問・介護見込み{lab('est')}</div>"
        f"<div class='big'>{manv(vc)}<span class='u'>万円</span></div>"
        f"<div class='py'>過去12か月平均・別建て（ペース補正なし）</div></div>"
        "</div>", unsafe_allow_html=True)
    st.markdown(
        f"<div class='mfc-note'>① ＋ ② ＋ ③ ＋ ④ ＝ 月末着地見込み <b>{man(cur)}</b>。"
        "訪問・介護は入力遅れのため外来予約ペースと分け、過去12か月平均で別建て。"
        f"　｜　レセコン：<b>{resec_status}</b>"
        + (f"（{actual_through}まで）" if actual_through else "（当月未取込）")
        + f"　予約：<b>{apo_status}</b>"
        + (f"（{res_through}まで）" if res_through else "") + "</div>",
        unsafe_allow_html=True)

    # ===== 予約増加補正（月中の予約増加を反映）=====
    rg_vis = roll.get("reservation_visible_remaining_as_of")
    rg_mult = roll.get("reservation_growth_multiplier")
    rg_proj = roll.get("reservation_projected_final_remaining")
    rg_fac = roll.get("reservation_factor_final", roll.get("reservation_factor"))
    if rg_mult is not None:
        st.markdown('<div class="mfc-sec">予約増加補正（月中の予約増加を反映）</div>', unsafe_allow_html=True)
        st.markdown(
            "<div class='mfc-split'>"
            f"<div class='mfc-chip'>現在の残り予約：<b>{rg_vis:,}件</b></div>"
            f"<div class='mfc-chip'>予約増加倍率：<b>{rg_mult:.2f}x</b>（過去12か月）</div>"
            f"<div class='mfc-chip'>月末最終見込み：<b>{rg_proj:,}件</b></div>"
            f"<div class='mfc-chip' style='background:#eef3fb;border-color:#c9d6ea;'>"
            f"適用ペース補正：<b>{rg_fac:.2f}</b></div>"
            "</div>", unsafe_allow_html=True)
        st.markdown(
            "<div class='mfc-note'>現在予約だけで過小評価しないよう、過去12か月の予約増加"
            f"（<b>{rg_mult:.2f}x</b>）を反映。上下限 0.85〜1.10。訪問・介護は対象外（④で別建て）。</div>",
            unsafe_allow_html=True)

    # ===== 第3階層：詳細分析 =====
    st.markdown('<div class="mfc-tier"><span class="n">KPI</span>経営KPI'
                '<span class="ln"></span></div>', unsafe_allow_html=True)

    # ----- 経営KPI（来院・初診・キャンセル・患者数）-----
    st.markdown('<div class="mfc-sec">来院・初診・キャンセル・患者数（当月見込み）</div>', unsafe_allow_html=True)
    vis = sup.get("visit") or {}
    sho = sup.get("shoshin") or {}
    pat = sup.get("patient_total") or {}
    can = sup.get("cancel") or {}

    def cnt_card(lb_, cur_v, py_v, unit, labkind, so, tp="tp-n"):
        diff = (cur_v - py_v) if (cur_v is not None and py_v is not None) else None
        pyline = (f"前年同月 <b>{intv(py_v)}{unit}</b>　{sint(diff)}{pct_of(cur_v, py_v)}"
                  if py_v is not None else "前年同月：取得不可")
        return (f"<div class='mfc-card {tp}'><div class='lb'>{lb_}{lab(labkind)}</div>"
                f"<div class='big'>{intv(cur_v)}<span class='u'>{unit}</span></div>"
                f"<div class='py'>{pyline}</div>"
                f"<div class='cardsw'><span class='sw'>So What</span>{so}</div></div>")

    # 総患者数（月間ユニーク）：当月分は元データ直読みで人数のみ算出、月末は来院見込み×前年圧縮比
    if pat.get("available"):
        fc_ = pat.get("forecast"); atd_ = pat.get("actual_to_date"); py_ = pat.get("prevyear")
        diff_ = (fc_ - py_) if (fc_ is not None and py_ is not None) else None
        pyline_ = (f"前年同月 <b>{intv(py_)}人</b>　{sint(diff_)}{pct_of(fc_, py_)}"
                   if py_ is not None else "前年同月：取得不可")
        atd_line = (f"<br>当月確定 <b>{intv(atd_)}人</b>（〜{str(actual_through or as_of)}・重複排除）"
                    if atd_ is not None else "")
        patient_card = (f"<div class='mfc-card tp-g'><div class='lb'>総患者数{lab('mdl')}</div>"
                        f"<div class='big'>{intv(fc_)}<span class='u'>人</span></div>"
                        f"<div class='py'>{pyline_}{atd_line}</div>"
                        "<div class='cardsw'><span class='sw'>So What</span>"
                        "来院枠を埋めて患者数を確保する。</div></div>")
    else:
        pyv = pat.get("prevyear")
        patient_card = (f"<div class='mfc-card tp-g'><div class='lb'>総患者数"
                        f"<span class='lab lab-ref'>データ未取得</span></div>"
                        f"<div class='na'>データ未取得</div>"
                        f"<div class='py'>月間ユニーク患者数は日次集計から復元できないため未取得。"
                        + (f"<br>（参考）前年同月 <b>{intv(pyv)}人</b>" if pyv is not None else "")
                        + "</div><div class='cardsw'><span class='sw'>So What</span>"
                        "確定は月末レセコンで補足。当月は来院回数・予約構成で代替把握する。</div></div>")

    can_avail = can.get("available")
    if can_avail and can.get("current_rate") is not None:
        cr = can.get("current_rate"); pyr = can.get("prevyear_rate")
        cdiff = (cr - pyr) if (cr is not None and pyr is not None) else None
        cdtxt = (f"　{'▲' if (cdiff or 0) < 0 else '+'}{abs(cdiff):.1f}pt" if cdiff is not None else "")
        cancel_card = (f"<div class='mfc-card tp-r'><div class='lb'>キャンセル率{lab('act')}</div>"
                       f"<div class='big'>{cr:.1f}<span class='u'>%</span></div>"
                       f"<div class='py'>登録済み予約(as_of時点)ベース"
                       + (f"<br>前年同月 <b>{pyr:.1f}%</b>{cdtxt}" if pyr is not None else "") + "</div>"
                       "<div class='cardsw'><span class='sw'>So What</span>"
                       "空き枠の再充填で来院数の下振れを防ぐ。</div></div>")
    else:
        cancel_card = ("<div class='mfc-card tp-r'><div class='lb'>キャンセル率"
                       "<span class='lab lab-ref'>データ未取得</span></div>"
                       "<div class='na'>データ未取得</div></div>")

    st.markdown(
        "<div class='mfc-cards4'>"
        + patient_card
        + cnt_card("来院回数", vis.get("forecast"), vis.get("prevyear"), "回", "est",
                   "来院回数の前年差は売上の量的な下押し。他曜日への振替・空き枠再充填で回復を図る。", "tp-n")
        + cnt_card("初診", sho.get("forecast"), sho.get("prevyear"), "件", "est",
                   "初診のうち自費相談・治療移行見込みを確認し、自費売上化につなげる。", "tp-o")
        + cancel_card
        + "</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='mfc-note'>来院回数・初診は当月着地見込み（確定＋残り見込み）。"
        "総患者数は当月レセコンの受診者を重複排除した確定人数を基に月末見込みを算出"
        "（人数のみ・個人情報は非保持）。キャンセル率・予約構成は as_of時点の登録済み予約の実データ。</div>",
        unsafe_allow_html=True)

    # ----- 予約構成（折りたたみ）-----
    with st.expander("予約ポートフォリオ（型別・登録済み予約）", expanded=False):
        comp = sup.get("reservation_composition") or {}
        if comp.get("available"):
            types = comp.get("types") or {}
            order = [("継続管理型", "tp-g"), ("都度治療型", "tp-n"),
                     ("高単価型", "tp-o"), ("混合・判定保留", "tp-r")]
            cards = []
            for name, tp in order:
                t = types.get(name) or {}
                cv = t.get("current"); pv = t.get("prevyear")
                diff = (cv - pv) if (cv is not None and pv is not None) else None
                pyline = (f"前年同月(実績) <b>{intv(pv)}件</b>　{sint(diff)}{pct_of(cv, pv)}"
                          if pv is not None else "前年同月：取得不可")
                cards.append(
                    f"<div class='mfc-card {tp}'><div class='lb'>{name}{lab('act')}</div>"
                    f"<div class='big'>{intv(cv)}<span class='u'>件</span></div>"
                    f"<div class='py'>登録済み予約(as_of時点)<br>{pyline}</div></div>")
            st.markdown("<div class='mfc-cards4'>" + "".join(cards) + "</div>", unsafe_allow_html=True)
            st.markdown(
                "<div class='mfc-note'>当月(" + ym_jp + ")の as_of時点で登録済みの予約を型別集計した実データ"
                "（合計 " + intv(comp.get("current_total")) + "件）。月内に登録・キャンセルが増減するため、"
                "前年比ではなく<b>充足・空き枠の管理指標</b>として見ます。</div>", unsafe_allow_html=True)
        else:
            st.markdown("<div class='mfc-card'><div class='na'>データ未取得</div>"
                        "<div class='py'>当月の予約構成データが取得できません。</div></div>",
                        unsafe_allow_html=True)

    # ===== 参考レポート（折りたたみ）=====
    st.markdown('<div class="mfc-tier"><span class="n">REFERENCE</span>参考レポート'
                '<span class="ln"></span></div>', unsafe_allow_html=True)

    with st.expander("売上内訳・判断サマリー（詳細）", expanded=False):
        hvl = fnum(roll.get("high_value_selfpay_low"))
        hvh = fnum(roll.get("high_value_selfpay_high"))
        hv_disp = f"{manv(hvl)}〜{manv(hvh)}万円" if (hvl is not None and hvh is not None) else "取得不可"
        st.markdown(
            f"<div class='mfc-judge'>現時点では<b>前年同月を{yoy_word}見込み</b>。"
            f"<ul><li>着地見込み <b>{man(cur)}</b>／前年 <b>{man(py)}</b>（{sman(yoy)}{yoy_pct}）。</li>"
            f"<li>通常営業ベース <b>{man(base)}</b> との差 <b>{sman(gap)}</b> は木曜休診影響の候補"
            "（確定損失ではない）。</li>"
            f"<li>差を埋める鍵＝高単価型 自費レンジ <b>{hv_disp}</b> の月内売上化。</li></ul></div>",
            unsafe_allow_html=True)

        def scard(lb_, key, akey, pkey, tp):
            v = fnum(roll.get(key)); av = fnum(roll.get(akey)); pv = fnum(roll.get(pkey))
            diff = (v - pv) if (v is not None and pv is not None) else None
            pyline = (f"前年 <b>{manv(pv)}万</b>　{sman(diff)}{pct_of(v, pv)}"
                      if pv is not None else "前年：取得不可")
            atxt = (f"うち確定 {manv(av)}万" if (av and av > 0) else "確定：未反映")
            return (f"<div class='mfc-card {tp}'><div class='lb'>{lb_}{lab('mdl')}</div>"
                    f"<div class='big'>{manv(v)}<span class='u'>万円</span></div>"
                    f"<div class='py'>{pyline}<br>{atxt}</div></div>")

        st.markdown(
            "<div class='mfc-cards'>"
            + scard("保険診療売上予測", "insurance_forecast", "insurance_actual_to_date", "insurance_prevyear", "tp-g")
            + scard("自費診療売上予測", "selfpay_forecast", "selfpay_actual_to_date", "selfpay_prevyear", "tp-o")
            + scard("物販売上予測", "product_forecast", "product_actual_to_date", "product_prevyear", "tp-n")
            + "</div>", unsafe_allow_html=True)
        outp = fnum(roll.get("outpatient_insurance_forecast"))
        vins = fnum(roll.get("visit_insurance_forecast"))
        care = fnum(roll.get("care_forecast"))
        if outp is not None:
            st.markdown(
                f"<div class='mfc-note'>保険内訳：外来 <b>{man(outp)}</b>（予約ペース補正あり）／"
                f"訪問 <b>{man(vins)}</b>／介護 <b>{man(care)}</b>。訪問・介護は入力遅れのため"
                "過去12か月平均で別建て（0扱いしない）。</div>", unsafe_allow_html=True)

    with st.expander("予測の推移・前回予測との差分", expanded=False):
        hist = read_history(month)
        if len(hist) >= 1:
            try:
                import pandas as pd
                df = pd.DataFrame([{
                    "予測基準日": r.get("as_of_date"),
                    "着地見込み(万円)": (fnum(r.get("current_forecast_total")) or 0) / 10000,
                    "前年同月(万円)": (fnum(r.get("previous_year_actual")) or 0) / 10000,
                } for r in hist]).set_index("予測基準日")
                st.line_chart(df, height=260)
            except Exception:
                for r in hist:
                    st.write(f"- {r.get('as_of_date')}：着地 {man(fnum(r.get('current_forecast_total')))}")
        else:
            st.info("推移の表示には複数の予測基準日が必要です。")
        prev = None
        for r in hist:
            if r.get("as_of_date", "") < as_of:
                prev = r
        if prev:
            pc = fnum(prev.get("current_forecast_total"))
            d_cur = (cur - pc) if (cur is not None and pc is not None) else None
            st.markdown(
                f"<div class='mfc-diff'>前回 <b>{prev.get('as_of_date')}</b> と比べ、着地見込みは "
                f"<b>{man(pc)} → {man(cur)}</b>"
                f"（<span class='mfc-{signclass(d_cur)}' style='font-weight:800'>{sman(d_cur)}</span>）。"
                "基準日が進むほど確度が上がります。</div>", unsafe_allow_html=True)
        else:
            st.markdown("<div class='mfc-diff'>これより前の予測基準日はまだありません"
                        "（本スナップショットが最初）。翌日以降から差分表示。</div>", unsafe_allow_html=True)

    with st.expander("今月の打ち手（院長・事務局向け）", expanded=False):
        acts = parse_actions_from_md(summary_md)
        if acts:
            li = "".join(f"<li><b>{i}.</b> {_html.escape(str(a))}</li>" for i, a in enumerate(acts, 1))
            body = f"<ul>{li}</ul>"
        else:
            body = ("<ul><li><b>1.</b> 高単価型自費の案件別進捗を確認（月内売上化か翌月送りか）。</li>"
                    "<li><b>2.</b> 継続管理型の未充足枠・キャンセル枠を他曜日へ補充。</li>"
                    "<li><b>3.</b> 月末確定後、通常営業ベースとの差が吸収されたかを判定。</li></ul>")
        st.markdown(f"<div class='mfc-actions'>{body}</div>", unsafe_allow_html=True)

    # ========== 予測の考え方 ==========
    with st.expander("この予測の考え方（院長向け）", expanded=False):
        st.markdown(
            "- 予測値は、AIが感覚で出しているものではありません。\n"
            "- **土台のV2予測モデル**は過去約6年分の売上・予約データで過去検証しており、"
            "直近12か月の平均誤差は約6.2％（月初時点で1か月先を予測した場合の検証値）。\n"
            "- **日次ローリング予測**は、V2をベースに**予測基準日までの実績＋残り見込み**を組み合わせた運用版です。"
            "基準日が進むほど確定実績が増え、着地見込みの確度が上がります。\n"
            "- 上部カードが**正データ**です。下部の出力レポート（dashboard_v3）は月初ベースの参考表示で、"
            "数値が異なる場合があります。\n"
            "- 表示値は確定値ではなく推定値です。月末後に実績と照合して検証します。")

    # ========== 出力レポート確認（参考表示・主役にしない）==========
    with st.expander("出力レポート確認（参考表示・共有／保存用）", expanded=False):
        st.warning("この出力レポートは参考表示です。正データは上部の日次ローリング予測カードです。")
        st.caption("dashboard_v3 は月初ベース（月初時点予測）で自動生成した参考レポートです。"
                   "日次ローリング予測（上部カード）とは数値が異なる場合があります。"
                   "院長がご覧になる正しい数値は、上部の『現時点着地見込み』ほかのカードです。")
        if os.path.exists(png_path):
            st.image(png_path, width="stretch",
                     caption="【参考表示・月初ベース】dashboard_v3（正データではありません／正データは上部カード）")
        else:
            st.caption("このスナップショットの dashboard_v3.png はありません。")
        if summary_md:
            with st.expander("summary.md の内容（参考・月初ベース）", expanded=False):
                st.info("参考表示です。正データは上部の日次ローリング予測カードです。")
                st.markdown(summary_md)
        if forecast_md:
            with st.expander("予測根拠サマリー（forecast_summary_v2・参考）", expanded=False):
                st.info("参考表示（V2モデルの月初予測サマリー）です。正データは上部の日次ローリング予測カードです。")
                st.markdown(forecast_md)
        if modelcard_md:
            with st.expander("モデル説明資料（model_card_v2・参考）", expanded=False):
                st.markdown(modelcard_md)

    # ========== スナップショット情報 ==========
    with st.expander("このスナップショットの情報（いつ時点の予測か）", expanded=False):
        st.json({k: meta.get(k) for k in [
            "target_month", "as_of_date", "generated_at", "forecast_mode",
            "resec_data_status", "apotool_data_status", "actual_data_through",
            "reservation_data_through", "model_version", "pipeline_exit_code"]} or meta)
        leak = roll.get("leak_checks") or {}
        if leak:
            st.caption("未来実績リーク防止チェック（ローカル運用版で検証済み）")
            for k, v in leak.items():
                st.markdown(f"- {'✅' if v.get('ok') else '⚠️'} **{k}**：{v.get('detail','')}")

    with st.expander("注意・限界（必ずお読みください）", expanded=False):
        st.markdown(
            "- 表示値は確定値ではなく、経営判断のための推定値です。\n"
            "- 日次ローリング予測は、予測基準日までの実績＋残り見込みで着地を計算します。\n"
            "- 当月レセコン実績が未反映のときは、その旨を上部に表示します。\n"
            "- 自費は変動が大きく、差の主因になりえます。高単価型は案件別の確認が必要です。\n"
            "- 通常営業ベースとの差は、月末後に実績と比較して再検証します（確定的な損失ではありません）。\n"
            "- 足りない項目は推測で作らず「データ未取得」と表示しています。\n"
            "- 本画面は院内検証用・閲覧専用です。予測更新はローカル運用版で行います。")

    st.divider()
    st.caption("MDC Forecast Console（日次ローリング予測・クラウド閲覧専用）｜院内検証用｜"
               "表示値は推定値・確定値ではありません｜個人情報・患者番号は非表示")


# ======================================================================
# 過去実績ビュー
#   data/history/ の集計済みデータだけを読む。患者単位データは扱わない。
# ======================================================================
def hist_path(name):
    return os.path.join(DATA, HIST_DIR, name)


@st.cache_data(show_spinner=False)
def _load_actuals(_mtime):
    import pandas as pd
    df = pd.read_csv(hist_path(F_MONTHLY_ACTUALS), encoding="utf-8-sig")
    return df.sort_values("年月").reset_index(drop=True)


def read_monthly_actuals():
    p = hist_path(F_MONTHLY_ACTUALS)
    if not os.path.isfile(p):
        return None
    try:
        return _load_actuals(os.path.getmtime(p))
    except Exception:
        return None


def shift_ym(ym, months):
    y, m = int(ym[:4]), int(ym[5:7])
    t = y * 12 + (m - 1) + months
    return f"{t // 12:04d}-{t % 12 + 1:02d}"


def fiscal_year_of(ym):
    """年度（4月始まり）。2026-03 は 2025年度。"""
    y, m = int(ym[:4]), int(ym[5:7])
    return y - 1 if m < 4 else y


def fiscal_range(fy):
    return f"{fy}-04", f"{fy + 1}-03"


def period_bounds(choice, months, custom):
    """期間プリセット名から (開始年月, 終了年月) を返す。データ範囲外は自動でクリップ。"""
    lo, hi = months[0], months[-1]
    if choice == "直近12か月":
        return (months[-12] if len(months) >= 12 else lo), hi
    if choice == "今年度":
        return fiscal_range(fiscal_year_of(hi))
    if choice == "昨年度":
        return fiscal_range(fiscal_year_of(hi) - 1)
    if choice == "任意期間":
        return custom
    return lo, hi  # 全期間


def cancel_rate(p):
    tot = float(p["予約総件数"].sum())
    return (float(p["キャンセル件数"].sum()) / tot * 100) if tot else None


def kpi(lb, big, unit, sub="", cls="tp-n"):
    sb = f"<div class='py'>{sub}</div>" if sub else ""
    return (f"<div class='mfc-card {cls}'><div class='lb'>{lb}</div>"
            f"<div class='big'>{big}<span class='u'>{unit}</span></div>{sb}</div>")


def _ymdate(s):
    import pandas as pd
    return pd.to_datetime(s + "-01")


AX = dict(grid=True, gridColor="#EDEFF3", domainColor="#E8EBF1",
          tickColor="#E8EBF1", labelColor="#8A94A3", labelFontSize=12)


def chart_total_sales(p):
    """月次総売上の推移（棒）。"""
    import pandas as pd
    import altair as alt
    d = pd.DataFrame({"月": _ymdate(p["年月"]), "総売上": p["月間総売上"] / 1e4})
    ch = alt.Chart(d).mark_bar(color="#0B1F3A", opacity=.92).encode(
        x=alt.X("月:T", axis=alt.Axis(format="%Y-%m", title=None, labelAngle=-55)),
        y=alt.Y("総売上:Q", title=None),
        tooltip=[alt.Tooltip("月:T", title="年月", format="%Y-%m"),
                 alt.Tooltip("総売上:Q", title="総売上(万円)", format=",.0f")])
    return (ch.properties(height=260).configure_view(strokeWidth=0)
            .configure_axis(**AX))


def chart_breakdown(p):
    """保険／自費／物販の積み上げ推移。"""
    import pandas as pd
    import altair as alt
    d = p[["年月", "保険診療売上", "自費診療売上", "物販売上"]].copy()
    d["月"] = _ymdate(d["年月"])
    long = d.melt(id_vars="月", value_vars=["保険診療売上", "自費診療売上", "物販売上"],
                  var_name="区分", value_name="売上")
    long["売上"] = long["売上"] / 1e4
    order = ["保険診療売上", "自費診療売上", "物販売上"]
    ch = alt.Chart(long).mark_bar().encode(
        x=alt.X("月:T", axis=alt.Axis(format="%Y-%m", title=None, labelAngle=-55)),
        y=alt.Y("売上:Q", title=None, stack="zero"),
        color=alt.Color("区分:N", sort=order,
                        scale=alt.Scale(domain=order,
                                        range=["#0B1F3A", "#B08A4E", "#9AA3B0"]),
                        legend=alt.Legend(orient="top", title=None, direction="horizontal")),
        order=alt.Order("区分:N", sort="descending"),
        tooltip=[alt.Tooltip("月:T", title="年月", format="%Y-%m"),
                 alt.Tooltip("区分:N", title="区分"),
                 alt.Tooltip("売上:Q", title="売上(万円)", format=",.0f")])
    return (ch.properties(height=260).configure_view(strokeWidth=0)
            .configure_axis(**AX))


def chart_visits(p):
    """来院・患者の推移。指標ごとにスケールが違うので縦に3段、y軸は独立。"""
    import pandas as pd
    import altair as alt
    d = p[["年月", "総患者数", "総来院回数", "初診件数"]].copy()
    d["月"] = _ymdate(d["年月"])
    order = ["総患者数", "総来院回数", "初診件数"]
    long = d.melt(id_vars="月", value_vars=order, var_name="指標", value_name="値")
    ch = alt.Chart(long).mark_line(color="#0B1F3A", strokeWidth=2,
                                   interpolate="monotone").encode(
        x=alt.X("月:T", axis=alt.Axis(format="%Y-%m", title=None, labelAngle=-55)),
        y=alt.Y("値:Q", title=None, scale=alt.Scale(zero=False, nice=True)),
        tooltip=[alt.Tooltip("月:T", title="年月", format="%Y-%m"),
                 alt.Tooltip("指標:N", title="指標"),
                 alt.Tooltip("値:Q", title="値", format=",.0f")])
    return (ch.properties(height=95)
            .facet(row=alt.Row("指標:N", sort=order, title=None,
                               header=alt.Header(labelAngle=0, labelAlign="left",
                                                 labelFontSize=12, labelColor="#0B1F3A",
                                                 labelFontWeight="bold")))
            .resolve_scale(y="independent")
            .configure_view(strokeWidth=0)
            .configure_axis(**AX))


TABLE_COLS = ["年月", "診療日数", "月間総売上", "保険診療売上", "自費診療売上", "物販売上",
              "外来保険売上", "訪問保険売上", "介護売上", "総患者数", "総来院回数",
              "初診件数", "レセプト枚数", "予約総件数", "来院予約件数", "キャンセル件数",
              "キャンセル率", "1診療日あたり売上", "1来院あたり売上", "1患者あたり売上"]


def render_history(nav=None):
    st.markdown(CSS, unsafe_allow_html=True)
    df = read_monthly_actuals()

    st.markdown(
        "<div class='mfc-title'>MDC Forecast Console"
        "<span class='mfc-vchip'>Actuals</span></div>"
        "<div class='mfc-sub'>確定した過去実績を任意の期間で振り返る画面です。"
        "表示しているのは月次に集計済みの確定値のみで、患者単位のデータは含みません。</div>",
        unsafe_allow_html=True)

    if nav:
        nav()

    if df is None or df.empty:
        st.warning("過去実績データがありません。"
                   "ローカルで scripts/build_history_aggregates.py を実行し、"
                   "data/history/monthly_actuals.csv を配置してください。")
        return

    meta = read_json(hist_path(F_HISTORY_META)) or {}
    months = list(df["年月"])

    # ---- 期間選択 ----
    st.markdown("<div class='mfc-tier'><span class='n'>Period</span>期間を選ぶ</div>",
                unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1.2, 1, 1])
    with c1:
        choice = st.selectbox("期間", ["直近12か月", "今年度", "昨年度", "全期間", "任意期間"],
                              index=0, key="hist_period")
    custom = (months[0], months[-1])
    with c2:
        s_sel = st.selectbox("開始年月", months, index=max(0, len(months) - 12),
                             key="hist_from", disabled=(choice != "任意期間"))
    with c3:
        e_sel = st.selectbox("終了年月", months, index=len(months) - 1,
                             key="hist_to", disabled=(choice != "任意期間"))
    if choice == "任意期間":
        custom = (s_sel, e_sel) if s_sel <= e_sel else (e_sel, s_sel)

    lo, hi = period_bounds(choice, months, custom)
    p = df[(df["年月"] >= lo) & (df["年月"] <= hi)]

    if p.empty:
        st.warning(f"選択した期間（{lo} 〜 {hi}）に該当する確定月がありません。"
                   f"収録範囲は {months[0]} 〜 {months[-1]} です。")
        return

    a_lo, a_hi = p["年月"].iloc[0], p["年月"].iloc[-1]
    st.markdown(f"<div class='mfc-meta'>対象期間 <b>{a_lo} 〜 {a_hi}</b>（{len(p)}か月）"
                f"｜収録範囲 {months[0]} 〜 {months[-1]}"
                f"｜{'確定月のみ' if meta.get('確定月のみ') else ''}</div>",
                unsafe_allow_html=True)

    # ---- 前年同期 ----
    want = [shift_ym(m, -12) for m in p["年月"]]
    prev = df[df["年月"].isin(want)]
    full_prev = len(prev) == len(p)
    yoy_html, yoy_sub = "—", "前年同期のデータが揃っていません"
    if full_prev and float(prev["月間総売上"].sum()) > 0:
        cur_t, prv_t = float(p["月間総売上"].sum()), float(prev["月間総売上"].sum())
        r = (cur_t - prv_t) / prv_t * 100
        yoy_html = f"{'+' if r >= 0 else '▲'}{abs(r):.1f}"
        yoy_sub = f"前年同期 <b>{manv(prv_t)}万円</b>（{want[0]} 〜 {want[-1]}）"

    cr = cancel_rate(p)

    # ---- KPIカード ----
    st.markdown("<div class='mfc-tier'><span class='n'>Summary</span>期間の実績</div>",
                unsafe_allow_html=True)
    row1 = "".join([
        kpi("期間総売上", manv(p["月間総売上"].sum()), "万円",
            f"診療日数 <b>{intv(p['診療日数'].sum())}</b> 日", "tp-b"),
        kpi("前年同期比", yoy_html, "%", yoy_sub,
            "tp-g" if (full_prev and yoy_html.startswith("+")) else
            ("tp-r" if full_prev else "tp-n")),
        kpi("保険売上", manv(p["保険診療売上"].sum()), "万円",
            f"外来 <b>{manv(p['外来保険売上'].sum())}</b>／訪問 <b>{manv(p['訪問保険売上'].sum())}</b>"
            f"／介護 <b>{manv(p['介護売上'].sum())}</b>（万円）", "tp-n"),
        kpi("自費売上", manv(p["自費診療売上"].sum()), "万円",
            f"売上構成比 <b>{p['自費診療売上'].sum() / p['月間総売上'].sum() * 100:.1f}%</b>", "tp-o"),
    ])
    row2 = "".join([
        kpi("物販売上", manv(p["物販売上"].sum()), "万円",
            f"売上構成比 <b>{p['物販売上'].sum() / p['月間総売上'].sum() * 100:.1f}%</b>", "tp-n"),
        kpi("総来院回数", intv(p["総来院回数"].sum()), "回",
            f"総患者数 <b>{intv(p['総患者数'].sum())}</b> 人（月次ユニークの合計）", "tp-n"),
        kpi("初診件数", intv(p["初診件数"].sum()), "件",
            f"月平均 <b>{p['初診件数'].mean():.1f}</b> 件", "tp-n"),
        kpi("キャンセル率", f"{cr:.1f}" if cr is not None else "—", "%",
            f"キャンセル <b>{intv(p['キャンセル件数'].sum())}</b> 件 / "
            f"予約 <b>{intv(p['予約総件数'].sum())}</b> 件", "tp-n"),
    ])
    st.markdown(f"<div class='mfc-cards4'>{row1}</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='mfc-cards4' style='margin-top:18px;'>{row2}</div>",
                unsafe_allow_html=True)

    # ---- 売上推移 ----
    st.markdown("<div class='mfc-tier'><span class='n'>Trend</span>売上の推移</div>",
                unsafe_allow_html=True)
    st.markdown("<div class='mfc-charthead'>月次総売上<span class='sub'>単位：万円</span></div>",
                unsafe_allow_html=True)
    st.altair_chart(chart_total_sales(p), width="stretch")

    st.markdown("<div class='mfc-charthead'>保険／自費／物販の内訳"
                "<span class='sub'>積み上げ・単位：万円</span></div>", unsafe_allow_html=True)
    st.altair_chart(chart_breakdown(p), width="stretch")

    # ---- 来院・患者 ----
    st.markdown("<div class='mfc-tier'><span class='n'>Visits</span>来院・患者の推移</div>",
                unsafe_allow_html=True)
    st.markdown("<div class='mfc-charthead'>総患者数・総来院回数・初診件数"
                "<span class='sub'>指標ごとに縦軸は独立</span></div>", unsafe_allow_html=True)
    st.altair_chart(chart_visits(p), width="stretch")

    # ---- 月次実績テーブル ----
    st.markdown("<div class='mfc-tier'><span class='n'>Table</span>月次実績</div>",
                unsafe_allow_html=True)
    show = p[TABLE_COLS].sort_values("年月", ascending=False).reset_index(drop=True)
    st.dataframe(show, width="stretch", hide_index=True, height=380)

    csv_bytes = show.to_csv(index=False).encode("utf-8-sig")
    st.download_button("この期間の実績をCSVでダウンロード", data=csv_bytes,
                       file_name=f"mdc_monthly_actuals_{a_lo}_{a_hi}.csv",
                       mime="text/csv", width="stretch")

    st.markdown(
        "<div class='mfc-note'>表示値はレセコン締め後の<b>確定実績</b>です（予測値ではありません）。"
        "当月は確定していないため含まれません。当月の見込みは「今月の予測」画面を参照してください。<br>"
        "本データは月次に集計済みで、<b>患者番号・患者名・電話番号・住所などの個人情報は一切含みません</b>。"
        "総患者数は月内のユニーク人数のカウント値です。</div>", unsafe_allow_html=True)

    if meta.get("生成日時"):
        st.caption(f"集計データ生成日時：{meta.get('生成日時')}"
                   f"｜収録 {meta.get('収録開始年月')} 〜 {meta.get('収録終了年月')}"
                   f"（{meta.get('収録月数')}か月）")


# ======================================================================
# 売上ポートフォリオ
#   data/history/portfolio_monthly.csv（月次×4分類の集計済み金額）だけを読む。
# ======================================================================
@st.cache_data(show_spinner=False)
def _load_portfolio(_mtime):
    import pandas as pd
    df = pd.read_csv(hist_path(F_PORTFOLIO), encoding="utf-8-sig")
    return df.sort_values(["年月", "分類コード"]).reset_index(drop=True)


def read_portfolio():
    p = hist_path(F_PORTFOLIO)
    if not os.path.isfile(p):
        return None
    try:
        return _load_portfolio(os.path.getmtime(p))
    except Exception:
        return None


def pf_pivot(df):
    """年月×表示分類名 の売上金額テーブル。"""
    p = df.pivot(index="年月", columns="表示分類名", values="売上金額")
    return p.reindex(columns=PF_LABELS).fillna(0)


def pf_cv(wide):
    """月次変動係数（標準偏差 / 平均 × 100）。2か月以下では算出しない。"""
    if len(wide) < 3:
        return None
    return (wide.std() / wide.mean() * 100)


def chart_pf_stack(wide):
    """分類別の積み上げ売上推移。ストック型を最下段に固定。"""
    import pandas as pd
    import altair as alt
    d = wide.reset_index()
    d["月"] = _ymdate(d["年月"])
    long = d.melt(id_vars="月", value_vars=PF_LABELS, var_name="分類", value_name="売上")
    long["売上"] = long["売上"] / 1e4
    long["順"] = long["分類"].map({n: o for _, n, _, o in PF_BUCKETS})
    ch = alt.Chart(long).mark_bar().encode(
        x=alt.X("月:T", axis=alt.Axis(format="%Y-%m", title=None, labelAngle=-55)),
        y=alt.Y("売上:Q", title=None, stack="zero"),
        color=alt.Color("分類:N", sort=PF_LABELS,
                        scale=alt.Scale(domain=PF_LABELS, range=PF_COLORS),
                        legend=alt.Legend(orient="top", title=None, direction="horizontal")),
        order=alt.Order("順:Q", sort="descending"),
        tooltip=[alt.Tooltip("月:T", title="年月", format="%Y-%m"),
                 alt.Tooltip("分類:N"), alt.Tooltip("売上:Q", title="売上(万円)", format=",.0f")])
    return (ch.properties(height=280).configure_view(strokeWidth=0).configure_axis(**AX))


def chart_pf_donut(shares, center_label, center_value):
    """選択期間の構成比（ドーナツ）。中央に結論の数値を置く。"""
    import pandas as pd
    import altair as alt
    d = pd.DataFrame({"分類": shares.index, "構成比": shares.values})
    arc = alt.Chart(d).mark_arc(innerRadius=76, outerRadius=112, stroke="#fff",
                                strokeWidth=2).encode(
        theta=alt.Theta("構成比:Q", stack=True),
        color=alt.Color("分類:N", sort=PF_LABELS,
                        scale=alt.Scale(domain=PF_LABELS, range=PF_COLORS), legend=None),
        order=alt.Order("構成比:Q", sort="descending"),
        tooltip=[alt.Tooltip("分類:N"), alt.Tooltip("構成比:Q", title="構成比(%)", format=".1f")])
    big = alt.Chart(pd.DataFrame({"t": [center_value]})).mark_text(
        dy=-6, fontSize=32, fontWeight="bold", color="#0B1F3A").encode(text="t:N")
    cap = alt.Chart(pd.DataFrame({"t": [center_label]})).mark_text(
        dy=22, fontSize=11.5, fontWeight="bold", color="#8A94A3").encode(text="t:N")
    return (alt.layer(arc, big, cap).properties(height=262)
            .configure_view(strokeWidth=0))


def chart_pf_matrix(shares, cvs, amounts):
    """安定性マトリクス。横軸=構成比、縦軸=月次変動係数。この画面の主役。"""
    import pandas as pd
    import altair as alt
    d = pd.DataFrame({"分類": shares.index, "構成比": shares.values,
                      "変動係数": [cvs[k] for k in shares.index],
                      "売上": [amounts[k] for k in shares.index]})
    # 軸の上限に余裕を持たせ、円の上に置くラベルが枠外へ切れないようにする。
    xmax = max(58.0, float(d["構成比"].max()) * 1.28)
    ymax = max(55.0, float(d["変動係数"].max()) * 1.32)

    base = alt.Chart(d)
    xenc = alt.X("構成比:Q", title="売上構成比（％）　→　大きいほど売上に効く",
                 scale=alt.Scale(domain=[0, xmax], nice=False))
    yenc = alt.Y("変動係数:Q", title="月次変動係数（％）　→　大きいほど不安定",
                 scale=alt.Scale(domain=[0, ymax], nice=False))
    # 平均線で4象限に区切る（左下＝大きく安定、右上＝大きく不安定）
    hx = alt.Chart(pd.DataFrame({"v": [float(d["構成比"].mean())]})).mark_rule(
        color="#E3E7EE", strokeDash=[4, 4]).encode(x="v:Q")
    hy = alt.Chart(pd.DataFrame({"v": [float(d["変動係数"].mean())]})).mark_rule(
        color="#E3E7EE", strokeDash=[4, 4]).encode(y="v:Q")
    pts = base.mark_circle(opacity=.88, stroke="#fff", strokeWidth=2).encode(
        x=xenc, y=yenc,
        size=alt.Size("売上:Q", scale=alt.Scale(range=[420, 2600]), legend=None),
        color=alt.Color("分類:N", sort=PF_LABELS,
                        scale=alt.Scale(domain=PF_LABELS, range=PF_COLORS), legend=None),
        tooltip=[alt.Tooltip("分類:N"),
                 alt.Tooltip("構成比:Q", title="構成比(%)", format=".1f"),
                 alt.Tooltip("変動係数:Q", title="変動係数(%)", format=".1f"),
                 alt.Tooltip("売上:Q", title="売上(円)", format=",.0f")])
    # dx / dy は mark のプロパティ。encode のチャネルではない。
    name = base.mark_text(fontSize=12.5, fontWeight="bold", color="#0B1F3A", dy=-36).encode(
        x=xenc, y=yenc, text="分類:N")
    val = base.mark_text(fontSize=11, color="#8A94A3", dy=-21).encode(
        x=xenc, y=yenc, text=alt.Text("変動係数:Q", format=".1f"))
    return (alt.layer(hx, hy, pts, name, val).properties(height=380)
            .configure_view(strokeWidth=0)
            .configure_axis(grid=True, gridColor="#F1F3F6", domainColor="#E8EBF1",
                            tickColor="#E8EBF1", labelColor="#8A94A3", labelFontSize=11.5,
                            titleColor="#8A94A3", titleFontSize=11.5, titleFontWeight="normal"))


# ======================================================================
# 売上ポートフォリオ画面 専用CSS
#   この画面を描画するときだけ注入する。他ページには一切適用されない
#   （Streamlit は1リクエストで1ページしか描画しないため）。
# ======================================================================
PF_CSS = """
<style>
/* ---- 余白の基準を締める ---- */
.block-container{padding-top:1.9rem !important;padding-bottom:3rem;}
[data-testid="stVerticalBlock"]{gap:.62rem;}
.mfc-title{font-size:33px;margin:0 0 5px;letter-spacing:-.6px;}
.mfc-sub{font-size:13.5px;line-height:1.6;max-width:700px;margin:0 0 6px;}
[data-testid="stRadio"]{margin:10px 0 10px !important;padding:10px 16px 8px !important;}
.mdc-navnote{margin:-4px 2px 12px !important;}

/* ---- セクション見出しを小さく、間隔を詰める ---- */
.mfc-tier{margin:26px 0 10px;font-size:21px;letter-spacing:-.3px;}
.mfc-tier .n{font-size:10px;letter-spacing:2.2px;margin-bottom:5px;}

/* ---- Streamlit の枠付きコンテナを「白カード」にする ---- */
[data-testid="stVerticalBlockBorderWrapper"]{
  background:var(--card);border:1px solid var(--line);border-radius:16px;
  box-shadow:var(--shadow);padding:15px 18px 11px;
}
[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stVerticalBlock"]{gap:.35rem;}

/* ---- セレクタの標準感を減らす ---- */
[data-testid="stSelectbox"]{margin-bottom:0;}
[data-testid="stSelectbox"] label{padding-bottom:0 !important;margin-bottom:2px !important;}
[data-testid="stSelectbox"] label p{
  font-size:10px !important;font-weight:800 !important;letter-spacing:1.3px;
  color:var(--gold) !important;text-transform:uppercase;margin:0 !important;
}
[data-testid="stSelectbox"] div[data-baseweb="select"]>div{
  border-radius:10px;border-color:#E3E7EE;min-height:38px;background:#FBFCFD;
  font-weight:700;color:var(--navy);
}
[data-testid="stSelectbox"] div[data-baseweb="select"]>div:hover{border-color:var(--gold2);}

/* ---- 期間カード ---- */
.pf-pcard-h{font-size:12.5px;font-weight:800;color:var(--navy);margin:0 0 8px;letter-spacing:.2px;}
.pf-pcard-h span{font-size:10px;font-weight:800;letter-spacing:2px;color:var(--gold);
  text-transform:uppercase;margin-right:10px;}
.pf-pnote{font-size:11px;color:var(--faint);margin:9px 2px 0;line-height:1.45;}
.pf-pmeta{font-size:12.5px;color:var(--muted);margin:8px 2px 2px;padding-top:9px;
  border-top:1px dashed #E8EBF1;line-height:1.5;}
.pf-pmeta b{color:var(--navy);font-weight:800;}

/* ---- ヒーロー（結論） ---- */
.pf-hero{display:grid;grid-template-columns:1.35fr 1fr;gap:30px;align-items:center;
  background:radial-gradient(120% 150% at 90% 4%,rgba(203,169,104,.17),transparent 44%),
    linear-gradient(155deg,#0a1b31 0%,#122f57 62%,#16386c 100%);
  border-radius:18px;padding:26px 32px;color:#fff;margin:16px 0 6px;
  box-shadow:0 22px 50px -26px rgba(11,31,58,.66);}
.pf-hero .k{font-size:10px;font-weight:800;letter-spacing:2.4px;color:var(--gold2);
  text-transform:uppercase;margin-bottom:9px;}
.pf-hero .big{font-size:58px;font-weight:800;line-height:.98;letter-spacing:-2px;
  font-variant-numeric:tabular-nums;}
.pf-hero .big span{font-size:24px;margin-left:5px;color:#c7d2e0;font-weight:700;letter-spacing:0;}
.pf-hero .cap{font-size:17px;font-weight:800;margin:9px 0 8px;letter-spacing:-.2px;}
.pf-hero .sub{font-size:12.5px;color:#a9b5c6;line-height:1.6;max-width:380px;}
.pf-hero .r{display:grid;gap:13px;border-left:1px solid rgba(255,255,255,.13);padding-left:28px;}
.pf-hero .it{font-size:11.5px;color:#a9b5c6;line-height:1.3;}
.pf-hero .it b{display:block;font-size:22px;color:#fff;font-weight:800;margin-top:2px;
  letter-spacing:-.4px;font-variant-numeric:tabular-nums;}
.pf-lead{font-size:14px;color:var(--ink);font-weight:600;line-height:1.6;
  margin:12px 2px 2px;padding-left:12px;border-left:3px solid var(--gold);}
.pf-lead b{color:var(--navy);font-weight:800;}

/* ---- KPIカード ---- */
.pf-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:13px;margin-top:14px;}
.pf-card{background:var(--card);border:1px solid var(--line);border-radius:13px;
  padding:14px 15px 12px;box-shadow:var(--shadow);display:flex;flex-direction:column;
  justify-content:space-between;min-height:104px;border-top:2px solid transparent;}
.pf-card .lb{font-size:11.5px;font-weight:800;color:var(--muted);letter-spacing:.2px;}
.pf-card .val{font-size:31px;font-weight:800;color:var(--navy);line-height:1;
  margin:9px 0 7px;letter-spacing:-.9px;font-variant-numeric:tabular-nums;}
.pf-card .val u{text-decoration:none;font-size:12.5px;color:var(--faint);margin-left:3px;
  font-weight:700;letter-spacing:0;}
.pf-card .sub{font-size:11px;color:var(--faint);line-height:1.4;}
.pf-card .sub b{color:var(--navy);font-weight:700;}
.pf-card.sm{min-height:92px;padding:12px 14px 10px;}
.pf-card.sm .val{font-size:25px;margin:7px 0 6px;}
.pf-card.a-navy{border-top-color:var(--navy);}
.pf-card.a-blue{border-top-color:var(--blue);}
.pf-card.a-gold{border-top-color:var(--gold);}
.pf-card.a-gray{border-top-color:#CFD6E1;}
.pf-card.a-green{border-top-color:var(--green);}

/* ---- グラフカードの見出し ---- */
.pf-ch{margin:0 0 2px;}
.pf-ch .t{font-size:14.5px;font-weight:800;color:var(--navy);letter-spacing:-.1px;}
.pf-ch .s{font-size:11.5px;color:var(--faint);margin-top:2px;line-height:1.45;}
[data-testid="stVegaLiteChart"]{background:transparent;border:none;box-shadow:none;
  padding:2px 0 0;}

/* ---- 構成比チップ ---- */
.pf-chip{display:flex;align-items:center;justify-content:space-between;
  border:1px solid var(--line);border-radius:11px;padding:10px 13px;margin-bottom:9px;
  background:#FBFCFD;}
.pf-chip .n{font-size:12.5px;font-weight:700;color:var(--navy);display:flex;align-items:center;}
.pf-chip .n i{width:9px;height:9px;border-radius:50%;margin-right:9px;display:inline-block;}
.pf-chip .v{text-align:right;}
.pf-chip .v b{font-size:17px;font-weight:800;color:var(--navy);font-variant-numeric:tabular-nums;}
.pf-chip .v small{display:block;font-size:11px;color:var(--faint);font-weight:600;}

/* ---- 当月見込み: 警告帯・見込みバッジ ---- */
.pf-warn{background:#FBF3E4;border:1px solid #ECD9B0;border-left:4px solid var(--gold);
  border-radius:12px;padding:13px 18px;margin:14px 0 4px;font-size:13.5px;color:#7A5A16;
  font-weight:600;line-height:1.6;}
.pf-warn b{color:#5C4310;font-weight:800;}
.pf-est{display:inline-block;font-size:10px;font-weight:800;letter-spacing:1px;
  background:#F6EFDE;color:#8A6A24;border-radius:6px;padding:2px 8px;margin-left:8px;
  vertical-align:middle;}
.pf-hero.est{background:radial-gradient(120% 150% at 90% 4%,rgba(203,169,104,.22),transparent 44%),
  linear-gradient(155deg,#14243a 0%,#1b3557 62%,#213f6f 100%);}
.pf-hero .rng{font-size:12px;color:#c7d2e0;margin-top:8px;line-height:1.5;}
.pf-hero .rng b{color:#e0c894;font-weight:800;}
.pf-cmp{font-size:13px;color:var(--muted);line-height:1.7;margin:6px 2px 0;
  padding-top:10px;border-top:1px dashed #E8EBF1;}
.pf-cmp b{color:var(--navy);font-weight:800;}

/* ---- 安定性マトリクスの解説 ---- */
.pf-mx{font-size:13px;color:var(--muted);line-height:1.65;margin:6px 2px 0;
  padding-top:10px;border-top:1px dashed #E8EBF1;}
.pf-mx b{color:var(--navy);font-weight:800;}

/* ---- テーブル・ボタン ---- */
[data-testid="stDataFrame"]{border-radius:13px;overflow:hidden;border:1px solid var(--line);}
[data-testid="stDownloadButton"] button{border-radius:10px;border:1px solid var(--line);
  font-weight:700;color:var(--navy);background:#FBFCFD;}
[data-testid="stDownloadButton"] button:hover{border-color:var(--gold2);color:var(--gold);}
[data-testid="stAlert"]{border-radius:12px;font-size:13px;}
.mfc-note{font-size:12.5px;line-height:1.7;margin-top:14px;}

@media (max-width:900px){
  .pf-hero{grid-template-columns:1fr;gap:20px;padding:22px 22px;}
  .pf-hero .big{font-size:46px;}
  .pf-hero .r{border-left:none;border-top:1px solid rgba(255,255,255,.13);
    padding-left:0;padding-top:16px;grid-template-columns:1fr 1fr;}
  .pf-grid{grid-template-columns:1fr 1fr;}
}
</style>
"""

PF_MODES = ["プリセット", "単月", "四半期", "任意期間"]
PF_PRESETS = ["最新確定月", "直近3か月", "直近6か月", "直近12か月", "直近24か月",
              "今年度累計", "昨年度", "全期間"]
PF_QUARTERS = ["第1四半期（4月〜6月）", "第2四半期（7月〜9月）",
               "第3四半期（10月〜12月）", "第4四半期（1月〜3月）"]
PF_CLOSED_NOTE = ("当月の最新状況は『今月の予測』画面で確認してください。"
                  "この画面は確定月のみを対象にしています。")


def ym_jp(ym):
    """'2026-06' -> '2026年6月'"""
    y, m = ym.split("-")
    return f"{y}年{int(m)}月"


def ym_range_jp(lo, hi):
    """'2026-04','2026-06' -> '2026年4月〜6月'（年をまたぐ場合は両方に年を付ける）"""
    if lo[:4] == hi[:4]:
        return f"{ym_jp(lo)}〜{int(hi[5:])}月"
    return f"{ym_jp(lo)}〜{ym_jp(hi)}"


def fiscal_years(months):
    """収録データに存在する年度を新しい順に返す。"""
    return sorted({fiscal_year_of(m) for m in months}, reverse=True)


def quarter_range(fy, q_index):
    """年度 fy の第 q_index+1 四半期の (開始年月, 終了年月)。年度は4月始まり。"""
    starts = [(fy, 4), (fy, 7), (fy, 10), (fy + 1, 1)]
    y, m = starts[q_index]
    return f"{y}-{m:02d}", f"{y}-{m + 2:02d}"


def _tail(months, n):
    return (months[-n] if len(months) >= n else months[0]), months[-1]


def pf_select_period(months):
    """期間選択UI。(開始年月, 終了年月, 表示ラベル) を返す。"""
    c0, c1, c2 = st.columns([1, 1.12, 1.12], gap="small")
    with c0:
        mode = st.selectbox("期間の選び方", PF_MODES, index=0, key="pf_mode")

    if mode == "プリセット":
        with c1:
            p = st.selectbox("プリセット", PF_PRESETS, index=3, key="pf_preset")
        latest_fy = fiscal_year_of(months[-1])
        if p == "最新確定月":
            lo = hi = months[-1]
            return lo, hi, f"最新確定月 {ym_jp(hi)}"
        if p.startswith("直近"):
            n = int(re.sub(r"\D", "", p))
            lo, hi = _tail(months, n)
            return lo, hi, f"{p}（{ym_range_jp(lo, hi)}）"
        if p == "今年度累計":
            lo, hi = fiscal_range(latest_fy)
            return lo, hi, f"{latest_fy}年度累計"
        if p == "昨年度":
            lo, hi = fiscal_range(latest_fy - 1)
            return lo, hi, f"{latest_fy - 1}年度"
        return months[0], months[-1], f"全期間（{ym_range_jp(months[0], months[-1])}）"

    if mode == "単月":
        with c1:
            m = st.selectbox("対象月", list(reversed(months)), index=0, key="pf_month")
        return m, m, f"単月 {ym_jp(m)}"

    if mode == "四半期":
        fys = fiscal_years(months)
        with c1:
            fy = st.selectbox("年度", fys, index=0, key="pf_fy",
                              format_func=lambda y: f"{y}年度")
        with c2:
            qi = PF_QUARTERS.index(st.selectbox("四半期", PF_QUARTERS, index=0, key="pf_quarter"))
        lo, hi = quarter_range(fy, qi)
        qname = PF_QUARTERS[qi].split("（")[0]
        return lo, hi, f"{fy}年度 {qname}（{ym_range_jp(lo, hi)}）"

    # 任意期間
    with c1:
        s = st.selectbox("開始年月", months, index=max(0, len(months) - 12), key="pf_from")
    with c2:
        e = st.selectbox("終了年月", months, index=len(months) - 1, key="pf_to")
    if s > e:
        s, e = e, s  # 逆順は自動で入れ替える
    return s, e, f"任意期間（{ym_range_jp(s, e)}）"


@st.cache_data(show_spinner=False)
def _load_pf_forecast(path, _mtime):
    return read_json(path)


def read_pf_forecast():
    """最新スナップショットの portfolio_forecast.json を読む。無ければ None。"""
    for month in list_months():
        latest = read_json(os.path.join(DATA, month, F_LATEST)) or {}
        snap = os.path.basename(str(latest.get("latest_snapshot_dir", "")).rstrip("/"))
        if not snap:
            continue
        p = os.path.join(DATA, month, "snapshots", snap, F_PF_FORECAST)
        if os.path.isfile(p):
            try:
                return _load_pf_forecast(p, os.path.getmtime(p))
            except Exception:
                return None
    return None


def chart_pf_compare(fc_share, act_share):
    """当月見込み vs 直近12か月確定実績の構成比を横棒で比較する。"""
    import pandas as pd
    import altair as alt
    rows = []
    for lb in PF_LABELS:
        rows.append({"分類": lb, "系列": "当月見込み", "構成比": fc_share[lb]})
        rows.append({"分類": lb, "系列": "直近12か月 確定実績", "構成比": act_share[lb]})
    d = pd.DataFrame(rows)
    ch = alt.Chart(d).mark_bar(cornerRadiusEnd=3, height=17).encode(
        y=alt.Y("分類:N", sort=PF_LABELS, title=None,
                axis=alt.Axis(labelFontSize=12.5, labelColor="#0B1F3A",
                              labelFontWeight="bold", labelPadding=8)),
        x=alt.X("構成比:Q", title="売上構成比（％）", scale=alt.Scale(domain=[0, 60])),
        yOffset=alt.YOffset("系列:N", sort=["当月見込み", "直近12か月 確定実績"]),
        color=alt.Color("系列:N", sort=["当月見込み", "直近12か月 確定実績"],
                        scale=alt.Scale(domain=["当月見込み", "直近12か月 確定実績"],
                                        range=["#B08A4E", "#0B1F3A"]),
                        legend=alt.Legend(orient="top", title=None, direction="horizontal")),
        tooltip=[alt.Tooltip("分類:N"), alt.Tooltip("系列:N"),
                 alt.Tooltip("構成比:Q", title="構成比(%)", format=".1f")])
    return (ch.properties(height=270).configure_view(strokeWidth=0).configure_axis(**AX))


def pf_card(lb, val, unit, sub, accent="a-gray", small=False):
    u = f"<u>{unit}</u>" if unit else ""
    return (f"<div class='pf-card {accent}{' sm' if small else ''}'>"
            f"<div class='lb'>{lb}</div>"
            f"<div class='val'>{val}{u}</div>"
            f"<div class='sub'>{sub}</div></div>")


def render_portfolio_forecast(fc, df):
    """当月見込み（推定値）。確定実績とは明確に分けて描画する。"""
    import pandas as pd

    as_of = fc.get("as_of_date", "—")
    total = int(fc["current_forecast_total"])
    amt = {b["表示分類名"]: int(b["売上見込み"]) for b in fc["buckets"]}
    share = {k: v / total * 100 for k, v in amt.items()}
    hv = fc["high_value_range"]

    # ---- A. 警告帯 ----
    st.markdown(
        f"<div class='pf-warn'>⚠ <b>これは確定実績ではありません。</b>"
        f"{as_of} 時点の実績・予約状況・過去傾向から算出した<b>当月見込み</b>です。"
        "分類別の金額は按分による推定であり、確定した内訳ではありません。"
        "月末後に確定実績と照合します。</div>", unsafe_allow_html=True)

    # ---- B. ヒーロー ----
    stock_pct = share["ストック型売上"]
    hv_pct = share["高単価型売上"]
    st.markdown(
        "<div class='pf-hero est'>"
        "<div class='l'>"
        f"<div class='k'>Forecast · as of {_html.escape(as_of)}</div>"
        f"<div class='big'>{stock_pct:.1f}<span>%</span></div>"
        "<div class='cap'>がストック型売上の見込み</div>"
        f"<div class='sub'>7月の基準予測 {manv(total)} 万円のうち、"
        f"{manv(amt['ストック型売上'])} 万円が継続管理と訪問・介護によるストック型の見込みです。</div>"
        "</div>"
        "<div class='r'>"
        f"<div class='it'>高単価型見込み<b>{manv(amt['高単価型売上'])}"
        "<span style='font-size:12px'> 万円</span></b></div>"
        f"<div class='it'>高単価依存度<b>{hv_pct:.1f}<span style='font-size:12px'> %</span></b></div>"
        f"<div class='rng'>高単価型 参考レンジ "
        f"<b>{manv(hv['参考下限'])} 〜 {manv(hv['参考上限'])} 万円</b><br>"
        f"（月次変動係数 {hv['使用した変動係数']}% による±1σ・確定値ではありません）</div>"
        "</div></div>", unsafe_allow_html=True)

    # ---- C. KPIカード ----
    row1 = "".join([
        pf_card("ストック型見込み", manv(amt["ストック型売上"]), "万円",
                f"構成比 <b>{share['ストック型売上']:.1f}%</b>", "a-navy"),
        pf_card("スポット型見込み", manv(amt["スポット型売上"]), "万円",
                f"構成比 <b>{share['スポット型売上']:.1f}%</b>", "a-blue"),
        pf_card("高単価型見込み", manv(amt["高単価型売上"]), "万円",
                f"構成比 <b>{share['高単価型売上']:.1f}%</b>", "a-gold"),
        pf_card("混合・未分類見込み", manv(amt["混合・未分類"]), "万円",
                f"構成比 <b>{share['混合・未分類']:.1f}%</b>", "a-gray"),
    ])
    row2 = "".join([
        pf_card("ストック比率", f"{stock_pct:.1f}", "%", "当月見込み", "a-green", small=True),
        pf_card("高単価依存度", f"{hv_pct:.1f}", "%", "当月見込み", "a-gold", small=True),
        pf_card("高単価型 参考レンジ", f"{manv(hv['参考下限'])}〜{manv(hv['参考上限'])}", "万円",
                f"変動係数 <b>{hv['使用した変動係数']}%</b>・確定値ではありません", "a-gold",
                small=True),
        pf_card("基準予測合計", manv(total), "万円",
                f"訪問・介護 <b>{manv(fc['visit_care_forecast_total'])}</b> 万円を含む",
                "a-navy", small=True),
    ])
    st.markdown(f"<div class='pf-grid'>{row1}</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='pf-grid'>{row2}</div>", unsafe_allow_html=True)

    # ---- D/E. 直近12か月 確定実績との比較 ----
    st.markdown("<div class='mfc-tier'><span class='n'>Compare</span>"
                "当月見込み と 直近12か月の確定実績</div>", unsafe_allow_html=True)
    wide = pf_pivot(df)
    l12 = wide.tail(12)
    a_amt = l12.sum()
    a_share = (a_amt / a_amt.sum() * 100).to_dict()

    with st.container(border=True):
        st.markdown("<div class='pf-ch'><div class='t'>分類別の構成比比較</div>"
                    f"<div class='s'>当月見込み（{as_of} 時点）と、"
                    f"直近12か月の確定実績（{l12.index[0]} 〜 {l12.index[-1]}）</div></div>",
                    unsafe_allow_html=True)
        st.altair_chart(chart_pf_compare(share, a_share), width="stretch")

        rows = []
        for lb in PF_LABELS:
            d = share[lb] - a_share[lb]
            sign = "＋" if d >= 0 else "▲"
            rows.append(f"<b>{lb}</b>：当月見込み {share[lb]:.1f}% ／ "
                        f"直近12か月 {a_share[lb]:.1f}%（{sign}{abs(d):.1f}pt）")
        st.markdown(f"<div class='pf-cmp'>{'<br>'.join(rows)}</div>", unsafe_allow_html=True)

    # ---- 明細テーブル ----
    st.markdown("<div class='mfc-tier'><span class='n'>Table</span>当月見込みの内訳</div>",
                unsafe_allow_html=True)
    tbl = pd.DataFrame([{
        "分類": b["表示分類名"], "売上見込み(円)": int(b["売上見込み"]),
        "構成比(%)": b["構成比"], "分類方法": b["分類方法"],
        "直近12か月 実績構成比(%)": round(a_share[b["表示分類名"]], 1),
    } for b in fc["buckets"]])
    with st.container(border=True):
        st.dataframe(tbl, width="stretch", hide_index=True)

    # ---- F. 注記 ----
    ap = fc.get("按分方式", {}) or {}
    learned = ap.get("1予約あたり売上", {}) or {}
    lt = "／".join(f"{k} {v:,}円" for k, v in learned.items())
    st.markdown(
        "<div class='mfc-note'><b>これは当月見込みです。</b>"
        f"{as_of} 時点の確定実績・登録済み予約・過去傾向から算出した推定値であり、"
        "確定値ではありません。月末後に確定実績と照合します。<br>"
        f"<b>分類方法</b>　{ap.get('名称', '想定売上加重按分')}。"
        f"予約1件あたりの想定売上（{lt}）で加重して分解しています。"
        f"予約を伴わない来院と突合の残差として {manv(ap.get('残差先取り額', 0))} 万円を先取りし、"
        "残りを登録済み予約から按分しました。キャンセル済みの予約は按分から除外しています。<br>"
        f"<b>訪問・介護</b>　{manv(fc['visit_care_forecast_total'])} 万円はストック型に含めています。"
        "反復性が高く、確定実績の売上ポートフォリオと同じ定義です。<br>"
        "<b>高単価型の参考レンジ</b>　確定実績から求めた月次変動係数による±1σの目安であり、"
        "予測区間ではありません。高単価型は月ごとの振れが大きいため、点推定だけでは誤解を招きます。<br>"
        "<b>合計</b>　4分類の合計は基準予測合計と円単位で一致します。<br>"
        "<b>個人情報</b>　本データは集計済みで、個人または担当者を識別しうる項目は一切含みません。"
        "</div>", unsafe_allow_html=True)

    st.caption(f"生成日時：{fc.get('generated_at', '—')}"
               f"｜対象月 {fc.get('target_month', '—')}"
               f"｜確定実績の反映 {fc.get('actual_data_through', '—')} まで")


def render_portfolio(nav=None):
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(PF_CSS, unsafe_allow_html=True)
    df = read_portfolio()

    st.markdown(
        "<div class='mfc-title'>MDC Forecast Console"
        "<span class='mfc-vchip'>Portfolio</span></div>"
        "<div class='mfc-sub'>この医院の売上が、安定収益なのか、都度獲得型なのか、"
        "高単価に依存しているのかを見る画面です。</div>",
        unsafe_allow_html=True)

    if nav:
        nav()

    if df is None or df.empty:
        st.warning("売上ポートフォリオのデータがありません。"
                   "ローカルで scripts/build_portfolio_aggregates.py を実行し、"
                   "data/history/portfolio_monthly.csv を配置してください。")
        return

    # ---- データ種別の切替（確定実績 / 当月見込み） ----
    fc = read_pf_forecast()
    with st.container(border=True):
        st.markdown("<div class='pf-pcard-h'><span>Data</span>データ種別</div>",
                    unsafe_allow_html=True)
        opts = [PF_DATA_ACTUAL] + ([PF_DATA_FORECAST] if fc else [])
        dtype = st.selectbox("データ種別", opts, index=0, key="pf_datatype",
                             label_visibility="collapsed",
                             help="「確定実績」はレセコン締め後の確定値、"
                                  "「当月見込み」は当月の推定値です。")
        if fc:
            st.markdown(
                f"<div class='pf-pnote'>確定実績は 〜"
                f"{ym_jp(list(pf_pivot(df).index)[-1])} ／ "
                f"当月見込みは {fc.get('target_month')}（as_of {fc.get('as_of_date')}）"
                "<span class='pf-est'>見込</span></div>", unsafe_allow_html=True)
        else:
            st.markdown("<div class='pf-pnote'>当月見込みのデータがまだありません。"
                        "確定実績のみ表示します。</div>", unsafe_allow_html=True)

    if dtype == PF_DATA_FORECAST and fc:
        render_portfolio_forecast(fc, df)
        return

    meta = read_json(hist_path(F_PORTFOLIO_META)) or {}
    wide_all = pf_pivot(df)
    months = list(wide_all.index)

    # ---- 期間選択（1枚のカードにまとめる） ----
    with st.container(border=True):
        st.markdown("<div class='pf-pcard-h'><span>Period</span>期間を選ぶ</div>",
                    unsafe_allow_html=True)
        lo, hi, plabel = pf_select_period(months)
        st.markdown(f"<div class='pf-pnote'>{_html.escape(PF_CLOSED_NOTE)}</div>",
                    unsafe_allow_html=True)

        wide = wide_all.loc[(wide_all.index >= lo) & (wide_all.index <= hi)]
        if wide.empty:
            st.warning(f"選択した期間（{ym_jp(lo)}〜{ym_jp(hi)}）に該当する確定月がありません。"
                       f"収録範囲は {ym_jp(months[0])}〜{ym_jp(months[-1])} です。"
                       "まだ締めが終わっていない期間か、収録前の期間です。")
            return

        a_lo, a_hi = wide.index[0], wide.index[-1]
        partial = (a_lo != lo) or (a_hi != hi)
        st.markdown(f"<div class='pf-pmeta'>対象期間 <b>{plabel}</b>"
                    f"　·　確定月 {len(wide)}か月（{a_lo} 〜 {a_hi}）"
                    f"　·　収録範囲 {months[0]} 〜 {months[-1]}</div>",
                    unsafe_allow_html=True)
        if partial:
            st.info(f"選択した期間のうち、確定している {len(wide)} か月"
                    f"（{ym_jp(a_lo)}〜{ym_jp(a_hi)}）だけを集計しています。")

    amounts = wide.sum()
    total = float(amounts.sum())
    shares = amounts / total * 100
    cvs = pf_cv(wide)

    # ---- A. 結論（ヒーロー） ----
    stock_pct = shares["ストック型売上"]
    hv_pct = shares["高単価型売上"]
    hv_m = wide["高単価型売上"]
    # 振れ幅は2か月以上ないと意味を持たない（単月では常に1.00倍になる）
    swing = (hv_m.max() / hv_m.min()) if (len(wide) >= 2 and hv_m.min() > 0) else None
    driver = cvs.drop("混合・未分類").idxmax() if cvs is not None else "高単価型売上"

    if len(wide) == 1:
        lead = (f"{ym_jp(a_hi)}は、売上の <b>{stock_pct:.1f}%</b> がストック型、"
                f"高単価型が <b>{hv_pct:.1f}%</b> でした。")
    elif driver != "高単価型売上":
        lead = (f"売上の <b>{stock_pct:.1f}%</b> がストック型。"
                f"この期間は <b>{driver}</b> が最も大きく振れています。")
    else:
        lead = (f"売上の <b>{stock_pct:.1f}%</b> がストック型。"
                f"高単価型が <b>{hv_pct:.1f}%</b> を占め、月次変動を押し上げる構造です。")

    st.markdown(
        "<div class='pf-hero'>"
        "<div class='l'>"
        "<div class='k'>Conclusion</div>"
        f"<div class='big'>{stock_pct:.1f}<span>%</span></div>"
        "<div class='cap'>がストック型売上</div>"
        "<div class='sub'>継続管理と訪問・介護による反復収益。"
        "この層が厚いほど、売上の土台は崩れにくくなります。</div>"
        "</div>"
        "<div class='r'>"
        f"<div class='it'>期間の総売上<b>{manv(total)}<span style='font-size:12px'> 万円</span></b></div>"
        f"<div class='it'>月あたり平均<b>{manv(total / len(wide))}"
        "<span style='font-size:12px'> 万円</span></b></div>"
        f"<div class='it'>高単価依存度<b>{hv_pct:.1f}"
        "<span style='font-size:12px'> %</span></b></div>"
        "</div></div>"
        f"<div class='pf-lead'>{lead}</div>", unsafe_allow_html=True)

    # ---- B. KPIカード ----
    row1 = "".join([
        pf_card("ストック型売上", manv(amounts["ストック型売上"]), "万円",
                f"構成比 <b>{shares['ストック型売上']:.1f}%</b>", "a-navy"),
        pf_card("スポット型売上", manv(amounts["スポット型売上"]), "万円",
                f"構成比 <b>{shares['スポット型売上']:.1f}%</b>", "a-blue"),
        pf_card("高単価型売上", manv(amounts["高単価型売上"]), "万円",
                f"構成比 <b>{shares['高単価型売上']:.1f}%</b>", "a-gold"),
        pf_card("混合・未分類", manv(amounts["混合・未分類"]), "万円",
                f"構成比 <b>{shares['混合・未分類']:.1f}%</b>", "a-gray"),
    ])
    cv_na = "変動係数は3か月以上で算出します"
    row2 = "".join([
        pf_card("ストック比率", f"{stock_pct:.1f}", "%",
                f"月次変動係数 <b>{cvs['ストック型売上']:.1f}%</b>" if cvs is not None else cv_na,
                "a-green", small=True),
        pf_card("高単価依存度", f"{hv_pct:.1f}", "%",
                f"月次変動係数 <b>{cvs['高単価型売上']:.1f}%</b>" if cvs is not None else cv_na,
                "a-gold", small=True),
        pf_card("高単価型の振れ幅", f"{swing:.2f}" if swing else "—", "倍",
                (f"最小 <b>{manv(hv_m.min())}</b> 〜 最大 <b>{manv(hv_m.max())}</b> 万円"
                 if swing else "2か月以上の期間で算出します"), "a-gold", small=True),
        pf_card("未分類率", f"{shares['混合・未分類']:.1f}", "%",
                "分類辞書で判定できない売上・予約外来院・残差", "a-gray", small=True),
    ])
    st.markdown(f"<div class='pf-grid'>{row1}</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='pf-grid'>{row2}</div>", unsafe_allow_html=True)

    # ---- C. 月次推移（直近24か月） ----
    st.markdown("<div class='mfc-tier'><span class='n'>Trend</span>売上構造の推移</div>",
                unsafe_allow_html=True)
    trend = wide_all.tail(24)
    with st.container(border=True):
        st.markdown("<div class='pf-ch'><div class='t'>分類別の積み上げ売上</div>"
                    f"<div class='s'>直近24か月（{trend.index[0]} 〜 {trend.index[-1]}）"
                    "・ストック型が最下段・単位：万円</div></div>", unsafe_allow_html=True)
        st.altair_chart(chart_pf_stack(trend), width="stretch")

    # ---- D. 構成比 ----
    st.markdown("<div class='mfc-tier'><span class='n'>Mix</span>選択期間の構成比</div>",
                unsafe_allow_html=True)
    with st.container(border=True):
        st.markdown("<div class='pf-ch'><div class='t'>分類別の構成比</div>"
                    f"<div class='s'>{a_lo} 〜 {a_hi}（{len(wide)}か月）</div></div>",
                    unsafe_allow_html=True)
        c1, c2 = st.columns([1.1, 1], gap="medium")
        with c1:
            st.altair_chart(chart_pf_donut(shares, "ストック型売上", f"{stock_pct:.1f}%"),
                            width="stretch")
        with c2:
            chips = "".join(
                f"<div class='pf-chip'><div class='n'>"
                f"<i style='background:{col}'></i>{lb}</div>"
                f"<div class='v'><b>{shares[lb]:.1f}%</b>"
                f"<small>{manv(amounts[lb])}万円</small></div></div>"
                for (_, lb, col, _) in PF_BUCKETS)
            st.markdown(f"<div style='margin-top:22px;'>{chips}</div>", unsafe_allow_html=True)

    # ---- E. 安定性マトリクス（主役） ----
    st.markdown("<div class='mfc-tier'><span class='n'>Stability</span>"
                "安定性マトリクス｜収益の質</div>", unsafe_allow_html=True)
    if cvs is None:
        st.info(f"変動係数の算出には3か月以上が必要です（現在 {len(wide)} か月）。"
                "期間を広げると安定性マトリクスが表示されます。")
    else:
        with st.container(border=True):
            st.markdown("<div class='pf-ch'><div class='t'>構成比 × 月次変動係数</div>"
                        "<div class='s'>円の大きさは売上金額。破線は4分類の平均。"
                        "左下＝大きく安定、右上＝大きく不安定。</div></div>",
                        unsafe_allow_html=True)
            st.altair_chart(chart_pf_matrix(shares, cvs, amounts), width="stretch")
            ratio = cvs["高単価型売上"] / max(cvs["ストック型売上"], 0.1)
            st.markdown(
                f"<div class='pf-mx'><b>ストック型は安定した土台、"
                f"高単価型は売上を押し上げるが月次変動も大きい。</b><br>"
                f"ストック型は構成比 <b>{stock_pct:.1f}%</b> に対し変動係数 "
                f"<b>{cvs['ストック型売上']:.1f}%</b>。高単価型は構成比 <b>{hv_pct:.1f}%</b> に対し "
                f"<b>{cvs['高単価型売上']:.1f}%</b> で、<b>{ratio:.1f}倍</b> 振れます。"
                "土台をストック型が支え、振れ幅を高単価型が生む構造です。</div>",
                unsafe_allow_html=True)

    # ---- F. 月次テーブル ----
    st.markdown("<div class='mfc-tier'><span class='n'>Table</span>月次の分類別実績</div>",
                unsafe_allow_html=True)
    import pandas as pd
    sub = df[(df["年月"] >= a_lo) & (df["年月"] <= a_hi)]
    amt = sub.pivot(index="年月", columns="表示分類名", values="売上金額").reindex(columns=PF_LABELS)
    shr = sub.pivot(index="年月", columns="表示分類名", values="売上構成比").reindex(columns=PF_LABELS)
    show = pd.concat([amt.add_suffix("(円)"), shr.add_suffix("(%)")], axis=1)
    show.insert(0, "月間総売上", sub.groupby("年月")["月間総売上"].first())
    show = show.sort_index(ascending=False).reset_index()
    with st.container(border=True):
        st.dataframe(show, width="stretch", hide_index=True, height=360)
        st.download_button("この期間のポートフォリオをCSVでダウンロード",
                           data=sub.to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"mdc_portfolio_{a_lo}_{a_hi}.csv",
                           mime="text/csv", width="stretch")

    # ---- 注記 ----
    ap = meta.get("按分方式", {}) or {}
    learned = ap.get("学習値", {}) or {}
    learned_txt = "／".join(f"{k} {v:,}円" for k, v in learned.items())
    st.markdown(
        "<div class='mfc-note'><b>分類の定義</b>　"
        "ストック型＝継続管理型（検診・メンテ等の定期来院）＋訪問診療・介護。"
        "スポット型＝都度治療型。高単価型＝補綴・自費中心。"
        "混合・未分類＝分類辞書で判定できないもの、予約を伴わない来院、突合の残差。<br>"
        f"<b>按分方法</b>　同じ来院日に複数の分類が混在する場合、"
        f"{ap.get('名称', '想定売上加重按分')}で分解しています"
        + (f"（1予約あたり売上の学習値：{learned_txt}）。" if learned_txt else "。") +
        "分類ごとの金額は<b>推定値</b>であり、確定した内訳ではありません。"
        "各月の分類合計はレセコンの月間総売上と一致します。<br>"
        f"<b>対象期間</b>　{PF_CLOSED_NOTE}<br>"
        "<b>個人情報</b>　本データは月次に集計済みで、個人または担当者を識別しうる項目は"
        "一切含みません。</div>", unsafe_allow_html=True)

    if meta.get("生成日時"):
        st.caption(f"集計データ生成日時：{meta.get('生成日時')}"
                   f"｜収録 {meta.get('収録開始年月')} 〜 {meta.get('収録終了年月')}"
                   f"（{meta.get('収録月数')}か月）")


# ======================================================================
# エントリポイント
# ======================================================================
if check_password():
    months = list_months()
    target = None
    snap = None

    # 表示中のページは session_state を唯一の正とする。ウィジェット本体は
    # 本文上部（page_nav）に1つだけ置く。サイドバーは折りたたまれて見えない
    # ことがあるため、切替の入口をサイドバーに依存させない。
    if "nav_page" not in st.session_state:
        st.session_state["nav_page"] = PAGE_FORECAST
    page = st.session_state["nav_page"]

    with st.sidebar:
        st.markdown("### MDC Forecast Console")
        st.caption(f"表示中：{page}")

        if page == PAGE_FORECAST:
            st.caption("日次ローリング予測・閲覧専用")
            if months:
                labels = [ym_label(m) for m in months]
                sel_m = st.selectbox("対象月", labels, index=0)
                target = months[labels.index(sel_m)]

            if target:
                latest = read_json(os.path.join(DATA, target, F_LATEST)) or {}
                snaps = list_snapshots(target)
                if snaps:
                    default_dir = os.path.basename(str(latest.get("latest_snapshot_dir", "")).rstrip("/"))
                    idx = snaps.index(default_dir) if default_dir in snaps else 0
                    slabels = [asof_label(s) for s in snaps]
                    sel_s = st.selectbox("予測基準日（as_of）", slabels, index=idx,
                                         help="過去の予測基準日を選ぶと、その時点の予測を確認できます。")
                    snap = snaps[slabels.index(sel_s)]
                    if latest.get("latest_as_of_date"):
                        st.caption(f"最新基準日：{latest.get('latest_as_of_date')}")
                else:
                    st.warning("この対象月にスナップショットがありません。")
        elif page == PAGE_HISTORY:
            st.caption("過去実績（確定値）・閲覧専用")
            hmeta = read_json(hist_path(F_HISTORY_META)) or {}
            if hmeta.get("収録開始年月"):
                st.caption(f"収録：{hmeta['収録開始年月']} 〜 {hmeta['収録終了年月']}")
        else:
            st.caption("売上ポートフォリオ（確定値）・閲覧専用")
            pmeta = read_json(hist_path(F_PORTFOLIO_META)) or {}
            if pmeta.get("収録開始年月"):
                st.caption(f"収録：{pmeta['収録開始年月']} 〜 {pmeta['収録終了年月']}")

        st.caption("予測は毎日ローカルで自動更新し、集計済みの結果のみをクラウドへ反映します。"
                   "個人情報・患者単位データは一切含みません。")

    if page == PAGE_PORTFOLIO:
        render_portfolio(nav=page_nav)
    elif page == PAGE_HISTORY:
        render_history(nav=page_nav)
    elif not months:
        st.markdown('<div style="font-size:29px;font-weight:800;color:#0B1F3A;">'
                    'MDC Forecast Console｜日次ローリング予測</div>', unsafe_allow_html=True)
        page_nav()
        st.warning("表示できる対象月がありません。data/YYYY_MM/ に snapshots とlatest.json を配置してください。")
    elif not snap:
        st.markdown('<div style="font-size:29px;font-weight:800;color:#0B1F3A;">'
                    'MDC Forecast Console｜日次ローリング予測</div>', unsafe_allow_html=True)
        page_nav()
        st.warning("表示できるスナップショットがありません。")
    else:
        render(target, snap, nav=page_nav)
