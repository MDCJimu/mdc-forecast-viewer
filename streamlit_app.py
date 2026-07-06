# -*- coding: utf-8 -*-
"""
MDC Forecast Console — クラウド閲覧専用版（日次ローリング予測ビューアー）
========================================================================
院長がURLで最新の月末着地見込みを確認するための閲覧専用画面です。
- 予測更新なし / run_all.bat 実行なし / raw・processed・患者単位データ処理なし
- 表示するのは、ローカル運用版で生成した「集計済みスナップショット」だけ
- 予測基準日(as_of_date)ごとのスナップショットを切り替えて、予測推移・前回差分を確認できる

データ構造（各対象月フォルダ）:
  data/<YYYY_MM>/
    latest.json            … 最初に読む。最新スナップショットを指す
    forecast_history.csv   … as_of_date ごとの予測結果（予測推移）
    snapshots/<YYYY_MM_DD>/
        daily_rolling_forecast.json  … その基準日の予測（正データ）
        forecast_meta.json           … いつ時点の予測か
        dashboard_v3.xlsx / _summary.md / forecast_summary_v2.md /
        model_card_v2.md / dashboard_v3.png   … 共有・保存用の出力レポート

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


def ym_label(folder):
    m = MONTH_RE.match(folder)
    if not m:
        return folder
    return f"{int(m.group(1))}年{int(m.group(2))}月"


def asof_label(folder):
    m = ASOF_RE.match(folder)
    if not m:
        return folder
    return f"{int(m.group(1))}年{int(m.group(2))}月{int(m.group(3))}日"


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


def fnum(v):
    try:
        return float(v)
    except Exception:
        return None


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
# CSS（紺×ゴールド・落ち着いた赤・大型カード）
# ======================================================================
CSS = """
<style>
:root{--navy:#0B1F3A;--navy2:#1A3358;--gold:#C8A96A;--red:#B5544A;--ink:#1E1E1E;--muted:#6b7686;}
[data-testid="stDecoration"]{display:none;}
[data-testid="stHeader"]{background:rgba(255,255,255,0);height:auto;}
.block-container{padding-top:3rem !important;padding-bottom:2rem;max-width:1360px;overflow:visible;}
.mfc-title{font-size:29px;font-weight:800;color:var(--navy);letter-spacing:.3px;line-height:1.3;margin:.2rem 0 4px;}
.mfc-sub{font-size:13px;color:var(--muted);margin-bottom:6px;line-height:1.6;}
.mfc-meta{font-size:12px;color:var(--muted);margin-bottom:12px;}
.mfc-meta b{color:var(--navy);}
.mfc-warn{background:#fbf1df;border-left:6px solid var(--gold);border-radius:0 10px 10px 0;
  padding:11px 16px;margin:6px 0 14px;font-size:14px;color:#7a5a10;font-weight:700;}
.mfc-hero{background:linear-gradient(135deg,#0B1F3A 0%,#1A3358 100%);border-radius:16px;
  padding:20px 24px;color:#fff;box-shadow:0 5px 16px rgba(11,31,58,.28);}
.mfc-concl{font-size:16px;color:#e6ecf5;line-height:1.7;margin:2px 0 16px;}
.mfc-concl b{color:#fff;}.mfc-concl .g{color:var(--gold);font-weight:800;}
.mfc-grid6{display:grid;grid-template-columns:1.5fr 1fr 1fr 1.2fr 1.2fr 1.4fr;gap:11px;}
.mfc-hc{background:rgba(255,255,255,.05);border:1px solid #33507a;border-radius:12px;padding:11px 13px;}
.mfc-hc .lb{font-size:11px;color:var(--gold);font-weight:700;margin-bottom:5px;letter-spacing:.2px;}
.mfc-hc .vl{font-size:25px;font-weight:800;color:#fff;line-height:1.05;}
.mfc-hc .vl .u{font-size:12px;color:#aeb9c9;margin-left:2px;font-weight:700;}
.mfc-hc.main{background:rgba(200,169,106,.15);border-color:var(--gold);}
.mfc-hc.main .vl{font-size:33px;}
.mfc-up{color:#7FE0A6 !important;}.mfc-dn{color:#FF9E9E !important;}.mfc-fl{color:#F0C674 !important;}
.mfc-split{display:flex;gap:10px;margin:10px 0 2px;flex-wrap:wrap;}
.mfc-chip{background:#f3f5f8;border:1px solid #e3e7ee;border-radius:10px;padding:7px 13px;font-size:13px;color:#333;}
.mfc-chip b{color:var(--navy);}
.mfc-judge{border-left:5px solid var(--gold);background:#f6f7f9;border-radius:0 10px 10px 0;
  padding:12px 16px;margin:16px 0 4px;font-size:14px;color:#333;line-height:1.7;}
.mfc-judge b{color:var(--navy);}.mfc-judge ul{margin:6px 0 0;padding-left:20px;}.mfc-judge li{margin:3px 0;}
.mfc-sec{font-size:16px;font-weight:800;color:var(--navy);border-left:6px solid var(--gold);
  padding-left:10px;margin:24px 0 10px;}
.mfc-cards{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;}
.mfc-card{background:#fff;border:1px solid #e3e7ee;border-radius:14px;padding:15px 17px;box-shadow:0 1px 5px rgba(0,0,0,.05);}
.mfc-card .lb{font-size:12px;font-weight:700;color:var(--navy);margin-bottom:6px;}
.mfc-card .big{font-size:29px;font-weight:800;color:var(--navy);line-height:1;}
.mfc-card .big .u{font-size:13px;color:#8a94a3;margin-left:3px;}
.mfc-card .sub{font-size:11px;color:var(--muted);margin-top:6px;}
.mfc-hv{grid-column:span 3;background:linear-gradient(135deg,#fbf4e6,#fff);border:1px solid var(--gold);
  border-radius:14px;padding:15px 18px;display:flex;align-items:center;gap:18px;box-shadow:0 1px 5px rgba(0,0,0,.05);}
.mfc-hv .lb{font-size:13px;font-weight:800;color:#7a5a10;}
.mfc-hv .rng{font-size:30px;font-weight:800;color:var(--navy);}
.mfc-hv .rng .u{font-size:13px;color:#8a94a3;margin-left:3px;}
.mfc-hv .note{font-size:12px;color:#7a5a10;flex:1;}
.mfc-diff{background:#fff;border:1px solid #e3e7ee;border-top:4px solid var(--gold);border-radius:14px;
  padding:14px 18px;box-shadow:0 1px 5px rgba(0,0,0,.05);font-size:14px;color:#333;line-height:1.8;}
.mfc-diff b{color:var(--navy);}
.mfc-actions{background:#fff;border:1px solid #e3e7ee;border-top:4px solid var(--gold);border-radius:14px;
  padding:16px 20px;box-shadow:0 1px 6px rgba(0,0,0,.06);}
.mfc-actions .h{font-size:15px;font-weight:800;color:var(--navy);margin-bottom:10px;}
.mfc-actions ul{list-style:none;margin:0;padding:0;}
.mfc-actions li{font-size:14px;color:#2b2b2b;padding:9px 0 9px 30px;position:relative;
  border-bottom:1px dashed #ececf0;line-height:1.5;}
.mfc-actions li:last-child{border-bottom:none;}
.mfc-actions li:before{content:'▢';position:absolute;left:4px;color:var(--gold);font-weight:800;}
.mfc-note{font-size:12px;color:var(--muted);margin-top:8px;line-height:1.6;}
@media (max-width:820px){
  .mfc-grid6{grid-template-columns:1fr 1fr;}.mfc-hc.main{grid-column:span 2;}
  .mfc-cards{grid-template-columns:1fr;}.mfc-hv{grid-column:span 1;flex-direction:column;align-items:flex-start;gap:8px;}
  .mfc-title{font-size:23px;}.mfc-hc .vl{font-size:22px;}.mfc-hc.main .vl{font-size:28px;}
}
</style>
"""


def hc(lb, num, unit="万円", cls="", numcls=""):
    return (f"<div class='mfc-hc {cls}'><div class='lb'>{lb}</div>"
            f"<div class='vl {numcls}'>{num}<span class='u'>{unit}</span></div></div>")


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

    # ---------- タイトル ----------
    st.markdown('<div class="mfc-title">MDC Forecast Console｜日次ローリング予測</div>', unsafe_allow_html=True)
    st.markdown(
        "<div class='mfc-sub'>院内検証用・クラウド閲覧専用画面です。表示値は確定値ではなく、"
        "経営判断の中心線（推定値）です。月末後に実績と照合して検証します。</div>",
        unsafe_allow_html=True)
    st.markdown(
        f"<div class='mfc-meta'>対象月：<b>{ym_jp}</b>　｜　予測基準日(as_of)：<b>{as_of}</b>　｜　"
        f"予測方式：<b>{meta.get('forecast_mode','日次ローリング予測')}</b>　｜　生成：{gen_at}</div>",
        unsafe_allow_html=True)

    # ---------- 当月実績未反映の警告（要件6）----------
    if resec_status != "反映済み":
        st.markdown(
            "<div class='mfc-warn'>⚠ 当月レセコン実績が未反映です。"
            "当月分（予測基準日までに<b>経過済みの診療日</b>を含む）のレセコン実績がまだ取り込まれていないため、"
            "経過分も<b>推定値（下記②）</b>で表示しています（確定実績＝①は0）。"
            "正式に実績を反映するには、当月分を含む最新の resec_data.xlsx を取り込み、日次更新を再実行してください。"
            "実績取込後は①が増え、着地見込みの確度が上がります。</div>", unsafe_allow_html=True)

    if not roll:
        st.warning("このスナップショットの予測データ（daily_rolling_forecast.json）が読み込めません。"
                   "ローカル運用版で再生成してください。")
        return

    cur = fnum(roll.get("current_forecast_total"))
    base = fnum(roll.get("normal_baseline_forecast"))
    gap = fnum(roll.get("gap_to_normal_baseline"))
    py = fnum(roll.get("previous_year_actual"))
    yoy = fnum(roll.get("yoy_diff"))
    lo = fnum(roll.get("forecast_low_80"))
    hi = fnum(roll.get("forecast_high_80"))
    actual_td = fnum(roll.get("actual_to_date_total")) or 0
    elapsed = fnum(roll.get("elapsed_unrecorded_total")) or 0
    remaining = fnum(roll.get("remaining_forecast_total")) or 0

    # ---------- 結論1行 + ヒーロー ----------
    concl = (f"<b>{ym_jp}</b> の現時点着地見込みは <span class='g'>{man(cur)}</span>。"
             f"前年同月比 <span class='mfc-{signclass(yoy)}'>{sman(yoy)}</span>、"
             f"通常営業ベースとの差 <span class='mfc-{signclass(gap)}'>{sman(gap)}</span>。")
    r80 = f"{manv(lo)}〜{manv(hi)}" if (lo is not None and hi is not None) else "取得不可"
    hero = (
        "<div class='mfc-hero'>"
        f"<div class='mfc-concl'>{concl}</div>"
        "<div class='mfc-grid6'>"
        + hc("現時点着地見込み", manv(cur), "万円", "main")
        + hc("前年同月実績", manv(py))
        + hc("前年差", smanv(yoy), "万円", "", f"mfc-{signclass(yoy)}")
        + hc("通常営業ベース予測", manv(base))
        + hc("通常営業ベースとの差", smanv(gap), "万円", "", f"mfc-{signclass(gap)}")
        + hc("80%予測レンジ", r80)
        + "</div></div>"
    )
    st.markdown(hero, unsafe_allow_html=True)

    # ---------- 着地の内訳（3成分を明示）＋定義 ----------
    st.markdown(
        "<div class='mfc-split'>"
        f"<div class='mfc-chip'>① 確定実績（〜{as_of}・取込済）：<b>{man(actual_td)}</b></div>"
        f"<div class='mfc-chip'>② 経過分の推定（〜{as_of}・未取込）：<b>{man(elapsed)}</b></div>"
        f"<div class='mfc-chip'>③ 残り期間の見込み（{as_of}翌日〜月末）：<b>{man(remaining)}</b></div>"
        f"<div class='mfc-chip' style='background:#eef3fb;border-color:#c9d6ea;'>"
        f"＝ 月末着地見込み：<b>{man(cur)}</b></div>"
        "</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='mfc-note'>"
        "<b>月末着地見込み ＝ ①確定実績 ＋ ②経過分の推定 ＋ ③残り期間の見込み</b>。"
        "① は当月レセコンで<b>取り込み済みの実績</b>（＝ actual_to_date）。"
        "② は予測基準日までに<b>経過したが、レセコン実績がまだ取り込まれていない診療日の推定</b>（＝ elapsed）。"
        "③ は<b>予測基準日の翌日から月末まで</b>の見込み（＝ remaining）。"
        "② が 0 に近いほど、着地見込みは確定実績で裏付けられています。"
        "</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='mfc-split'>"
        f"<div class='mfc-chip'>レセコン実績反映：<b>{resec_status}</b>"
        + (f"（{actual_through} まで反映）" if actual_through else "（当月分は未取込）")
        + "</div>"
        f"<div class='mfc-chip'>予約反映：<b>{apo_status}</b>"
        + (f"（{res_through} まで）" if res_through else "")
        + "</div></div>", unsafe_allow_html=True)

    # ---------- 判定 ----------
    below = (cur is not None and py is not None and cur < py)
    above = (cur is not None and py is not None and cur > py)
    if below:
        head = "現時点では<b>前年同月を下回る見込み</b>です。"
    elif above:
        head = "現時点では<b>前年同月を上回る見込み</b>です。"
    else:
        head = "現時点では<b>ほぼ前年同月並み</b>の見込みです。"
    st.markdown(
        f"<div class='mfc-judge'>{head}"
        "<ul>"
        "<li>通常営業ベースとの差は、木曜休診影響の<b>候補</b>として見ます（確定的な損失ではありません）。</li>"
        "<li>実績が通常営業ベースに近づけば、他曜日や自費売上に吸収された可能性があります。</li>"
        "<li>下回る場合は木曜休診影響の候補として検証します。月末後に吸収判定します。</li>"
        "</ul></div>", unsafe_allow_html=True)

    # ---------- 前回予測との差分（要件8）----------
    hist = read_history(month)
    prev = None
    for r in hist:
        if r.get("as_of_date", "") < as_of:
            prev = r  # as_of 昇順なので最後に残るのが直前
    st.markdown('<div class="mfc-sec">前回予測との差分</div>', unsafe_allow_html=True)
    if prev:
        pc = fnum(prev.get("current_forecast_total"))
        d_cur = (cur - pc) if (cur is not None and pc is not None) else None
        pg = fnum(prev.get("gap_to_normal_baseline"))
        st.markdown(
            "<div class='mfc-diff'>"
            f"前回基準日 <b>{prev.get('as_of_date')}</b> と比べて、"
            f"現時点着地見込みは <b>{man(pc)} → {man(cur)}</b>"
            f"（<span class='mfc-{signclass(d_cur)}' style='font-weight:800'>{sman(d_cur)}</span>）。"
            "予測基準日が進むほど、確定実績が増えて着地見込みの確度が上がります。"
            "</div>", unsafe_allow_html=True)
    else:
        st.markdown(
            "<div class='mfc-diff'>この対象月で、これより前の予測基準日がまだありません"
            "（本スナップショットが最初の基準日）。翌日以降の更新から差分が表示されます。</div>",
            unsafe_allow_html=True)

    # ---------- 予測推移（要件7）----------
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
                st.write(f"- {r.get('as_of_date')}：着地 {man(fnum(r.get('current_forecast_total')))}"
                         f" / 通常営業ベース {man(fnum(r.get('normal_baseline_forecast')))}")
        st.markdown("<div class='mfc-note'>青系＝現時点着地見込み、通常営業ベース、前年同月実績の推移。"
                    "着地見込みは基準日が進むほど確定実績に近づきます。</div>", unsafe_allow_html=True)
    else:
        st.info("予測推移を表示するには、複数の予測基準日のスナップショットが必要です。")

    # ---------- 売上構成（保険/自費/物販 + 高単価）----------
    st.markdown('<div class="mfc-sec">売上構成（当月着地見込み）</div>', unsafe_allow_html=True)

    def scard(lb, key, akey, sub):
        v = fnum(roll.get(key))
        av = fnum(roll.get(akey))
        atxt = f"うち実績 {manv(av)}万" if (av and av > 0) else "実績未反映（推定）"
        return (f"<div class='mfc-card'><div class='lb'>{lb}</div>"
                f"<div class='big'>{manv(v)}<span class='u'>万円</span></div>"
                f"<div class='sub'>{sub}／{atxt}</div></div>")

    hvl = fnum(roll.get("high_value_selfpay_low"))
    hvh = fnum(roll.get("high_value_selfpay_high"))
    hv_disp = f"{manv(hvl)}〜{manv(hvh)}" if (hvl is not None and hvh is not None) else "取得不可"
    hv_html = (
        f"<div class='mfc-hv'><div><div class='lb'>高単価型 自費レンジ</div>"
        f"<div class='rng'>{hv_disp}<span class='u'>万円</span></div></div>"
        "<div class='note'>高単価型自費は月末着地に与える影響が大きいため、"
        "案件別の進捗確認が必要です（上振れ要因）。</div></div>")
    st.markdown(
        "<div class='mfc-cards'>"
        + scard("保険診療売上予測", "insurance_forecast", "insurance_actual_to_date", "安定指標（基礎売上の芯）")
        + scard("自費診療売上予測", "selfpay_forecast", "selfpay_actual_to_date", "変動が大きく差の主因になりうる")
        + scard("物販売上予測", "product_forecast", "product_actual_to_date", "影響は小さい")
        + hv_html + "</div>", unsafe_allow_html=True)

    # ---------- 今月、月末までに確認すること ----------
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

    # ---------- 予測の考え方（説明文）----------
    with st.expander("この予測の考え方（院長向け）", expanded=False):
        st.markdown(
            "- 予測値は、AIが感覚で出しているものではありません。\n"
            "- **土台となるV2予測モデル**は、過去約6年分・約72か月以上の売上データと予約データを使い、"
            "過去の各月について「その月の月初時点に戻ったら、月末売上をどれくらい予測できたか」を仮想的に検証しています。\n"
            "- **V2モデルの過去検証では、直近12か月の平均誤差は約6.2％**でした"
            "（これは“月初時点で1か月先を予測した場合”の検証値です）。\n"
            "- **日次ローリング予測**は、このV2モデルをベースに、"
            "**予測基準日までの実績と、残り期間の見込み**を組み合わせた**運用版**です。"
            "基準日が進むほど確定実績が増え、着地見込みの確度が上がります。\n"
            "- **日次ローリング予測そのものの精度は、今後の運用のなかで（月末実績と照合して）検証していきます。**"
            " 約6.2％はV2モデルの月初検証値であり、日次ローリング予測自体の確定精度ではありません。\n"
            "- 表示値は**過去検証済みロジックによる経営判断の中心線**であり、**確定値ではなく推定値**です。"
            "月末後に実績と照合して検証します。")

    # ---------- 出力レポート確認（参考表示・主役にしない）----------
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

    # ---------- スナップショット情報（forecast_meta）----------
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
                # 初期値＝latest.json が指す最新スナップショット
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
