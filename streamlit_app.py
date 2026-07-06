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

起動: py -m streamlit run streamlit_app.py
"""
import os
import re
import json
import csv
import html as _html
import streamlit as st

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

MONTH_RE = re.compile(r"^(\d{4})_(\d{2})$")
ASOF_RE = re.compile(r"^(\d{4})_(\d{2})_(\d{2})$")

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
:root{--navy:#0B1F3A;--navy2:#1A3358;--gold:#C8A96A;--red:#B5544A;--green:#2f8f5b;
  --ink:#1E1E1E;--muted:#6b7686;--line:#e3e7ee;}
[data-testid="stDecoration"]{display:none;}
[data-testid="stHeader"]{background:rgba(255,255,255,0);height:auto;}
.block-container{padding-top:2.6rem !important;padding-bottom:2rem;max-width:1420px;overflow:visible;}
.mfc-title{font-size:29px;font-weight:800;color:var(--navy);letter-spacing:.3px;line-height:1.25;margin:.1rem 0 3px;}
.mfc-vchip{display:inline-block;background:var(--gold);color:#3a2c07;font-size:12px;font-weight:800;
  border-radius:6px;padding:1px 8px;margin-left:8px;vertical-align:middle;}
.mfc-sub{font-size:13px;color:var(--muted);margin-bottom:6px;line-height:1.6;}
.mfc-meta{font-size:12px;color:var(--muted);margin-bottom:8px;}
.mfc-meta b{color:var(--navy);}
.mfc-legend{display:flex;gap:14px;flex-wrap:wrap;align-items:center;font-size:12px;color:var(--muted);
  border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:7px 2px;margin:2px 0 14px;}
.mfc-warn{background:#fbf1df;border-left:6px solid var(--gold);border-radius:0 10px 10px 0;
  padding:11px 16px;margin:6px 0 14px;font-size:14px;color:#7a5a10;font-weight:700;}
/* ラベルチップ（実績/推定/見込/参考） */
.lab{display:inline-block;font-size:11px;font-weight:800;border-radius:5px;padding:1px 7px;margin-left:7px;
  vertical-align:middle;letter-spacing:.2px;}
.lab-act{background:#e5f3ea;color:#1d6b41;border:1px solid #bfe3cd;}
.lab-mdl{background:#e9eef7;color:#274b86;border:1px solid #c9d6ea;}
.lab-est{background:#fbf1df;color:#7a5a10;border:1px solid #e7d4a6;}
.lab-ref{background:#eef0f4;color:#6b7686;border:1px solid #dcdfe6;}
/* サマリー帯 */
.mfc-hero{background:linear-gradient(135deg,#0B1F3A 0%,#1A3358 100%);border-radius:16px;
  padding:18px 22px;color:#fff;box-shadow:0 5px 16px rgba(11,31,58,.28);}
.mfc-grid6{display:grid;grid-template-columns:1.5fr 1fr 1fr 1.2fr 1.2fr 1.4fr;gap:11px;}
.mfc-hc{background:rgba(255,255,255,.05);border:1px solid #33507a;border-radius:12px;padding:11px 13px;}
.mfc-hc .lb{font-size:11px;color:var(--gold);font-weight:700;margin-bottom:5px;letter-spacing:.2px;}
.mfc-hc .vl{font-size:25px;font-weight:800;color:#fff;line-height:1.05;}
.mfc-hc .vl .u{font-size:12px;color:#aeb9c9;margin-left:2px;font-weight:700;}
.mfc-hc .sb{font-size:11px;color:#aeb9c9;margin-top:5px;line-height:1.4;}
.mfc-hc.main{background:rgba(200,169,106,.15);border-color:var(--gold);}
.mfc-hc.main .vl{font-size:33px;}
.mfc-up{color:#7FE0A6 !important;}.mfc-dn{color:#FF9E9E !important;}.mfc-fl{color:#F0C674 !important;}
/* So What 帯 */
.mfc-sowhat{border-left:5px solid var(--gold);background:#f7f5ef;border-radius:0 10px 10px 0;
  padding:10px 15px;margin:10px 0 4px;font-size:13.5px;color:#3b3b3b;line-height:1.7;}
.mfc-sowhat .sw{color:var(--gold);font-weight:800;margin-right:6px;}
.mfc-sowhat b{color:var(--navy);}
/* セクション見出し */
.mfc-sec{font-size:16px;font-weight:800;color:var(--navy);border-left:6px solid var(--gold);
  padding-left:10px;margin:22px 0 10px;}
/* 汎用カードグリッド */
.mfc-cards{display:grid;grid-template-columns:repeat(3,1fr);gap:13px;}
.mfc-cards4{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;}
.mfc-card{background:#fff;border:1px solid var(--line);border-radius:14px;padding:14px 16px;
  box-shadow:0 1px 5px rgba(0,0,0,.05);}
.mfc-card.tp-g{border-top:4px solid var(--green);}
.mfc-card.tp-n{border-top:4px solid var(--navy2);}
.mfc-card.tp-o{border-top:4px solid var(--gold);}
.mfc-card.tp-r{border-top:4px solid var(--red);}
.mfc-card .lb{font-size:12.5px;font-weight:800;color:var(--navy);margin-bottom:6px;}
.mfc-card .big{font-size:27px;font-weight:800;color:var(--navy);line-height:1;}
.mfc-card .big .u{font-size:13px;color:#8a94a3;margin-left:3px;font-weight:700;}
.mfc-card .py{font-size:12px;color:var(--muted);margin-top:6px;line-height:1.5;}
.mfc-card .py b{color:var(--navy);}
.mfc-card .cardsw{font-size:11.5px;color:#5a5f68;margin-top:7px;line-height:1.55;
  border-top:1px dashed #ececf0;padding-top:6px;}
.mfc-card .cardsw .sw{color:var(--gold);font-weight:800;}
.mfc-card .na{font-size:19px;font-weight:800;color:#9aa3b0;}
/* 進捗4カード（①②③＝着地） */
.mfc-prog{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;}
.mfc-prog .mfc-card.eq{background:linear-gradient(135deg,#eef3fb,#fff);border-color:#c9d6ea;}
/* 高単価レンジ */
.mfc-hv{background:linear-gradient(135deg,#fbf4e6,#fff);border:1px solid var(--gold);
  border-radius:14px;padding:13px 18px;display:flex;align-items:center;gap:18px;
  box-shadow:0 1px 5px rgba(0,0,0,.05);margin-top:12px;}
.mfc-hv .lb{font-size:13px;font-weight:800;color:#7a5a10;}
.mfc-hv .rng{font-size:27px;font-weight:800;color:var(--navy);}
.mfc-hv .rng .u{font-size:13px;color:#8a94a3;margin-left:3px;}
.mfc-hv .note{font-size:12px;color:#7a5a10;flex:1;}
/* 判断サマリー */
.mfc-judge{border-left:5px solid var(--gold);background:#f6f7f9;border-radius:0 10px 10px 0;
  padding:12px 16px;margin:6px 0 4px;font-size:14px;color:#333;line-height:1.7;}
.mfc-judge b{color:var(--navy);}.mfc-judge ul{margin:6px 0 0;padding-left:20px;}.mfc-judge li{margin:3px 0;}
/* 差分・アクション */
.mfc-diff{background:#fff;border:1px solid var(--line);border-top:4px solid var(--gold);border-radius:14px;
  padding:13px 18px;box-shadow:0 1px 5px rgba(0,0,0,.05);font-size:14px;color:#333;line-height:1.8;}
.mfc-diff b{color:var(--navy);}
.mfc-actions{background:#fff;border:1px solid var(--line);border-top:4px solid var(--gold);border-radius:14px;
  padding:15px 20px;box-shadow:0 1px 6px rgba(0,0,0,.06);}
.mfc-actions .h{font-size:15px;font-weight:800;color:var(--navy);margin-bottom:10px;}
.mfc-actions ul{list-style:none;margin:0;padding:0;}
.mfc-actions li{font-size:14px;color:#2b2b2b;padding:9px 0 9px 30px;position:relative;
  border-bottom:1px dashed #ececf0;line-height:1.5;}
.mfc-actions li:last-child{border-bottom:none;}
.mfc-actions li:before{content:'▢';position:absolute;left:4px;color:var(--gold);font-weight:800;}
.mfc-note{font-size:12px;color:var(--muted);margin-top:8px;line-height:1.6;}
@media (max-width:900px){
  .mfc-grid6{grid-template-columns:1fr 1fr;}.mfc-hc.main{grid-column:span 2;}
  .mfc-cards,.mfc-cards4,.mfc-prog{grid-template-columns:1fr 1fr;}
  .mfc-hv{flex-direction:column;align-items:flex-start;gap:8px;}
  .mfc-title{font-size:23px;}.mfc-hc .vl{font-size:22px;}.mfc-hc.main .vl{font-size:28px;}
}
</style>
"""


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


# ======================================================================
# 本体描画
# ======================================================================
def render(month, snap):
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
    st.markdown('<div class="mfc-title">MDC Forecast Console｜日次ローリング予測'
                '<span class="mfc-vchip">正データ</span></div>', unsafe_allow_html=True)
    st.markdown(
        "<div class='mfc-sub'>院内検証用・クラウド閲覧専用画面です。表示値は確定値ではなく、"
        "経営判断の中心線（推定値）です。月末後に実績と照合して検証します。</div>",
        unsafe_allow_html=True)
    st.markdown(
        f"<div class='mfc-meta'>対象月：<b>{ym_jp}</b>　｜　予測基準日(as_of)：<b>{as_of}</b>　｜　"
        f"予測方式：<b>{meta.get('forecast_mode','日次ローリング予測')}</b>　｜　"
        f"モデル：{roll.get('model_version','MDC Forecast Model v2.0')}　｜　生成：{gen_at}</div>",
        unsafe_allow_html=True)
    st.markdown(
        "<div class='mfc-legend'>"
        f"{lab('act')}<span>確定した当月レセコン実績</span>"
        f"{lab('mdl')}<span>モデル推定（曜日別平均×予約ペース補正）</span>"
        f"{lab('est')}<span>予約・過去平均ベースの見込み</span>"
        f"{lab('ref')}<span>出力レポート（下部・参考表示）</span>"
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

    # ========== 1. 最上段サマリー帯 ==========
    r80 = f"{manv(lo)}〜{manv(hi)}" if (lo is not None and hi is not None) else "取得不可"
    yoy_pct = f"（{yoy_rate:+.1f}%）" if isinstance(yoy_rate, (int, float)) else ""
    hero = (
        "<div class='mfc-hero'><div class='mfc-grid6'>"
        + hc("現時点着地見込み", manv(cur), "万円", "main", sub="日次ローリング（①＋②＋③）")
        + hc("前年同月実績", manv(py), "万円", "", "", "2025年7月（確定）")
        + hc("前年差", smanv(yoy), "万円", "", f"mfc-{signclass(yoy)}", yoy_pct)
        + hc("通常営業ベース予測", manv(base), "万円", "", "", "木曜も開院した場合")
        + hc("通常営業ベースとの差", smanv(gap), "万円", "", f"mfc-{signclass(gap)}",
             "木曜休診影響の候補")
        + hc("80%予測レンジ", r80, "万円", "", "", "残り見込みの不確実性")
        + "</div></div>"
    )
    st.markdown(hero, unsafe_allow_html=True)

    below = (cur is not None and py is not None and cur < py)
    yoy_word = "下回る" if below else ("上回る" if (cur is not None and py is not None and cur > py) else "ほぼ並ぶ")
    st.markdown(sowhat(
        f"現時点着地見込み <b>{man(cur)}</b> は前年同月 <b>{man(py)}</b> を{yoy_word}見込み"
        f"（前年差 {sman(yoy)}{yoy_pct}）。通常営業ベース <b>{man(base)}</b> との差 <b>{sman(gap)}</b> は"
        "<b>確定的な損失ではありません</b>。木曜休診影響の候補として、自費売上化と他曜日充足で"
        "埋められるかが焦点。月末後に吸収判定します。"), unsafe_allow_html=True)

    # ---------- 着地見込みの比較（基準／保守／参考／前年）----------
    cons = fnum(roll.get("conservative_forecast"))
    v2ms = fnum(roll.get("v2_month_start_forecast"))
    rvis = roll.get("reservation_visible_remaining_as_of")
    rproj = roll.get("reservation_projected_final_remaining")
    st.markdown('<div class="mfc-sec">着地見込みの比較（基準・保守・参考）</div>', unsafe_allow_html=True)
    st.markdown(
        "<div class='mfc-cards4'>"
        f"<div class='mfc-card tp-o'><div class='lb'>基準予測{lab('mdl')}</div>"
        f"<div class='big'>{manv(cur)}<span class='u'>万円</span></div>"
        "<div class='py'>訪問・介護＋予約増加補正</div></div>"
        f"<div class='mfc-card tp-g'><div class='lb'>保守ライン{lab('mdl')}</div>"
        f"<div class='big'>{manv(cons)}<span class='u'>万円</span></div>"
        "<div class='py'>訪問・介護補正のみ（予約増加は織り込まず）</div></div>"
        f"<div class='mfc-card tp-n'><div class='lb'>月初参考{lab('ref')}</div>"
        f"<div class='big'>{manv(v2ms)}<span class='u'>万円</span></div>"
        "<div class='py'>V2月初型の参考値</div></div>"
        f"<div class='mfc-card tp-r'><div class='lb'>前年同月{lab('act')}</div>"
        f"<div class='big'>{manv(py)}<span class='u'>万円</span></div>"
        "<div class='py'>2025年7月実績</div></div>"
        "</div>", unsafe_allow_html=True)
    st.markdown(sowhat(
        f"<b>基準予測 {man(cur)}</b>：現時点の残り予約 <b>{rvis:,}件</b> に対し、"
        f"過去12か月の同日以降の予約増加実績を反映し、月末最終予約見込みを <b>{rproj:,}件</b> "
        "として補正しています。&nbsp;"
        f"<b>保守ライン {man(cons)}</b>：予約増加を織り込まず、訪問・介護補正のみを反映した場合の"
        "保守ラインです。いずれも確定値ではなく、過去実績に基づく見込みです。"),
        unsafe_allow_html=True)
    st.markdown(
        "<div class='mfc-warn'>予約増加倍率は過去12か月実績に基づくため、"
        "今後数日の予約入り状況によって着地見込みは上下します。</div>",
        unsafe_allow_html=True)

    # ========== 2. 月中進捗（①②③④＝着地） ==========
    vc = fnum(roll.get("visit_care_forecast_total"))
    st.markdown('<div class="mfc-sec">2. 月中進捗（着地の内訳）</div>', unsafe_allow_html=True)
    st.markdown(
        "<div class='mfc-prog'>"
        f"<div class='mfc-card tp-g'><div class='lb'>① 確定実績{lab('act')}</div>"
        f"<div class='big'>{manv(actual_td)}<span class='u'>万円</span></div>"
        f"<div class='py'>〜{as_of}・外来保険＋自費＋物販（取込済み）</div></div>"
        f"<div class='mfc-card tp-n'><div class='lb'>② 経過分の推定{lab('mdl')}</div>"
        f"<div class='big'>{manv(elapsed)}<span class='u'>万円</span></div>"
        f"<div class='py'>経過したが実績未取込の診療日</div></div>"
        f"<div class='mfc-card tp-o'><div class='lb'>③ 残り期間の見込み{lab('est')}</div>"
        f"<div class='big'>{manv(remaining)}<span class='u'>万円</span></div>"
        f"<div class='py'>{as_of}翌日〜月末（外来保険・自費・物販／木曜休診反映）</div></div>"
        f"<div class='mfc-card tp-r'><div class='lb'>④ 訪問・介護見込み{lab('est')}</div>"
        f"<div class='big'>{manv(vc)}<span class='u'>万円</span></div>"
        f"<div class='py'>過去12か月平均・入力遅れ補正（ペース補正なし）</div></div>"
        "</div>", unsafe_allow_html=True)
    st.markdown(
        f"<div class='mfc-note'>＝ 月末着地見込み <b>{man(cur)}</b>（① ＋ ② ＋ ③ ＋ ④）。</div>",
        unsafe_allow_html=True)
    st.markdown(sowhat(
        "<b>月末着地見込み ＝ ①確定実績 ＋ ②経過分の推定 ＋ ③残り期間の見込み ＋ ④訪問・介護見込み</b>。"
        "<b>訪問・介護は月初入力が遅れるため、外来予約ペースとは分けて補正しています</b>"
        "（過去12か月平均・0扱いしない）。②が0に近いほど、また予約が埋まるほど確度が上がります。"),
        unsafe_allow_html=True)
    st.markdown(
        "<div class='mfc-note'>"
        f"レセコン実績反映：<b>{resec_status}</b>"
        + (f"（{actual_through} まで反映）" if actual_through else "（当月分は未取込）")
        + f"　｜　予約反映：<b>{apo_status}</b>"
        + (f"（{res_through} まで登録済み）" if res_through else "") + "</div>",
        unsafe_allow_html=True)

    # ---------- 予約ペース補正（Part B：月中の予約増加を織り込む）----------
    rg_vis = roll.get("reservation_visible_remaining_as_of")
    rg_mult = roll.get("reservation_growth_multiplier")
    rg_proj = roll.get("reservation_projected_final_remaining")
    rg_fac = roll.get("reservation_factor_final", roll.get("reservation_factor"))
    if rg_mult is not None:
        st.markdown(
            "<div class='mfc-split'>"
            f"<div class='mfc-chip'>現在見えている残り予約：<b>{rg_vis:,}件</b></div>"
            f"<div class='mfc-chip'>月末までの予約増加倍率：<b>{rg_mult:.2f}x</b>（過去12か月）</div>"
            f"<div class='mfc-chip'>月末最終予約見込み：<b>{rg_proj:,}件</b></div>"
            f"<div class='mfc-chip' style='background:#eef3fb;border-color:#c9d6ea;'>"
            f"適用 予約ペース補正：<b>{rg_fac:.2f}</b></div>"
            "</div>", unsafe_allow_html=True)
        st.markdown(sowhat(
            "<b>月中の予約増加を過去実績から見込み、現在見えている予約数だけで過小評価しないよう補正しています。</b>"
            f"7/6時点で見えている残り予約 <b>{rg_vis:,}件</b> は、過去12か月では月末までに"
            f"平均 <b>{rg_mult:.2f}倍</b> に増えるため、月末最終 <b>{rg_proj:,}件</b> と見込んで"
            f"予約ペース補正 <b>{rg_fac:.2f}</b> を算出しています（現在数のまま0.85に下げる方式は採用しません／"
            "上下限 0.85〜1.10）。訪問・介護にはこの予約増加ロジックは適用しません（④で別建て）。"),
            unsafe_allow_html=True)

    # ========== 3. 今月の判断サマリー ==========
    st.markdown('<div class="mfc-sec">3. 今月の判断サマリー</div>', unsafe_allow_html=True)
    hvl = fnum(roll.get("high_value_selfpay_low"))
    hvh = fnum(roll.get("high_value_selfpay_high"))
    hv_disp = f"{manv(hvl)}〜{manv(hvh)}万円" if (hvl is not None and hvh is not None) else "取得不可"
    st.markdown(
        f"<div class='mfc-judge'>現時点では<b>前年同月を{yoy_word}見込み</b>です。"
        "<ul>"
        f"<li>現時点着地見込み <b>{man(cur)}</b> は前年 <b>{man(py)}</b> を {sman(yoy)}{yoy_pct}。</li>"
        f"<li>通常営業ベース <b>{man(base)}</b> との差 <b>{sman(gap)}</b> は"
        "<b>木曜休診影響の候補</b>（確定的な損失ではありません）。他曜日に吸収された可能性を月末後に判定。</li>"
        f"<li>差を埋める鍵＝<b>高単価型 自費レンジ {hv_disp}</b> の月内売上化。</li>"
        "</ul></div>", unsafe_allow_html=True)
    st.markdown(sowhat(
        f"前年割れの主因は診療日減（木曜休診）。通常営業ベースは前年に近い水準のため、"
        f"差 {sman(gap)} を自費高単価の売上化と他曜日充足で埋められるかが焦点。"), unsafe_allow_html=True)

    # ========== 4. 売上系カード ==========
    st.markdown('<div class="mfc-sec">4. 売上構成（当月着地見込み）</div>', unsafe_allow_html=True)

    def scard(lb_, key, akey, pkey, tp, so):
        v = fnum(roll.get(key))
        av = fnum(roll.get(akey))
        pv = fnum(roll.get(pkey))
        diff = (v - pv) if (v is not None and pv is not None) else None
        pyline = (f"前年同月 <b>{manv(pv)}万</b>　{sman(diff)}{pct_of(v, pv)}"
                  if pv is not None else "前年同月：取得不可")
        atxt = (f"うち確定実績 {manv(av)}万" if (av and av > 0) else "確定実績：未反映")
        return (f"<div class='mfc-card {tp}'><div class='lb'>{lb_}{lab('mdl')}</div>"
                f"<div class='big'>{manv(v)}<span class='u'>万円</span></div>"
                f"<div class='py'>{pyline}<br>{atxt}</div>"
                f"<div class='cardsw'><span class='sw'>So What</span>{so}</div></div>")

    st.markdown(
        "<div class='mfc-cards'>"
        + scard("保険診療売上予測", "insurance_forecast", "insurance_actual_to_date",
                "insurance_prevyear", "tp-g",
                "基礎売上の芯。他曜日の来院枠を埋めて目減りを抑える。")
        + scard("自費診療売上予測", "selfpay_forecast", "selfpay_actual_to_date",
                "selfpay_prevyear", "tp-o",
                "変動が大きく差の主因になりうる。高単価案件の月内売上化が鍵。")
        + scard("物販売上予測", "product_forecast", "product_actual_to_date",
                "product_prevyear", "tp-n",
                "影響は小さい。判断は保険・自費・予約構成を優先する。")
        + "</div>", unsafe_allow_html=True)
    st.markdown(
        f"<div class='mfc-hv'><div><div class='lb'>高単価型 自費レンジ{lab('est')}</div>"
        f"<div class='rng'>{hv_disp.replace('万円','')}<span class='u'>万円</span></div></div>"
        "<div class='note'>高単価型自費は月末着地に与える影響が大きいため、"
        "案件別の進捗確認が必要です（上振れ要因）。</div></div>", unsafe_allow_html=True)
    outp = fnum(roll.get("outpatient_insurance_forecast"))
    vins = fnum(roll.get("visit_insurance_forecast"))
    care = fnum(roll.get("care_forecast"))
    if outp is not None:
        st.markdown(
            f"<div class='mfc-note'><b>保険の内訳（着地見込み）</b>：外来保険 <b>{man(outp)}</b>"
            f"（予約ペース補正あり）／訪問保険 <b>{man(vins)}</b>／介護 <b>{man(care)}</b>。"
            "<b>訪問・介護は月初入力が遅れるため、外来予約ペース補正（0.85）を掛けず、"
            "過去12か月平均で見込んでいます</b>（月初に実績が0でも0扱いしません）。</div>",
            unsafe_allow_html=True)

    # ========== 5. 患者数・来院系カード ==========
    st.markdown('<div class="mfc-sec">5. 患者数・来院系（当月見込み）</div>', unsafe_allow_html=True)
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

    # 総患者数：月間ユニークは日次集計から復元不可 → データ未取得
    if pat.get("available"):
        patient_card = cnt_card("総患者数", pat.get("forecast"), pat.get("prevyear"), "人", "mdl",
                                "来院枠を埋めて患者数を確保する。", "tp-g")
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
        + cnt_card("総来院回数", vis.get("forecast"), vis.get("prevyear"), "回", "est",
                   "来院回数の前年差は売上の量的な下押し。他曜日への振替・空き枠再充填で回復を図る。", "tp-n")
        + cnt_card("初診件数", sho.get("forecast"), sho.get("prevyear"), "件", "est",
                   "初診のうち自費相談・治療移行見込みを確認し、自費売上化につなげる。", "tp-o")
        + cancel_card
        + "</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='mfc-note'>総来院回数・初診件数は「確定実績（〜" + str(actual_through or as_of)
        + "）＋残り見込み」の当月着地見込み（見込ラベル）。キャンセル率・予約構成は"
        "as_of時点で登録済みの当月予約に基づく実データです。総患者数（月間ユニーク）は"
        "日次集計から復元できないため未取得としています（推測値は作りません）。</div>",
        unsafe_allow_html=True)

    # ========== 6. 予約構成系カード ==========
    st.markdown('<div class="mfc-sec">6. 予約構成（登録済み予約・as_of時点）</div>', unsafe_allow_html=True)
    comp = sup.get("reservation_composition") or {}
    if comp.get("available"):
        types = comp.get("types") or {}
        order = [("継続管理型", "tp-g", "継続来院の充足を維持して着地の下支えに。"),
                 ("都度治療型", "tp-n", "未充足枠・キャンセル枠を洗い出して補充する。"),
                 ("高単価型", "tp-o", "案件増が要因なら充足維持で着地の下支えに。"),
                 ("混合・判定保留", "tp-r", "未充足枠・キャンセル枠を洗い出して補充する。")]
        cards = []
        for name, tp, so in order:
            t = types.get(name) or {}
            cv = t.get("current"); pv = t.get("prevyear")
            diff = (cv - pv) if (cv is not None and pv is not None) else None
            pyline = (f"前年同月(実績) <b>{intv(pv)}件</b>　{sint(diff)}{pct_of(cv, pv)}"
                      if pv is not None else "前年同月：取得不可")
            cards.append(
                f"<div class='mfc-card {tp}'><div class='lb'>{name}{lab('act')}</div>"
                f"<div class='big'>{intv(cv)}<span class='u'>件</span></div>"
                f"<div class='py'>登録済み予約(as_of時点)<br>{pyline}</div>"
                f"<div class='cardsw'><span class='sw'>So What</span>{so}</div></div>")
        st.markdown("<div class='mfc-cards4'>" + "".join(cards) + "</div>", unsafe_allow_html=True)
        st.markdown(
            "<div class='mfc-note'>当月(" + ym_jp + ")の<b>as_of時点で登録済みの予約</b>を型別に集計した"
            "実データ（合計 " + intv(comp.get("current_total")) + "件）。前年同月は確定実績（月間）です。"
            "月内はこれから登録・キャンセルが増減するため、前年との単純比較ではなく"
            "<b>充足・空き枠の管理指標</b>として見ます。</div>", unsafe_allow_html=True)
    else:
        st.markdown("<div class='mfc-card'><div class='na'>データ未取得</div>"
                    "<div class='py'>当月の予約構成データが取得できません。</div></div>",
                    unsafe_allow_html=True)

    # ========== 予測推移 / 前回差分 ==========
    hist = read_history(month)
    st.markdown('<div class="mfc-sec">予測推移（予測基準日ごとの着地見込み）</div>', unsafe_allow_html=True)
    if len(hist) >= 1:
        try:
            import pandas as pd
            df = pd.DataFrame([{
                "予測基準日": r.get("as_of_date"),
                "現時点着地見込み(万円)": (fnum(r.get("current_forecast_total")) or 0) / 10000,
                "通常営業ベース(万円)": (fnum(r.get("normal_baseline_forecast")) or 0) / 10000,
                "前年同月(万円)": (fnum(r.get("previous_year_actual")) or 0) / 10000,
            } for r in hist]).set_index("予測基準日")
            st.line_chart(df, height=280)
        except Exception:
            for r in hist:
                st.write(f"- {r.get('as_of_date')}：着地 {man(fnum(r.get('current_forecast_total')))}")
    else:
        st.info("予測推移を表示するには、複数の予測基準日のスナップショットが必要です。")

    prev = None
    for r in hist:
        if r.get("as_of_date", "") < as_of:
            prev = r
    st.markdown('<div class="mfc-sec">前回予測との差分</div>', unsafe_allow_html=True)
    if prev:
        pc = fnum(prev.get("current_forecast_total"))
        d_cur = (cur - pc) if (cur is not None and pc is not None) else None
        st.markdown(
            "<div class='mfc-diff'>"
            f"前回基準日 <b>{prev.get('as_of_date')}</b> と比べて、現時点着地見込みは "
            f"<b>{man(pc)} → {man(cur)}</b>"
            f"（<span class='mfc-{signclass(d_cur)}' style='font-weight:800'>{sman(d_cur)}</span>）。"
            "基準日が進むほど確定実績が増え、着地見込みの確度が上がります。</div>",
            unsafe_allow_html=True)
    else:
        st.markdown(
            "<div class='mfc-diff'>この対象月で、これより前の予測基準日がまだありません"
            "（本スナップショットが最初の基準日）。翌日以降の更新から差分が表示されます。</div>",
            unsafe_allow_html=True)

    # ========== 経営アクション ==========
    st.markdown('<div class="mfc-sec">今月、月末までに確認すること</div>', unsafe_allow_html=True)
    acts = parse_actions_from_md(summary_md)
    if acts:
        li = "".join(f"<li><b>{i}.</b> {_html.escape(str(a))}</li>" for i, a in enumerate(acts, 1))
        body = f"<ul>{li}</ul>"
    else:
        body = ("<ul><li><b>1.</b> 高単価型自費の案件別進捗を確認（月内売上化か翌月送りか）。</li>"
                "<li><b>2.</b> 継続管理型の未充足枠・キャンセル枠を他曜日へ補充。</li>"
                "<li><b>3.</b> 月末確定後、通常営業ベースとの差が吸収されたかを判定。</li></ul>")
    st.markdown("<div class='mfc-actions'><div class='h'>院長・事務局が「で、何をするか」を見る場所です</div>"
                f"{body}</div>", unsafe_allow_html=True)

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
# エントリポイント
# ======================================================================
if check_password():
    months = list_months()
    with st.sidebar:
        st.markdown("### MDC Forecast Console")
        st.caption("日次ローリング予測・閲覧専用")
        if months:
            labels = [ym_label(m) for m in months]
            sel_m = st.selectbox("対象月", labels, index=0)
            target = months[labels.index(sel_m)]
        else:
            target = None

        snap = None
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
        st.caption("更新はローカル運用版（run_daily_forecast_update.bat）で行います。"
                   "生成された latest.json / forecast_history.csv / snapshots のみをクラウドへ反映します。")

    if not months:
        st.markdown('<div style="font-size:29px;font-weight:800;color:#0B1F3A;">'
                    'MDC Forecast Console｜日次ローリング予測</div>', unsafe_allow_html=True)
        st.warning("表示できる対象月がありません。data/YYYY_MM/ に snapshots とlatest.json を配置してください。")
    elif not snap:
        st.markdown('<div style="font-size:29px;font-weight:800;color:#0B1F3A;">'
                    'MDC Forecast Console｜日次ローリング予測</div>', unsafe_allow_html=True)
        st.warning("表示できるスナップショットがありません。")
    else:
        render(target, snap)
