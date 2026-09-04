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
import hmac
import json
import csv
import html as _html
import streamlit as st

# 経営分析の文章生成。表示専用モジュールで、予測値には触れない。
# 読み込めない環境でも画面は落とさない（分析ブロックだけ出さない）。
#
# reload しているのは、Streamlit がこのファイル（メインスクリプト）だけを
# 実行のたびに読み直し、import 済みモジュールは sys.modules に残したまま
# 使い続けるため。デプロイでファイルが差し替わっても、プロセスが再起動
# しない限り mgmt_report は古いままになり、こちら側の呼び出しとだけ食い違う。
# 実際に本番で
#   build_management_report() takes from 1 to 3 positional arguments but 4 were given
# が出た（画面は新しい呼び出し、モジュールは history_rows を受け取る前の版）。
# 毎回ソースから読み直せば、この食い違いは起きない。定数と関数だけの
# モジュールなので、読み直しの副作用も費用もない。
#
# import の前に、このファイル自身の置き場所を sys.path へ入れる。
# Streamlit Cloud はメインスクリプトのディレクトリを sys.path に入れて起動する
# ため本番では何も変わらないが、streamlit.testing の AppTest はそれをしない。
# そのため AppTest では mgmt_report の import が黙って失敗して MR=None になり、
# 「経営分析を組み立てるためのデータが読み込めませんでした」と出たまま
# 全項目が成功していた（経営分析ブロックを一度も検証できていなかった）。
# 起動のされ方に関係なく同じモジュールを読むようにして、この穴をふさぐ。
try:
    import importlib
    import sys as _sys
    if os.path.dirname(os.path.abspath(__file__)) not in _sys.path:
        _sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import mgmt_report as MR
    MR = importlib.reload(MR)
except Exception:      # pragma: no cover - 実行環境にファイルが無い場合のみ
    MR = None

# deploy-marker: portfolio current-month forecast (2026-07-10e) — redeploy trigger

# 本文上部に表示するビルド識別子。Cloud が古いビルドを配信していないか
# 画面から即座に確認できるようにするための目印。サイドバーが折りたたまれて
# いても見えるよう、ページ切替の直下に置く。
APP_BUILD = "2026-07-10e portfolio-forecast"

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")

# 閲覧パスワードは Streamlit Cloud の Secrets（または環境変数）でのみ与える。
# コード・README・ログに秘密値を書かない。未設定なら閲覧を許可しない（fail-closed）。
PW_KEY = "MDC_PREVIEW_PASSWORD"

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
# 院内表示の4分類。サブスク型＝月額課金ではなく、継続的・反復的に発生する売上。
PF_BUCKETS = [
    ("subscription", "サブスク型", "#0B1F3A", 0),
    ("selfpay", "自費診療", "#B08A4E", 1),
    ("insurance", "保険診療", "#2F6BD6", 2),
    ("other", "その他", "#9AA3B0", 3),
]
PF_LABELS = [n for _, n, _, _ in PF_BUCKETS]
PF_COLORS = [c for _, _, c, _ in PF_BUCKETS]
PF_CODES = [c for c, _, _, _ in PF_BUCKETS]
PF_SUB, PF_SELF, PF_INS, PF_OTHER = PF_LABELS
PF_SUB_NOTE = "サブスク型：メンテ・訪問・介護など、継続的に発生する売上"

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


def read_prevyear_actual_row(ym):
    """monthly_actuals.csv から前年同月の確定実績の行を返す。無ければ None。

    経営分析で使う診療日数・外来/訪問/介護の内訳・患者数などは
    daily_rolling_forecast.json 側に前年値が無いため、ここから借りる。
    集計済みの月次データだけを読む（患者単位データは扱わない）。
    """
    if not ym or len(ym) < 7:
        return None
    try:
        prev = f"{int(ym[:4]) - 1}-{ym[5:7]}"
    except Exception:
        return None
    try:
        with open(os.path.join(DATA, HIST_DIR, F_MONTHLY_ACTUALS),
                  encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                if r.get("年月") == prev:
                    return r
    except Exception:
        return None
    return None


def read_history_rows():
    """monthly_actuals.csv の全行。直近12か月の分布とトレンド判定に使う。

    集計済みの月次データだけを読む（患者単位データは扱わない）。
    読めなければ空リストを返し、分析側は分布を使わない。
    """
    try:
        with open(os.path.join(DATA, HIST_DIR, F_MONTHLY_ACTUALS),
                  encoding="utf-8-sig", newline="") as fh:
            return [r for r in csv.DictReader(fh) if r.get("年月")]
    except Exception:
        return []


def read_target_rows():
    """monthly_targets.csv の全行。経営計画目標はこのファイルだけが正。

    スキーマの解釈（列名・未設定の扱い）は mgmt_report 側に置いてあるので、
    ここは場所を渡すだけにする。読めなければ空リスト＝目標は未設定。
    """
    if MR is None:
        return []
    try:
        return MR.read_monthly_targets(os.path.join(DATA, HIST_DIR))
    except Exception:
        return []


def relabel_v3_summary(text):
    """月初ベースの出力レポートを表示するときのラベル補正。

    dashboard_v3_summary.md の『通常営業ベースとの差』は月初時点のV2予測から
    計算した値で、画面上部（予測基準日時点の日次ローリング予測）の同名の値とは
    基準が違う。同じ名前のまま並ぶと食い違いに見えるので、表示するときだけ
    どちらの基準かを名前に入れる。元ファイルは書き換えない。
    """
    if not text:
        return text
    text = text.replace("通常営業ベースとの差",
                        "通常営業ベースとの差（月初時点のV2予測を基準にした値）")
    # 高単価型の案件レンジが算出できなかった月は 0〜0 と出力される。0円の見込みではない。
    for z in ("0〜0百万円", "0〜0万円", "0〜0円"):
        text = text.replace(z, "（算出不可）")
    # 月初時点で作った経営アクションは、予測基準日時点で生成した「今月の打ち手」と
    # 前提が違い、同じ画面に並ぶと食い違って見える。表示では見出しごと差し替える。
    out, skip = [], False
    for ln in text.splitlines():
        if ln.startswith("##"):
            skip = ("経営アクション" in ln) or ("確認すること" in ln) or ("打ち手" in ln)
            if skip:
                out.append("## 今月の経営アクション（月初時点の案・参考）")
                out.append("")
                out.append("> 月初時点で作った案のため、ここには表示していません。"
                           "実際の打ち手は上部の『今月の打ち手』"
                           "（予測基準日時点のデータから生成）をご覧ください。")
                continue
        if not skip:
            out.append(ln)
    return "\n".join(out)


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


def _p(txt):
    return f"<p>{_html.escape(str(txt))}</p>"


def _render_position(rep):
    """経営の現在地。目標・予測・参考水準を、意味ごとに分けて出す。

    3つは性格が違うので、同じ表に混ぜて並べない。
      目標      人が決めた値。1本だけ。未登録なら「未設定」と出す。
      予測      Forecast の出力。
      参考水準  過去実績を今月の外来診療日数に換算した値。目標ではない。

    参考水準の並びは金額の降順で、月によって上下が入れ替わっても文が壊れない
    名前（すべて「○○水準」）にしてある。
    """
    if not rep:
        return
    tgt = rep.get("target") or {}
    lv = rep.get("levels") or {}
    pos = rep.get("position") or {}
    if not tgt and not lv:
        return

    b = ["<div class='mfc-pos'>", "<div class='h'>経営の現在地</div>"]

    # --- 目標 ---
    b.append("<div class='grp'>目標</div><table class='pt'>")
    if tgt.get("has_target"):
        b.append(f"<tr class='tgt'><td>経営計画目標</td>"
                 f"<td class='n'>{man(tgt['target'])}</td><td class='w'></td></tr>")
        if tgt.get("note"):
            b.append(f"<tr><td colspan='3' class='note'>"
                     f"{_html.escape(tgt['note'])}</td></tr>")
    else:
        b.append("<tr class='tgt'><td>経営計画目標</td>"
                 "<td class='n na'>未設定</td><td class='w'></td></tr>")
    b.append("</table>")

    # --- 予測 ---
    f = rep.get("facts") or {}
    b.append("<div class='grp'>予測</div><table class='pt'>")
    if f.get("total") is not None:
        b.append(f"<tr class='fc'><td>着地見込み</td>"
                 f"<td class='n'>{man(f['total'])}</td>"
                 f"<td class='w'>{_perday(f.get('per_day_now'))}</td></tr>")
    if f.get("conservative") is not None:
        b.append(f"<tr><td>保守ライン</td>"
                 f"<td class='n'>{man(f['conservative'])}</td>"
                 f"<td class='w'></td></tr>")
    b.append("</table>")

    # --- 参考水準 ---
    disp = lv.get("display") or []
    if disp:
        b.append("<div class='grp'>参考水準"
                 "<span class='s'>（過去実績を今月の外来診療日数に換算した値。"
                 "目標ではありません）</span></div><table class='pt'>")
        for r in disp:
            cls = "ref" + ("" if r["main"] else " sub")
            b.append(f"<tr class='{cls}'><td>{_html.escape(r['label'])}</td>"
                     f"<td class='n'>{man(r['total'])}</td>"
                     f"<td class='w'>{_perday(r['per_day'])}</td></tr>")
        b.append("</table>")
        if lv.get("visit_care") is not None:
            b.append(f"<div class='note'>参考水準はいずれも、外来3区分"
                     f"（外来保険＋自費＋物販）の換算額に、今月の訪問保険・介護の見込み"
                     f"{man(lv['visit_care'])}を加えた総売上です。"
                     f"右の数字は外来診療日1日あたりの外来3区分です。</div>")

    for t in (pos.get("lines") or []):
        b.append(_p(t))
    b.append("</div>")
    st.markdown("".join(b), unsafe_allow_html=True)


def _perday(v):
    return "" if v is None else f"1日 {v / 10000:.1f}万円"


DECOMP_GROUPS = (
    ("患者価値・来院構造（外来＋訪問）",
     ("dental", "visits", "patients", "per_visit", "per_patient",
      "visits_per_patient")),
    ("外来生産性（外来のみ）", ("op", "per_day")),
)


def _render_decomp_table(dc):
    """売上の組み立てを、母集団ごとに群を分けた表にする。"""
    by = dc.get("by_key") or {}
    out = ["<table class='mfc-ctab'><tr><th>指標</th><th class='n'>今月</th>"
           "<th class='n'>前年同月</th><th class='n'>差</th><th class='n'>前年比</th>"
           "<th>数え方</th></tr>"]
    for gname, keys in DECOMP_GROUPS:
        rows = [by[k] for k in keys if k in by]
        if not rows:
            continue
        out.append(f"<tr class='grp'><td colspan='6'>{_html.escape(gname)}</td></tr>")
        for r in rows:
            rt = "—" if r["rate"] is None else f"{r['rate']:+.1f}%"
            out.append(
                f"<tr><td>{_html.escape(r['label'])}</td>"
                f"<td class='n'>{_dv(r['now'], r['unit'])}</td>"
                f"<td class='n'>{_dv(r['prev'], r['unit'])}</td>"
                f"<td class='n {signclass(r['diff'])}'>{_dv(r['diff'], r['unit'], True)}</td>"
                f"<td class='n {signclass(r['rate'])}'>{rt}</td>"
                f"<td class='s'>{_html.escape(r['how'])}</td></tr>")
    out.append("</table>")
    return "".join(out)


def _dv(v, unit, signed=False):
    """指標の値を単位に合わせて整形する。回数だけ小数2桁（1.61回のような値のため）。"""
    if v is None:
        return "—"
    sign = "+" if (signed and v > 0) else ""
    if unit == "回" and abs(v) < 100:
        return f"{sign}{v:,.2f}回"
    if unit == "円" and abs(v) >= 1_000_000:
        return man(v)
    return f"{sign}{v:,.0f}{unit}"


def _render_mgmt_report(rep):
    """参考レポートの冒頭。結論 → 主因 → 稼働 → 構造変化 → 月末までの論点。"""
    if not rep:
        st.markdown("<div class='mfc-rep'><div class='na'>経営分析を組み立てるための"
                    "データが読み込めませんでした。</div></div>", unsafe_allow_html=True)
        return
    blocks = ["<div class='mfc-rep'>"]
    blocks.append("<div class='h'>今月の結論</div>")
    blocks.extend(_p(t) for t in rep["conclusion"])
    blocks.append("<div class='h'>前年差の主因</div>")
    blocks.append(_p(rep["cause"]["text"]))
    if rep["capacity"]["text"]:
        blocks.append("<div class='h'>稼働の評価</div>")
        blocks.append(_p(rep["capacity"]["text"]))
    dc = rep.get("decomposition") or {}
    if dc.get("text"):
        # 患者価値・来院構造（外来＋訪問）と 外来生産性（外来だけ）は母集団が違う。
        # 表でも群を分けて、掛け算でつながるのは同じ群の中だけだと分かるようにする。
        blocks.append("<div class='h'>売上の組み立て</div>")
        blocks.append(_render_decomp_table(dc))
        blocks.append(_p(dc["text"]))
    if rep["structure"] or rep.get("trend"):
        blocks.append("<div class='h'>構造変化</div>")
        if rep["structure"]:
            blocks.append(_p(rep["structure"]["text"]))
        if rep.get("trend"):
            blocks.append(_p(rep["trend"]["text"]))
    blocks.append("<div class='h'>月末までの最大論点</div>")
    blocks.append(_p(rep["focus"]))
    if rep["notes"]:
        blocks.append("<div class='h'>データについて</div>")
        blocks.append("<div class='na'>" +
                      "<br>".join("・" + _html.escape(n) for n in rep["notes"]) + "</div>")
    blocks.append("</div>")
    st.markdown("".join(blocks), unsafe_allow_html=True)


def _render_contribution_table(rep):
    """総売上の前年差を、どの項目がいくら作っているかに分解した表。"""
    rows = (rep or {}).get("cause", {}).get("rows") or []
    if not rows:
        return
    tr = []
    for r in rows:
        cls = signclass(r["diff"]) if r["role"] != "ほぼ前年並み" else "fl"
        tr.append(f"<tr><td>{_html.escape(r['name'])}</td>"
                  f"<td class='n'>{man(r['now'])}</td>"
                  f"<td class='n'>{man(r['prev'])}</td>"
                  f"<td class='n {cls}'>{sman(r['diff'])}</td>"
                  f"<td class='n'>{MR.pct(r['rate'])}</td>"
                  f"<td>{_html.escape(r['role'])}</td></tr>")
    f = rep["facts"]
    tr.append(f"<tr><td><b>総売上</b></td><td class='n'><b>{man(f['total'])}</b></td>"
              f"<td class='n'><b>{man(f['prev_total'])}</b></td>"
              f"<td class='n {signclass(f['yoy'])}'><b>{sman(f['yoy'])}</b></td>"
              f"<td class='n'>{MR.pct(f['yoy_rate'])}</td><td></td></tr>")
    st.markdown(
        "<table class='mfc-ctab'><tr><th>項目</th><th style='text-align:right'>今月見込み</th>"
        "<th style='text-align:right'>前年同月</th><th style='text-align:right'>前年差</th>"
        "<th style='text-align:right'>増減率</th><th>全体差への向き</th></tr>"
        + "".join(tr) + "</table>", unsafe_allow_html=True)


def _render_capacity_table(rep):
    rows = (rep or {}).get("capacity", {}).get("rows") or []
    if not rows:
        return
    tr = []
    for r in rows:
        cls = signclass(r["diff_raw"])
        tr.append(f"<tr><td>{_html.escape(r['name'])}</td>"
                  f"<td class='n'>{_html.escape(r['now'])}</td>"
                  f"<td style='color:#8a94a3;font-size:11.5px'>"
                  f"{_html.escape(r.get('kind', '見込み'))}</td>"
                  f"<td class='n'>{_html.escape(r['prev'])}</td>"
                  f"<td class='n {cls}'>{_html.escape(r['diff'])}</td></tr>")
    st.markdown(
        "<table class='mfc-ctab'><tr><th>稼働の指標</th>"
        "<th style='text-align:right'>今月</th><th>区分</th>"
        "<th style='text-align:right'>前年同月（実績）</th>"
        "<th style='text-align:right'>差</th></tr>"
        + "".join(tr) + "</table>"
        "<div class='mfc-note'>「見込み」は月末着地の予測値、「実績」は予測基準日時点の"
        "実データです。前年同月はすべて確定実績です。</div>", unsafe_allow_html=True)


# ======================================================================
# 外来患者価値・外来生産性（訪問診療を含まない・確定実績のみ）
#   上の「来院・初診・キャンセル・患者数」は訪問診療を含む総数の見込み。
#   こちらは訪問診療を除いた確定実績どうしの比較で、母集団が違う。
#   同じ画面に並ぶので、見出しと但し書きで必ず区別する。
#   月末見込みは作らない（外来来院回数・外来ユニーク患者数に見込みが無いため）。
# ======================================================================
# So What は指標ごとに固定の読み方。数字そのものはレポート側が作る。
# 指標名は MR の定数で引く。MR が読めない環境（import 失敗時）でも
# 画面自体は描けなければならないので、モジュール読み込み時ではなく
# 描画時に組み立てる。
def _opv_sowhat():
    if MR is None:
        return {}
    return {
        MR.OP_PER_VISIT_LABEL:
            "1回の来院でいくら作れているか。落ちていれば来院を増やしても売上は戻らない。",
        MR.OP_PER_PATIENT_LABEL:
            "患者1人が今月いくらになっているか。来院頻度と1回あたりの積で決まる。",
        MR.OP_VISITS_PER_DAY_LABEL:
            "1日に何回来院を受けているか。枠の埋まり方をそのまま表す。",
    }


def _opv_card(r, sowhat_by_name):
    """メイン3本のカード。3本とも上がるほど良い指標なので、符号で色を決める。"""
    rt = r.get("rate")
    tp = "tp-n" if rt is None else ("tp-g" if rt > 0 else ("tp-r" if rt < 0 else "tp-n"))
    if r["prev"] == "—":
        pyline = "前年同期：比較なし"
    else:
        pyline = (f"前年同期 <b>{_html.escape(r['prev'])}</b>　"
                  f"{_html.escape(r['diff'])}{'' if rt is None else f' {rt:+.1f}%'}")
    so = sowhat_by_name.get(r["name"], "")
    sw = (f"<div class='cardsw'><span class='sw'>So What</span>{so}</div>" if so else "")
    return (f"<div class='mfc-card {tp}'><div class='lb'>{_html.escape(r['name'])}"
            f"{lab('act')}</div>"
            f"<div class='big'>{_html.escape(r['now'])}</div>"
            f"<div class='py'>{pyline}</div>{sw}</div>")


def _opv_table(rows):
    tr = []
    for r in rows:
        rt = "—" if r["rate"] is None else f"{r['rate']:+.1f}%"
        tr.append(f"<tr><td>{_html.escape(r['name'])}</td>"
                  f"<td class='n'>{_html.escape(r['now'])}</td>"
                  f"<td class='n'>{_html.escape(r['prev'])}</td>"
                  f"<td class='n {signclass(r['diff_raw'])}'>{_html.escape(r['diff'])}</td>"
                  f"<td class='n {signclass(r['rate'])}'>{rt}</td>"
                  f"<td class='s'>{_html.escape(r['how'])}</td></tr>")
    return ("<table class='mfc-ctab'><tr><th>指標</th><th class='n'>今月（確定実績）</th>"
            "<th class='n'>前年同期</th><th class='n'>差</th><th class='n'>前年比</th>"
            "<th>数え方</th></tr>" + "".join(tr) + "</table>")


def _render_outpatient_value(rep):
    ov = (rep or {}).get("outpatient_value") or {}
    st.markdown('<div class="mfc-sec">外来患者価値・外来生産性'
                '（訪問診療を含まない・確定実績）</div>', unsafe_allow_html=True)
    if not ov.get("available"):
        st.markdown("<div class='mfc-card'><div class='na'>データ未取得</div>"
                    f"<div class='py'>{_html.escape(ov.get('text', ''))}</div></div>",
                    unsafe_allow_html=True)
        return
    scope = ov.get("scope", "")
    comp = ov.get("compare_scope", "")
    st.markdown("<div class='mfc-note'><b>" + _html.escape(scope) + "</b>"
                + ("　／　<b>" + _html.escape(comp) + "</b>" if comp else "")
                + f"（〜{_html.escape(str(ov.get('cutoff') or ''))}）。"
                "分子は外来保険＋自費＋物販、分母は訪問診療を含まない外来来院回数・"
                "外来ユニーク患者数です。月末見込みは作っていません。</div>",
                unsafe_allow_html=True)
    _sw = _opv_sowhat()
    st.markdown("<div class='mfc-cards'>"
                + "".join(_opv_card(r, _sw) for r in ov.get("main", []))
                + "</div>", unsafe_allow_html=True)
    with st.expander("外来患者価値・外来生産性の詳細（外来3区分売上・来院回数・患者数）",
                     expanded=False):
        st.markdown(_opv_table(ov.get("detail", [])), unsafe_allow_html=True)
        st.markdown("<div class='mfc-rep'>" + _p(ov["text"]) + "</div>",
                    unsafe_allow_html=True)


# ======================================================================
# 予測変更の内訳（「日次予測の推移」グラフの直下）
#   グラフは「上がった／下がった」しか分からない。どの売上区分の見込みが動いて
#   そうなったのかを、スナップショット間の実データだけで添える。
#
#   経営画面に出すのは区分別だけ。「残り予測対象が1日減少」のようなバケット移動は
#   日付が進めば必ず起きる機械的な動きで、売上の良し悪しではない。
#   経営上の理由と取り違えられるため、内部監査用の折りたたみへ隔離する。
# ======================================================================
def _snap_roll(month, snap):
    """スナップショットの daily_rolling_forecast.json。無ければ None。"""
    return read_json(os.path.join(DATA, month, "snapshots", snap, F_ROLL))


def _load_forecast_change(month, snap):
    """(内訳, スナップショット一覧, 位置) を返す。作れなければ (None, [], -1)。"""
    if MR is None:
        return None, [], -1
    snaps = list_snapshots(month)          # 新しい順
    if not snaps or snap not in snaps:
        return None, [], -1
    i = snaps.index(snap)
    if i + 1 >= len(snaps):
        return None, snaps, i               # 比較できる前回が無い（月初など）
    fc = MR.build_forecast_change(_snap_roll(month, snaps[i + 1]),
                                  _snap_roll(month, snap))
    return (fc if fc.get("available") else None), snaps, i


def _fc_segment_table(fc):
    """どの売上区分の見込みが動いたか。経営画面のメイン。"""
    tr = []
    for x in fc["segments"]:
        tr.append(f"<tr><td>{_html.escape(x['label'])}</td>"
                  f"<td class='n'>{man(x['from'])}</td>"
                  f"<td class='n'>{man(x['to'])}</td>"
                  f"<td class='n {signclass(x['diff'])}'>"
                  f"{MR.yen_sman(x['diff'])}</td></tr>")
    tot = sum(x["diff"] for x in fc["segments"])
    tr.append(f"<tr><td><b>合計</b></td><td class='n'></td><td class='n'></td>"
              f"<td class='n {signclass(tot)}'><b>{MR.yen_sman(tot)}</b></td></tr>")
    return ("<table class='mfc-ctab'>"
            f"<tr><th>{_html.escape(fc['subtitle'])}</th>"
            f"<th style='text-align:right'>{_html.escape(fc['from_label'])}</th>"
            f"<th style='text-align:right'>{_html.escape(fc['to_label'])}</th>"
            "<th style='text-align:right'>変化</th></tr>"
            + "".join(tr) + "</table>")


def _render_forecast_change(fc, month, snaps, i):
    """直近の予測変更を、グラフの直下に出す。

    比較できる前回が無い月初や、内訳に必要なキーを持たない古いスナップショットでは
    ブロックごと出さない（推定値は作らない）。
    """
    if not fc:
        return
    st.markdown('<div class="mfc-sec">直近の予測変更</div>', unsafe_allow_html=True)
    st.markdown(
        "<div class='mfc-fc'>"
        f"<div class='hd'>{_html.escape(fc['label'])}</div>"
        f"<div class='big'>{man(fc['from_total'])} → {man(fc['to_total'])}"
        f"<span class='dl {signclass(fc['diff'])}'>"
        f"{MR.yen_sman(fc['diff'])} {fc['direction']}</span></div>"
        "</div>", unsafe_allow_html=True)
    st.markdown(_fc_segment_table(fc), unsafe_allow_html=True)
    st.markdown(f"<div class='mfc-rep'>{_p(fc['comment'])}</div>",
                unsafe_allow_html=True)
    st.markdown(f"<div class='mfc-note'>{_html.escape(fc['short_note'])}</div>",
                unsafe_allow_html=True)

    _render_forecast_change_history(month, snaps, i)
    _render_forecast_change_bridge(fc)


def _render_forecast_change_history(month, snaps, i, back=3):
    """過去の予測変更。常時は出さず、折りたたみに直近数件だけ置く。

    ここも区分別で並べる（バケット移動は経営の判断材料にしない）。
    """
    rows = []
    for k in range(i, min(i + back, len(snaps) - 1)):
        fc = MR.build_forecast_change(_snap_roll(month, snaps[k + 1]),
                                      _snap_roll(month, snaps[k]))
        if fc.get("available"):
            rows.append(fc)
    if len(rows) < 2:
        return
    order = ["外来保険", "自費", "物販", "訪問保険", "介護"]
    with st.expander("過去の予測変更を見る", expanded=False):
        tr = []
        for fc in reversed(rows):          # 古い順
            by = {x["label"]: x["diff"] for x in fc["segments"]}
            tds = "".join(
                f"<td class='n {signclass(by.get(lb))}'>{MR.yen_sman(by.get(lb))}</td>"
                for lb in order)
            tr.append(f"<tr><td>{_html.escape(fc['label'])}</td>"
                      f"<td class='n {signclass(fc['diff'])}'>"
                      f"<b>{MR.yen_sman(fc['diff'])}</b></td>{tds}</tr>")
        heads = "".join(f"<th style='text-align:right'>{lb}</th>" for lb in order)
        st.markdown(
            "<table class='mfc-ctab'><tr><th>基準日</th>"
            f"<th style='text-align:right'>変更額</th>{heads}</tr>"
            + "".join(tr) + "</table>"
            "<div class='mfc-note'>各行とも、区分別の合計が変更額に一致します。</div>",
            unsafe_allow_html=True)


def _render_forecast_change_bridge(fc):
    """予測構成バケットの移動。内部監査用で、経営上の理由ではない。

    一番深い折りたたみに置き、開いた最初の行で「経営上の理由ではない」と断る。
    """
    br = fc.get("bridge") or {}
    items = br.get("items") or []
    if not items:
        return
    with st.expander(br.get("title", "予測構成バケットの移動（内部監査用）"),
                     expanded=False):
        st.markdown(f"<div class='mfc-warnbox'>{_html.escape(br['caution'])}</div>",
                    unsafe_allow_html=True)
        tr = []
        for i2 in items:
            tr.append(f"<tr><td>{_html.escape(i2['label'])}</td>"
                      f"<td class='n {signclass(i2['yen'])}'>"
                      f"{MR.yen_sman(i2['yen'])}</td>"
                      f"<td class='s'>{_html.escape(i2.get('how', ''))}</td></tr>")
        res = br.get("residual")
        if res is not None:
            tr.append(f"<tr><td>説明できない残差</td>"
                      f"<td class='n {signclass(res)}'>{MR.yen_sman(res)}</td>"
                      f"<td class='s'>内訳で説明しきれなかった分（丸め誤差を含む）"
                      f"</td></tr>")
        st.markdown(
            "<table class='mfc-ctab'><tr><th>バケット</th>"
            "<th style='text-align:right'>金額</th><th>数え方</th></tr>"
            + "".join(tr) + "</table>"
            f"<div class='mfc-note'>{_html.escape(br['note'])}</div>",
            unsafe_allow_html=True)


# ======================================================================
# 確定した診療日の「事前予測 vs 実績」
#   上の「直近の予測変更」とは別のブロックにする。
#     予測変更 … 前回の基準日から月末着地見込みがどう動いたか
#     予想対実績 … 終わった1日について、始まる前の見込みと確定実績の差
#   月末見込みには残り期間の水準・予約補正も効くので、
#   2つを「AはBが原因」と結びつけない。
#
#   日別の見込みが保存され始めたのはこの機能のリリース以降なので、
#   材料がそろうまでブロックごと出さない（後付けで作らない）。
# ======================================================================
def _load_daily_vs_expected(month):
    """その月のスナップショットを集めて、事前予測 vs 実績を作る。"""
    if MR is None:
        return None
    rolls = []
    for n in list_snapshots(month):
        r = _snap_roll(month, n)
        if r:
            rolls.append(r)
    if not rolls:
        return None
    dve = MR.build_daily_vs_expected(rolls)
    return dve if dve.get("available") else None


def _dve_table(day):
    tr = []
    for sg in day["segments"]:
        cls = "" if sg["key"] != "total" else "grp"
        tr.append(f"<tr class='{cls}'><td>{_html.escape(sg['label'])}</td>"
                  f"<td class='n'>{man(sg['expected'])}</td>"
                  f"<td class='n'>{man(sg['actual'])}</td>"
                  f"<td class='n {signclass(sg['diff'])}'>"
                  f"{MR.yen_sman(sg['diff'])}</td></tr>")
    return ("<table class='mfc-ctab'><tr><th>区分</th>"
            "<th style='text-align:right'>事前予測</th>"
            "<th style='text-align:right'>確定実績</th>"
            "<th style='text-align:right'>予想比</th></tr>"
            + "".join(tr) + "</table>")


def _load_data_completeness(roll):
    """売上がまだ反映されていない診療日。旧世代のスナップショットでは None。"""
    if MR is None:
        return None
    dq = MR.build_data_completeness(roll)
    return dq if dq.get("available") else None


def _render_data_completeness(dq):
    """休診日・未来日は対象外。未反映の診療日があるときだけ出す。"""
    if not dq:
        return
    rows = []
    for x in dq["days"]:
        est = man(x["estimate"]) if x["estimate"] is not None else "—"
        rows.append(f"<tr><td>{_html.escape(str(x['label']))}</td>"
                    f"<td class='n'>{est}</td></tr>")
    st.markdown('<div class="mfc-sec">売上がまだ反映されていない診療日</div>',
                unsafe_allow_html=True)
    st.markdown(
        "<div class='mfc-fc'>"
        f"<div class='hd'>{_html.escape(str(dq['headline']))}</div>"
        "<table class='mfc-t'><thead><tr><th>診療日</th>"
        "<th class='n'>保持している見込み</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        "</div>", unsafe_allow_html=True)
    st.markdown(f"<div class='mfc-note'>{_html.escape(str(dq['note']))}</div>",
                unsafe_allow_html=True)


def _render_daily_vs_expected(dve):
    if not dve:
        return
    day = dve["latest"]
    st.markdown('<div class="mfc-sec">確定した診療日の予想対実績</div>',
                unsafe_allow_html=True)
    st.markdown(
        "<div class='mfc-fc'>"
        f"<div class='hd'>{_html.escape(str(day['date']))}</div>"
        f"<div class='big'>事前予測 {man(day['segments'][-1]['expected'])}"
        f" → 実績 {man(day['segments'][-1]['actual'])}"
        f"<span class='dl {signclass(day['diff'])}'>"
        f"{MR.yen_sman(day['diff'])}</span></div>"
        "</div>", unsafe_allow_html=True)
    st.markdown(_dve_table(day), unsafe_allow_html=True)
    st.markdown(
        f"<div class='mfc-note'>事前予測は "
        f"{_html.escape(str(day['expected_from']))} 基準日のスナップショットに"
        "保存されていた、この日がまだ残り予測だった時点の見込みです。"
        "月末着地見込みの変更額とは別のものです。</div>",
        unsafe_allow_html=True)

    past = dve["days"][1:]
    if past:
        with st.expander("過去の診療日の予想対実績を見る", expanded=False):
            tr = []
            for d in past:
                by = {sg["key"]: sg for sg in d["segments"]}
                tds = "".join(
                    f"<td class='n {signclass(by[k]['diff'])}'>"
                    f"{MR.yen_sman(by[k]['diff'])}</td>"
                    for k in ("outpatient_insurance", "selfpay", "product"))
                tr.append(f"<tr><td>{_html.escape(str(d['date']))}</td>"
                          f"<td class='n'>{man(by['total']['expected'])}</td>"
                          f"<td class='n'>{man(by['total']['actual'])}</td>"
                          f"<td class='n {signclass(by['total']['diff'])}'>"
                          f"<b>{MR.yen_sman(by['total']['diff'])}</b></td>{tds}</tr>")
            st.markdown(
                "<table class='mfc-ctab'><tr><th>診療日</th>"
                "<th style='text-align:right'>事前予測</th>"
                "<th style='text-align:right'>実績</th>"
                "<th style='text-align:right'>予想比</th>"
                "<th style='text-align:right'>外来保険</th>"
                "<th style='text-align:right'>自費</th>"
                "<th style='text-align:right'>物販</th></tr>"
                + "".join(tr) + "</table>"
                f"<div class='mfc-note'>{_html.escape(dve['note'])}</div>",
                unsafe_allow_html=True)


def _render_actions(rep):
    """今月の打ち手。1件ごとに 対象／理由／確認する数字／判断 を出す。"""
    acts = (rep or {}).get("actions") or []
    if not acts:
        st.markdown("<div class='mfc-rep'><div class='na'>今月のデータからは、"
                    "経営判断が必要な論点を特定できませんでした。</div></div>",
                    unsafe_allow_html=True)
        return
    out = []
    for i, a in enumerate(acts, 1):
        checks = "".join(f"<li>{_html.escape(str(c))}</li>" for c in a["check"])
        out.append(
            f"<div class='mfc-a'><div class='no'>ACTION {i}</div>"
            f"<div class='hd'>{_html.escape(a['headline'])}</div>"
            "<dl>"
            f"<dt>対象</dt><dd>{_html.escape(a['target'])}</dd>"
            f"<dt>理由</dt><dd>{_html.escape(a['why'])}</dd>"
            f"<dt>確認する数字</dt><dd><ul>{checks}</ul></dd>"
            f"<dt>何を判断するか</dt><dd>{_html.escape(a['decide'])}</dd>"
            "</dl></div>")
    st.markdown("".join(out), unsafe_allow_html=True)
    st.markdown("<div class='mfc-note'>ここに載せるのは、今月の残り日数で結果を動かせるものだけです。"
                "並び順は総売上への効き方と緊急度で決めています。件数は最大5件です。</div>",
                unsafe_allow_html=True)

    later = (rep or {}).get("next_month_actions") or []
    if later:
        st.markdown("<div class='mfc-sec'>来月以降の構造課題（今月の残り日数では動かせないもの）</div>",
                    unsafe_allow_html=True)
        lo = []
        for i, a in enumerate(later, 1):
            checks = "".join(f"<li>{_html.escape(str(c))}</li>" for c in a["check"])
            lo.append(
                f"<div class='mfc-a' style='border-left-color:#9AA3B0'>"
                f"<div class='no' style='color:#9AA3B0'>NEXT {i}</div>"
                f"<div class='hd'>{_html.escape(a['headline'])}</div>"
                "<dl>"
                f"<dt>対象</dt><dd>{_html.escape(a['target'])}</dd>"
                f"<dt>理由</dt><dd>{_html.escape(a['why'])}</dd>"
                f"<dt>確認する数字</dt><dd><ul>{checks}</ul></dd>"
                f"<dt>何を判断するか</dt><dd>{_html.escape(a['decide'])}</dd>"
                "</dl></div>")
        st.markdown("".join(lo), unsafe_allow_html=True)


# ======================================================================
# モデルの役割
#   名称だけを見ると取り違えるため、役割ごとに分けて表示する。
#     forecast_display_model : この画面の基準予測（ヒーロー数値）
#     champion_model         : 学習ループ側の Champion。この画面の基準予測ではない
#     challenger_model       : 検証中の Challenger（シャドー）
#     care_component_version : 介護コンポーネントの版数
#   古いスナップショットには model_roles が無いので、その場合は何も出さない。
# ======================================================================
def _roles(roll):
    return (roll or {}).get("model_roles") or {}


# ======================================================================
# 月次ライフサイクル表示
#   「今月どう着地しそうか」と「先月は確定したか」を別の情報として見せる。
#   monthly_lifecycle が無い旧スナップショットは従来表示のまま（後方互換）。
# ======================================================================
def _lifecycle(roll, meta=None):
    return ((roll or {}).get("monthly_lifecycle")
            or (meta or {}).get("monthly_lifecycle") or {})


def _ym_jp(m):
    try:
        return f"{int(m[:4])}年{int(m[5:7])}月"
    except Exception:
        return m or "—"


def _render_month_header(roll, meta, ym_jp, as_of):
    lc = _lifecycle(roll, meta)
    active = lc.get("active_forecast_month")
    if not active:
        st.markdown(
            f"<div class='mfc-meta'>対象月 <b>{ym_jp}</b>　·　予測基準日 <b>{as_of}</b></div>",
            unsafe_allow_html=True)
        return
    stale = not lc.get("is_active_forecast_month", True)
    note = ("<div style='font-size:11.5px;color:#B08A4E;margin-top:6px;'>"
            f"※ この画面のデータは {_ym_jp(lc.get('this_file_target_month'))} 分です。"
            "最新の当月データがまだ生成されていません。</div>" if stale else "")
    st.markdown(
        "<div style='display:flex;flex-wrap:wrap;gap:28px;align-items:flex-end;"
        "margin:6px 0 2px;'>"
        "<div><div style='font-size:11px;color:#8a94a3;letter-spacing:.6px;'>今月の予測</div>"
        f"<div style='font-size:26px;font-weight:800;color:#0B1F3A;line-height:1.25;'>"
        f"{_ym_jp(active)}</div></div>"
        "<div><div style='font-size:11px;color:#8a94a3;letter-spacing:.6px;'>予測基準日</div>"
        f"<div style='font-size:18px;font-weight:800;color:#3a4658;line-height:1.6;'>"
        f"{as_of}</div></div>"
        "</div>" + note,
        unsafe_allow_html=True)


def _latest_lifecycle():
    """最新スナップショットのライフサイクル（過去実績ビュー用）。"""
    for m in list_months():
        snaps = list_snapshots(m)
        for s in reversed(snaps or []):
            d = os.path.join(DATA, m, "snapshots", s)
            lc = _lifecycle(read_json(os.path.join(d, F_ROLL)),
                            read_json(os.path.join(d, F_META)))
            if lc:
                return lc
    return {}


def _render_single_month(df):
    """単月閲覧。終了した月は確定前（暫定締め）でも選べる。

    期間集計とは別ロジック。「確定していないから単月でも見せない」にはしない。
    未取得の区分は0円と断定せず『未取得』と出す。
    """
    months = list(df["年月"])
    if not months:
        return
    has_status = "close_status" in df.columns
    st.markdown("<div class='mfc-tier'><span class='n'>Month</span>1か月の結果を見る</div>",
                unsafe_allow_html=True)
    c1, _ = st.columns([1.2, 2])
    with c1:
        sel = st.selectbox("年月", list(reversed(months)), index=0, key="hist_single")
    row = df[df["年月"] == sel].iloc[0]
    status = str(row["close_status"]) if has_status else "finalized"
    prov = (status == "provisional_close")
    label = "暫定締め" if prov else "実績確定"
    color = "#B08A4E" if prov else "#2E8B57"
    # 空欄は pandas が NaN にするので、文字列化した "nan" を未取得と誤読しない
    _mv = row.get("未取得区分")
    _mv = "" if _mv is None or (isinstance(_mv, float) and _mv != _mv) else str(_mv)
    missing = [s for s in _mv.split(";") if s and s.lower() != "nan"]

    st.markdown(
        f"<div style='display:flex;gap:16px;align-items:baseline;margin:2px 0 8px;'>"
        f"<span style='font-size:22px;font-weight:800;color:#0B1F3A;'>{_ym_jp(sel)}</span>"
        f"<span style='font-size:13px;font-weight:800;color:{color};'>{label}</span>"
        + (f"<span style='font-size:11.5px;color:#B08A4E;'>"
           f"{'・'.join(missing)}は未取得（確定値ではありません）</span>" if missing else "")
        + "</div>", unsafe_allow_html=True)

    # 未取得の区分は列名ではなく表示名で持っている（介護 → 介護売上）
    MISS_COL = {"介護": "介護売上", "当月レセコン": "月間総売上"}
    miss_cols = {MISS_COL.get(m, m) for m in missing}

    def money(name, col):
        v = ("未取得" if col in miss_cols
             else f"{manv(fnum(row.get(col)))}<span style='font-size:11px;'>万円</span>")
        c = "#B08A4E" if col in miss_cols else "#3a4658"
        return (f"<div style='flex:1 1 148px;'>"
                f"<div style='font-size:10.5px;color:#8a94a3;'>{name}</div>"
                f"<div style='font-size:18px;font-weight:800;color:{c};"
                f"line-height:1.35;'>{v}</div></div>")

    def num(name, col, unit):
        return (f"<div style='flex:1 1 128px;'>"
                f"<div style='font-size:10.5px;color:#8a94a3;'>{name}</div>"
                f"<div style='font-size:18px;font-weight:800;color:#3a4658;"
                f"line-height:1.35;'>{fnum(row.get(col)):,.0f}"
                f"<span style='font-size:11px;'>{unit}</span></div></div>")

    cells = "".join([money("総売上", "月間総売上"), money("保険売上", "保険診療売上"),
                     money("外来保険", "外来保険売上"), money("訪問保険", "訪問保険売上"),
                     money("介護", "介護売上"), money("自費", "自費診療売上"),
                     money("物販", "物販売上"),
                     num("患者数", "総患者数", "人"), num("来院回数", "総来院回数", "回"),
                     num("初診数", "初診件数", "件"), num("診療日数", "診療日数", "日")])
    foot = ("暫定締めのため実績は確定していません。"
            + (f"{'・'.join(missing)}のデータが未取得です。" if missing else "")
            ) if prov else ""
    st.markdown(
        "<div style='background:#fff;border:1px solid #e3e7ee;border-radius:12px;"
        "padding:14px 18px;margin:4px 0 16px;display:flex;flex-wrap:wrap;gap:18px;'>"
        + cells + "</div>"
        + (f"<div style='font-size:11px;color:#B08A4E;margin:-10px 0 14px;'>{foot}</div>"
           if foot else ""),
        unsafe_allow_html=True)


def _render_month_close_list():
    """月ごとの締め状況。主予測から外れた月も履歴から消さずここで見られる。"""
    lc = _latest_lifecycle()
    months = lc.get("months") or {}
    if not months:
        return
    rows = []
    for m in sorted(months, reverse=True):
        v = months[m]
        if v.get("state") == "not_started":
            continue
        color = {"finalized": "#2E8B57", "provisional_close": "#B08A4E",
                 "forecasting": "#2F6BD6"}.get(v.get("state"), "#8a94a3")
        note = " / ".join(v.get("pending_labels") or [])
        rows.append(
            f"<div style='display:flex;gap:14px;align-items:baseline;padding:3px 0;'>"
            f"<span style='min-width:92px;color:#3a4658;font-weight:700;'>{_ym_jp(m)}</span>"
            f"<span style='min-width:84px;color:{color};font-weight:800;'>"
            f"{v.get('state_label')}</span>"
            f"<span style='color:#8a94a3;'>{note}</span></div>")
    st.markdown(
        "<div style='background:#f7f8fa;border:1px solid #e3e7ee;border-radius:10px;"
        "padding:12px 16px;margin:6px 0 14px;font-size:12px;'>"
        "<div style='font-size:11px;color:#8a94a3;font-weight:800;letter-spacing:.4px;"
        "margin-bottom:6px;'>月次の締め状況</div>" + "".join(rows) +
        "<div style='color:#9AA3B0;margin-top:8px;'>"
        "暫定締めの月は実績が未確定です。確定すると『実績確定』へ変わります。</div></div>",
        unsafe_allow_html=True)


def _render_forecast_composition(roll):
    """着地見込みの内訳を、意味の違う3つに分けて出す。

    「実績」と表示してよいのは confirmed_actual だけ。訪問保険・介護の月末見込みは
    確度が高くても実績ではないので『確度の高い見込み』として別に出す。
    forecast_composition が無い旧スナップショットでは何も出さない（後方互換）。
    """
    fc = (roll or {}).get("forecast_composition") or {}
    if not fc:
        return
    lab = fc.get("labels") or {}
    through = fc.get("confirmed_actual_through")
    not_imported = (fc.get("actual_data_status") == "not_yet_imported")
    if not_imported:
        actual_note = "当月レセコンデータ未取込（実績が0だったのではありません）"
    elif through:
        actual_note = f"レセコン計上済み（〜{through}）"
    else:
        actual_note = "当月のレセコン実績は未取得"
    items = [
        ("confirmed_actual", lab.get("confirmed_actual", "確定実績"), "#2E8B57",
         actual_note),
        ("locked_or_expected", lab.get("locked_or_expected", "確度の高い見込み"), "#B08A4E",
         "訪問保険・介護の月末見込み（実績ではありません）"),
        ("remaining_forecast", lab.get("remaining_forecast", "残り予測"), "#2F6BD6",
         "経過未反映＋残り期間の見込み"),
    ]
    cells = "".join(
        f"<div style='flex:1 1 180px;'>"
        f"<div style='font-size:10.5px;color:#8a94a3;'>{name}</div>"
        f"<div style='font-size:19px;font-weight:800;color:{color};line-height:1.35;'>"
        f"{manv(fnum(fc.get(key)))}<span style='font-size:11px;'>万円</span></div>"
        f"<div style='font-size:10.5px;color:#9AA3B0;'>{note}</div></div>"
        for key, name, color, note in items)
    st.markdown(
        "<div style='background:#fff;border:1px solid #e3e7ee;border-radius:12px;"
        "padding:13px 18px;margin:8px 0 4px;'>"
        "<div style='font-size:11px;color:#8a94a3;font-weight:800;letter-spacing:.4px;"
        "margin-bottom:8px;'>着地見込みの内訳</div>"
        f"<div style='display:flex;flex-wrap:wrap;gap:22px;'>{cells}"
        f"<div style='flex:1 1 180px;'>"
        f"<div style='font-size:10.5px;color:#8a94a3;'>"
        f"{lab.get('total_forecast', '現時点着地見込み')}</div>"
        f"<div style='font-size:19px;font-weight:800;color:#0B1F3A;line-height:1.35;'>"
        f"{manv(fnum(fc.get('total_forecast')))}<span style='font-size:11px;'>万円</span></div>"
        f"<div style='font-size:10.5px;color:#9AA3B0;'>3つの合計</div></div></div>"
        "<div style='font-size:11px;color:#9AA3B0;margin-top:9px;'>"
        "『確定実績』はレセコンで計上済みの金額だけです。"
        "訪問保険・介護の見込みは実績に含めていません。</div></div>",
        unsafe_allow_html=True)


def _render_prev_month_close(roll, meta=None):
    """前月の締め状況。主画面の『今月の予測』とは別枠で出す。"""
    lc = _lifecycle(roll, meta)
    prev = lc.get("previous_month")
    if not prev:
        return
    status = lc.get("previous_month_close_status")
    label = lc.get("previous_month_close_label") or status
    reasons = lc.get("previous_month_pending_labels") or []
    finalized = (status == "finalized")
    color = "#2E8B57" if finalized else "#B08A4E"
    body = (f"<span style='color:{color};font-weight:800;'>{label}</span>"
            + (f"<span style='color:#6b7686;'>　{' / '.join(reasons)}</span>"
               if reasons else ""))
    st.markdown(
        "<div style='background:#f7f8fa;border:1px solid #e3e7ee;border-left:3px solid "
        f"{color};border-radius:8px;padding:9px 14px;margin:8px 0 2px;font-size:12px;'>"
        "<span style='color:#8a94a3;font-weight:800;letter-spacing:.4px;'>前月の締め状況</span>"
        f"　<b style='color:#3a4658;'>{_ym_jp(prev)}</b>　{body}</div>",
        unsafe_allow_html=True)


def _render_model_roles(roll):
    r = _roles(roll)
    if not r:
        return
    ec = r.get("evaluation_champion_model")
    ec_status = r.get("evaluation_champion_status")
    ch = r.get("challenger_model")
    ch_status = r.get("challenger_status")
    items = [
        ("この画面の基準予測", r.get("forecast_display_model")),
        ("評価Champion（本番未採用）", f"{ec}（{ec_status}）" if ec and ec_status else ec),
        ("Challenger（シャドー）", f"{ch}（{ch_status}）" if ch and ch_status else ch),
        ("介護コンポーネント", r.get("care_component_version")),
    ]
    rows = "".join(
        f"<div style='display:flex;gap:10px;'>"
        f"<span style='color:#9AA3B0;min-width:230px;'>{k}</span>"
        f"<span style='color:#6b7686;font-weight:700;'>{v}</span></div>"
        for k, v in items if v)
    if not rows:
        return
    with st.expander("モデルの役割", expanded=False):
        st.markdown(
            "<div style='font-size:11.5px;line-height:1.9;'>" + rows +
            "<div style='color:#9AA3B0;margin-top:8px;'>"
            "評価Champion は検証上の役割で、承認済みだが本番の基準予測には未採用。"
            "シャドー運用は Challenger のみ。基準予測を差し替えるには別途の承認が必要。"
            "</div></div>",
            unsafe_allow_html=True)


# ======================================================================
# パスワード保護
# ======================================================================
def expected_password():
    """設定された閲覧パスワードを返す。未設定なら None。

    fail-closed 方針: 固定値へのフォールバックは持たない。
    Secrets も環境変数も無い場合は None を返し、呼び出し側が閲覧を拒否する。
    """
    try:
        v = st.secrets.get(PW_KEY)
        if v is not None and str(v) != "":
            return str(v)
    except Exception:
        pass
    v = os.environ.get(PW_KEY)
    return v if v else None


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
    expected = expected_password()
    if not expected:
        # 未設定のまま公開されている状態。既定値では通さない。
        with c:
            st.error("閲覧パスワードが設定されていないため、この画面は表示できません。")
            st.caption(
                f"管理者向け: Streamlit Cloud の Settings → Secrets に "
                f"`{PW_KEY}` を設定してください。設定値はここには表示されません。")
        return False
    with c:
        pw = st.text_input("閲覧パスワード", type="password", key="_pw_input")
        if st.button("表示する", type="primary", width="stretch"):
            if pw and hmac.compare_digest(str(pw), expected):
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
/* 経営計画目標。人が決めた1本だけをゴールドで、未設定はそのまま「未設定」と出す。 */
.mfc-conc .cTgt{display:inline-flex;align-items:baseline;gap:10px;font-size:12.5px;
  color:#a9b5c6;font-weight:700;letter-spacing:.6px;margin:0 0 18px;
  border-left:3px solid var(--gold2);padding-left:12px;}
.mfc-conc .cTgt b{font-size:22px;color:#f0d9a8;font-weight:800;letter-spacing:-.3px;
  font-variant-numeric:tabular-nums;}
.mfc-conc .cTgt.na b{font-size:16px;color:#8494a8;font-weight:700;}
/* バッジの中間トーン。前年総額に届かなくても日数補正では上回る月を赤で出さない。 */
/* 縮退表示用。良し悪しを示唆しない無彩色にする。 */
.mfc-conc .cBadge.flat{background:rgba(255,255,255,.14);color:#e8eef6;
  border:1px solid rgba(255,255,255,.28);box-shadow:none;}
.mfc-conc .cBadge.mid{background:linear-gradient(135deg,#cfe0f2,#7fa3c9);color:#0d2038;
  box-shadow:0 8px 20px -8px rgba(127,163,201,.6);}
.mfc-conc .cBadge.up{background:linear-gradient(135deg,#bfe8cd,#68b98a);color:#0b2417;
  box-shadow:0 8px 20px -8px rgba(104,185,138,.6);}
/* 誤読を防ぐ3点セット。総額差・診療日数差・日数補正水準との差を必ず並べて出す。 */
.mfc-conc .cFacts{display:flex;flex-wrap:wrap;gap:10px 14px;margin-top:16px;}
.mfc-conc .cFact{display:inline-flex;align-items:baseline;gap:7px;font-size:11.5px;
  color:#a9b5c6;font-weight:700;background:rgba(255,255,255,.06);
  border:1px solid rgba(255,255,255,.12);border-radius:8px;padding:7px 12px;}
.mfc-conc .cFact b{font-size:14.5px;font-weight:800;font-variant-numeric:tabular-nums;}
.mfc-conc .cFact.up b{color:#8FE3B0;}
.mfc-conc .cFact.dn b{color:#FFB3B3;}
.mfc-conc .cRLbl{grid-column:1/-1;font-size:11px;color:var(--gold2);font-weight:800;
  letter-spacing:1.6px;margin-bottom:2px;}
.mfc-conc .cRLbl span{display:block;font-size:10.5px;color:#8494a8;font-weight:600;
  letter-spacing:0;margin-top:4px;line-height:1.5;}
.mfc-conc .cItem.sub b{font-size:19px;color:#c4cedd;}
/* 予測の幅。経営の現在地より下・小さく置く。 */
.mfc-sub{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px 26px;
  background:var(--card);border:1px solid var(--line);border-radius:12px;
  padding:12px 20px;margin:12px 0 0;font-size:12px;color:var(--faint);font-weight:700;}
.mfc-sub b{margin-left:8px;font-size:15px;color:var(--navy);font-weight:800;
  font-variant-numeric:tabular-nums;}
.mfc-sub .n{font-weight:600;font-size:11.5px;margin-left:auto;}
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
/* ---- 経営レポート ---- */
.mfc-rep{background:var(--card);border:1px solid var(--line);border-radius:14px;
  padding:22px 26px;margin:10px 0 4px;box-shadow:var(--shadow);}
.mfc-rep .h{font-size:11.5px;font-weight:800;color:var(--gold);letter-spacing:1.6px;margin:24px 0 8px;}
.mfc-rep .h:first-child{margin-top:0;}
.mfc-rep p{font-size:15px;line-height:1.95;color:var(--ink);margin:0 0 7px;}
.mfc-rep p:last-child{margin-bottom:0;}
.mfc-rep b{color:var(--navy);font-weight:800;}
.mfc-rep .na{font-size:14px;color:var(--faint);line-height:1.8;}
/* 経営の現在地。目標・予測・参考水準を見た目でも分ける。
   目標=ゴールドの左罫、予測=紺の左罫、参考水準=細い灰の左罫。
   参考水準は金額の降順で並ぶので、行の色で「どれが目標か」を示す。 */
.mfc-pos{background:var(--card);border:1px solid var(--line);border-radius:14px;
  padding:22px 24px;margin:0 0 14px;}
.mfc-pos .h{font-size:11.5px;font-weight:800;color:var(--gold);letter-spacing:1.6px;
  margin:0 0 10px;}
.mfc-pos .grp{font-size:11px;font-weight:800;color:var(--faint);letter-spacing:1.2px;
  margin:14px 0 4px;}
.mfc-pos .grp .s{font-weight:600;letter-spacing:0;margin-left:6px;}
.mfc-pos .pt{width:100%;border-collapse:collapse;font-size:14px;}
.mfc-pos .pt td{padding:6px 8px;border-bottom:1px solid var(--line);}
.mfc-pos .pt td.n{text-align:right;font-weight:800;white-space:nowrap;}
.mfc-pos .pt td.w{text-align:right;color:var(--faint);font-size:12px;white-space:nowrap;}
.mfc-pos .pt td.na{color:var(--faint);font-weight:700;}
.mfc-pos .pt tr.tgt td{border-left:3px solid var(--gold);background:rgba(200,169,106,.06);}
.mfc-pos .pt tr.fc td{border-left:3px solid var(--navy);}
.mfc-pos .pt tr.ref td{border-left:3px solid var(--line);}
.mfc-pos .pt tr.ref.sub td{color:var(--faint);}
.mfc-pos .note{font-size:12px;color:var(--faint);line-height:1.75;margin:6px 0 0;}
.mfc-pos p{font-size:15px;line-height:1.95;color:var(--ink);margin:10px 0 0;}
/* 売上の組み立て表。母集団の違う指標を同じ表に並べるので、群の見出し行を入れる。 */
.mfc-ctab tr.grp td{font-size:11px;font-weight:800;color:var(--faint);
  letter-spacing:1.1px;padding-top:12px;border-bottom:1px solid var(--line);}
.mfc-ctab td.s{font-size:11.5px;color:var(--faint);}
.mfc-ctab{width:100%;border-collapse:collapse;font-size:13.5px;margin:4px 0 2px;}
.mfc-ctab th{text-align:left;font-weight:800;color:var(--faint);font-size:11.5px;
  border-bottom:1px solid var(--line);padding:7px 8px;}
.mfc-ctab td{padding:9px 8px;border-bottom:1px solid var(--line);color:var(--ink);}
.mfc-ctab td.n{text-align:right;font-variant-numeric:tabular-nums;}
.mfc-ctab .dn{color:var(--red);font-weight:800;}
.mfc-ctab .up{color:var(--green);font-weight:800;}
.mfc-ctab .fl{color:var(--faint);font-weight:700;}
.mfc-a{border:1px solid var(--line);border-left:3px solid var(--gold);border-radius:11px;
  padding:15px 19px;margin:0 0 13px;background:var(--card);}
.mfc-a .no{font-size:11px;font-weight:800;color:var(--gold);letter-spacing:1.4px;}
.mfc-a .hd{font-size:15.5px;font-weight:800;color:var(--navy);line-height:1.5;margin:3px 0 11px;}
.mfc-a dl{margin:0;display:grid;grid-template-columns:104px 1fr;gap:7px 14px;
  font-size:13.5px;line-height:1.8;}
.mfc-a dt{color:var(--faint);font-weight:800;font-size:12px;padding-top:2px;}
.mfc-a dd{margin:0;color:var(--ink);}
.mfc-a ul{margin:0;padding-left:17px;}
.mfc-a li{margin:1px 0;}
@media (max-width:700px){.mfc-a dl{grid-template-columns:1fr;gap:2px 0;}}
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
.mfc-fc{background:#F7F8FA;border:1px solid #E8EBF1;border-left:3px solid #B08A4E;
  border-radius:12px;padding:12px 18px;margin:8px 0 12px;}
.mfc-fc .hd{font-size:11px;font-weight:800;letter-spacing:1.4px;color:#B08A4E;margin-bottom:4px;}
.mfc-fc .big{font-size:20px;font-weight:800;color:#1E2430;}
.mfc-fc .dl{margin-left:14px;font-size:16px;}
.mfc-warnbox{background:#FFF7ED;border:1px solid #F3D9B5;border-left:3px solid #E0912F;
  border-radius:10px;padding:10px 14px;margin:0 0 12px;font-size:12.5px;color:#6B4A16;}
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
    # 評価Champion v2.1（本番未採用・任意）。無ければ None（基準予測表示には影響しない）。
    candidate = read_json(os.path.join(snap_dir, "candidate_forecast_v21.json"))
    # Challenger v3（参考・任意）。latest→snap_dir→candidate_forecast_v3.json。無ければ None。
    v3cand = read_json(os.path.join(snap_dir, "candidate_forecast_v3.json"))
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

    _render_month_header(roll, meta, ym_jp, as_of)
    st.markdown(
        f"<div class='mfc-meta'>{meta.get('forecast_mode','日次ローリング予測')}　·　"
        f"{_roles(roll).get('forecast_display_model') or roll.get('model_version','MDC Forecast Model v2.0')}"
        f"　·　生成 {gen_at}　·　院内検証用・閲覧専用</div>",
        unsafe_allow_html=True)
    _render_prev_month_close(roll, meta)
    _render_model_roles(roll)
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

    # 経営分析（表示専用）。前年同月の月次実績と、直前のスナップショットを材料に渡す。
    _hist_rows = read_history(month)
    _prev_fc = None
    for _r in _hist_rows:
        if _r.get("as_of_date", "") < (as_of or ""):
            _prev_fc = _r
    mgmt = None
    if MR is not None:
        try:
            mgmt = MR.build_management_report(
                roll, read_prevyear_actual_row(roll.get("target_month")), _prev_fc,
                read_history_rows(), read_target_rows())
        except Exception as e:      # 分析が落ちても数値カードは出す
            st.markdown(f"<div class='mfc-note'>経営分析の生成に失敗しました（{_html.escape(str(e))}）。"
                        "数値カードは通常どおり表示しています。<br>"
                        "引数の数が合わないという内容の場合は、画面の更新に対して"
                        "分析モジュールが古いまま動いています。アプリを再起動すると直ります。"
                        "</div>", unsafe_allow_html=True)
            mgmt = None

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
    cons = fnum(roll.get("conservative_forecast"))
    td_pct = f"（{yoy_td_rate:+.1f}%）" if isinstance(yoy_td_rate, (int, float)) else ""
    biz_pct = f"（{biz_rate:+.1f}%）" if isinstance(biz_rate, (int, float)) else ""
    r80 = f"{manv(lo)}〜{manv(hi)}" if (lo is not None and hi is not None) else "取得不可"
    yoy_pct = f"（{yoy_rate:+.1f}%）" if isinstance(yoy_rate, (int, float)) else ""
    # 縮退表示のときに出す注記。経営分析（mgmt_report）が読めないと、
    # 外来診療日数をそろえた前年同月水準を作れない。総額だけを見て良し悪しを
    # 決めると「診療日が1日少ない月の前年割れ」を悪化と誤読させるため、
    # 縮退時は事実の提示にとどめて判定語を一切出さない。
    FALLBACK_NOTE = "経営分析データを取得できないため、総額比較のみ表示しています。"

    actual_days = roll.get("actual_days_count") or 0
    remaining_days_count = roll.get("remaining_days_count") or 0
    unrecorded_days = roll.get("elapsed_unrecorded_days_count") or 0
    # 今月の診療日数は「実績のある日数＋経過したが未反映の日数＋残り日数」で決まる。
    # 月ごとに変わるのでコードに書かない。
    month_days = actual_days + unrecorded_days + remaining_days_count
    actual_daily_avg = (actual_td / actual_days) if actual_days else 0.0
    remaining_daily_avg = (remaining / remaining_days_count) if remaining_days_count else 0.0
    pace_gap = ((remaining_daily_avg / actual_daily_avg - 1) if actual_daily_avg else 0.0)
    vc = fnum(roll.get("visit_care_forecast_total"))

    # 前回スナップショットとの差。結論の1行とグラフ直下の両方で使うので先に作る。
    _fc, _fc_snaps, _fc_i = _load_forecast_change(month, snap)
    _dve = _load_daily_vs_expected(month)
    _dq = _load_data_completeness(roll)      # 売上未反映の診療日（旧世代では None）

    st.markdown('<div class="mfc-tier"><span class="n">SUMMARY</span>今日の結論'
                '<span class="ln"></span></div>', unsafe_allow_html=True)
    # 経営の現在地をヒーローへ統合する。並びは
    #   着地見込み → 経営計画目標 → 参考水準 → （下段）前年総額・保守ライン・予測レンジ。
    # Forecast の内部不確実性（保守ライン・80%レンジ）より、経営上の現在位置を先に見せる。
    smry = (mgmt or {}).get("summary") or {}
    badge = smry.get("badge") or {}
    tgt = (mgmt or {}).get("target") or {}
    # バッジは _summary が判定する（前年総額と日数補正水準を分けて見る）。
    if badge:
        b_text, b_tone = badge["text"], badge["tone"]
        facts_html = "".join(
            f"<span class='cFact {x['tone']}'>{_html.escape(x['label'])}"
            f"<b>{_html.escape(x['value'])}</b></span>"
            for x in (smry.get("facts") or []))
    else:
        # 縮退表示。良し悪しは判定せず、前年総額比という事実だけを中立に出す。
        b_text = ("前年総額比 "
                  + (f"{yoy_rate:+.1f}%" if isinstance(yoy_rate, (int, float)) else "—"))
        b_tone = "flat"
        facts_html = (f"<span class='cFact'>前年同月<b>{man(py)}</b></span>"
                      f"<span class='cFact'>前年総額比<b>{sman(yoy)}{yoy_pct}</b></span>")
    t_val = man(tgt["target"]) if tgt.get("has_target") else "未設定"
    t_cls = "" if tgt.get("has_target") else " na"
    lv_html = "".join(
        f"<div class='cItem{'' if x['main'] else ' sub'}'>"
        f"{_html.escape(x['label'])}<b>{man(x['total'])}</b></div>"
        for x in (smry.get("levels") or []))
    st.markdown(
        "<div class='mfc-conc'><div class='cLeft'>"
        f"<div class='cLbl'>今月着地見込み（{ym_jp}）</div>"
        f"<div class='cBig'>{manv(cur)}<span>万円</span></div>"
        f"<div class='cTgt{t_cls}'>経営計画目標<b>{t_val}</b></div>"
        "<div class='cRow'>"
        f"<span class='cBadge {b_tone}'>{_html.escape(b_text)}</span>"
        "</div>"
        f"<div class='cFacts'>{facts_html}</div>"
        "</div>"
        "<div class='cRight'>"
        + ("<div class='cRLbl'>参考水準"
           "<span>過去実績を今月の外来診療日数に換算した値。目標ではありません</span></div>"
           + lv_html
           if lv_html else
           f"<div class='cRLbl'>参考水準<span>{FALLBACK_NOTE}</span></div>")
        + "</div></div>", unsafe_allow_html=True)
    # 予測の内部レンジは、経営の現在地より下・小さく置く。
    st.markdown(
        "<div class='mfc-sub'>"
        f"<span>前年同月（総額）<b>{man(py)}</b></span>"
        f"<span>保守ライン<b>{man(cons)}</b></span>"
        f"<span>80%予測レンジ<b>{r80}万円</b></span>"
        "<span class='n'>保守ラインと80%レンジは予測の幅で、経営目標ではありません</span>"
        "</div>", unsafe_allow_html=True)
    top3 = (mgmt or {}).get("actions", [])[:3]
    if top3:
        rows_html = "".join(
            f"<div class='r'><span class='t'>{_html.escape(a['headline'])}</span>"
            f"<span class='d'>{_html.escape(a['why'])}</span></div>" for a in top3)
    else:
        rows_html = ("<div class='r'><span class='t'>今日の論点は特定できていません</span>"
                     "<span class='d'>前年同月の実績が読めないため、差の主因を分解できません。</span></div>")
    # 結論文は _summary が実データから組み立てる（前年総額・診療日数・日数補正水準・
    # 1日あたり・参考水準での位置・目標の有無を、この順で1つの文にする）。
    # 読めないときは、判定を書かずに事実と注記だけを出す。
    lead = _html.escape(smry.get("lead") or "")
    if not lead:
        lead = (f"今月の着地見込みは{man(cur)}、前年同月は{man(py)}で、"
                f"前年総額比は{sman(yoy)}{yoy_pct}です。{FALLBACK_NOTE}")
    # 前回の基準日からどう動いたかを、結論の1行目に添える。
    # ここでは「どの区分の見込みが変わったか」までしか言わない
    # （実績が予測を下回ったかどうかは、この材料では判定できない）。
    _fc_line = ""
    if _fc:
        _fc_line = (f"<div class='lead' style='margin-top:6px'>"
                    f"{_html.escape(_fc['headline'])}</div>")
    # 事前予測 vs 実績は、正式な材料がそろった日だけ1行出す。
    # 日別の見込みを保存し始める前の期間は何も出さない（後付けで作らない）。
    if _dve:
        _fc_line += (f"<div class='lead' style='margin-top:6px'>"
                     f"{_html.escape(_dve['headline'])}</div>")
    st.markdown(
        "<div class='mfc-act'><div class='k'>今日の結論と論点</div>"
        f"<div class='lead'>{lead}</div>{_fc_line}"
        f"<div class='rows'>{rows_html}</div></div>", unsafe_allow_html=True)

    st.markdown('<div class="mfc-sec">この見込みの前提</div>', unsafe_allow_html=True)
    st.markdown(
        "<div class='mfc-cards4'>"
        "<div class='mfc-card tp-g'><div class='lb'>診療日数の前提</div>"
        f"<div class='py'>今月の診療日数 <b>{month_days}日</b><br>実績のある日数 <b>{actual_days}日</b>"
        f"<br>経過したが未反映 <b>{unrecorded_days}日</b><br>残りの診療日 <b>{remaining_days_count}日</b></div></div>"
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

    # ===== 評価Champion v2.1（承認済み・本番未採用。シャドーではない）=====
    #   基準予測（ヒーロー/①）は一切変更しない。候補JSONがある時のみ控えめな参考カードを表示。
    if candidate and candidate.get("model_status") == "shadow":
        c_cur = fnum(candidate.get("current_model_forecast_total"))
        c_can = fnum(candidate.get("candidate_forecast_total"))
        c_diff = fnum(candidate.get("difference_vs_current"))
        c_yoy = candidate.get("candidate_yoy_rate")
        c_rem = fnum(candidate.get("candidate_remaining_daily_average"))
        d = candidate.get("difference_breakdown") or {}
        c_yoy_txt = f"{c_yoy:+.1f}%" if isinstance(c_yoy, (int, float)) else "—"
        reason = (f"外来保険の補正を1.10→1.05に縮小（約{sman(fnum(d.get('insurance_adjust_reduced')))}万）、"
                  f"自費の一律補正を廃止（約{sman(fnum(d.get('selfpay_adjust_removed')))}万）、"
                  f"物販の一律補正を廃止（約{sman(fnum(d.get('product_adjust_removed')))}万）。"
                  f"件数（来院・患者・初診）の見込みは現行のまま変更なし。")
        st.markdown(
            "<div class='mfc-sec' style='opacity:.72'>評価Champion v2.1（本番未採用）"
            "<span style='font-size:10px;font-weight:800;letter-spacing:1.6px;color:#9AA3B0;"
            "border:1px solid #cfd6df;border-radius:999px;padding:2px 9px;margin-left:10px;"
            "vertical-align:middle;'>評価Champion · 本番未採用</span></div>",
            unsafe_allow_html=True)
        st.markdown(
            "<div style='background:#f4f6f9;border:1px solid #dde3ea;border-left:3px solid #9AA3B0;"
            "border-radius:10px;padding:14px 18px;color:#3a4658;'>"
            "<div style='font-size:12px;font-weight:800;color:#8a94a3;letter-spacing:.4px;margin-bottom:8px;'>"
            "評価上のChampionとして承認済み。現在の基準予測には採用していません</div>"
            "<div style='display:flex;flex-wrap:wrap;gap:22px;align-items:baseline;'>"
            f"<div><div style='font-size:10.5px;color:#8a94a3;'>現行基準予測 v2.0</div>"
            f"<div style='font-size:19px;font-weight:800;color:#5a6472;'>{manv(c_cur)}<small style='font-size:11px'>万円</small></div></div>"
            f"<div><div style='font-size:10.5px;color:#8a94a3;'>v2.1予測（本番未採用）</div>"
            f"<div style='font-size:19px;font-weight:800;color:#3a4658;'>{manv(c_can)}<small style='font-size:11px'>万円</small></div></div>"
            f"<div><div style='font-size:10.5px;color:#8a94a3;'>差額</div>"
            f"<div style='font-size:16px;font-weight:800;color:#B08A4E;'>{sman(c_diff)}<small style='font-size:11px'>万円</small></div></div>"
            f"<div><div style='font-size:10.5px;color:#8a94a3;'>候補の前年比</div>"
            f"<div style='font-size:16px;font-weight:800;color:#5a6472;'>{c_yoy_txt}</div></div>"
            f"<div><div style='font-size:10.5px;color:#8a94a3;'>候補 残り1診療日あたり</div>"
            f"<div style='font-size:16px;font-weight:800;color:#5a6472;'>{c_rem/10000:.1f}<small style='font-size:11px'>万円/日</small></div></div>"
            "</div>"
            f"<div style='font-size:11.5px;color:#6b7686;line-height:1.6;margin-top:10px;'>"
            f"<b style='color:#8a94a3;'>差が出る主な理由：</b>{reason}</div>"
            "<div style='font-size:11px;color:#8a94a3;margin-top:8px;font-weight:700;'>"
            "※ v2.1は評価上のChampionとして承認済みですが、現在の基準予測には採用していません。</div>"
            "</div>", unsafe_allow_html=True)
    else:
        # 候補JSONが無い日は、参考カードを出さない（アプリは落とさない）。
        st.markdown(
            "<div class='mfc-note' style='opacity:.6'>評価Champion v2.1（本番未採用）：この基準日では未生成のため非表示。</div>",
            unsafe_allow_html=True)

    # ===== Challenger モデル v3（検証中・シャドー）=====
    #   画面の基準予測（ヒーロー）は forecast_display_model = v2.0系。
    #   v2.1 は評価上の Champion として承認済みだが本番未採用。シャドーではない。
    #   シャドー運用は v3 だけ。v3カードは v2.1 を「比較基準」として並べるだけで、
    #   画面の基準予測を置き換えない。名称の役割は「モデルの役割」に明示する。
    if v3cand and v3cand.get("model_status") == "shadow":
        w3_total = fnum(v3cand.get("forecast_total"))
        w3_v21 = fnum(v3cand.get("v21_forecast_total"))
        w3_diff = fnum(v3cand.get("difference_vs_v21"))
        w3_prog = v3cand.get("progress")
        w3_ew = v3cand.get("ensemble_weight")
        w3_vw = v3cand.get("v21_weight")
        i80l = fnum(v3cand.get("interval_80_low")); i80h = fnum(v3cand.get("interval_80_high"))
        i90l = fnum(v3cand.get("interval_90_low")); i90h = fnum(v3cand.get("interval_90_high"))
        prog_pct = f"{w3_prog*100:.0f}%" if isinstance(w3_prog, (int, float)) else "—"
        # 差額：正=v3がv2.1より高い / 負=低い。0は同額。
        if isinstance(w3_diff, (int, float)):
            if abs(w3_diff) < 1:
                diff_txt = "±0円（v2.1と同額）"
            elif w3_diff < 0:
                diff_txt = f"▲{intv(-w3_diff)}円"
            else:
                diff_txt = f"+{intv(w3_diff)}円"
        else:
            diff_txt = "—"
        same_note = ("進捗率が40%以上のため、v3は現在v2.1を100%採用しています。"
                     if isinstance(w3_ew, (int, float)) and w3_ew == 0.0 else
                     "進捗率に応じてEnsembleとv2.1をブレンドしています。")
        model_expl = (v3cand.get("explanation", {}) or {}).get("text", "")
        st.markdown(
            "<div class='mfc-sec' style='opacity:.72'>Challenger モデル v3（検証中）"
            "<span style='font-size:10px;font-weight:800;letter-spacing:1.6px;color:#9AA3B0;"
            "border:1px solid #cfd6df;border-radius:999px;padding:2px 9px;margin-left:10px;"
            "vertical-align:middle;'>CHALLENGER · SHADOW</span></div>", unsafe_allow_html=True)
        st.markdown(
            "<div style='background:#f4f6f9;border:1px solid #dde3ea;border-left:3px solid #9AA3B0;"
            "border-radius:10px;padding:14px 18px;color:#3a4658;'>"
            "<div style='font-size:12px;font-weight:800;color:#8a94a3;letter-spacing:.4px;margin-bottom:8px;'>"
            "検証中のChallengerモデル（現在の正式な基準予測ではありません）</div>"
            "<div style='display:flex;flex-wrap:wrap;gap:22px;align-items:baseline;'>"
            f"<div><div style='font-size:10.5px;color:#8a94a3;'>比較基準 v2.1（評価Champion・本番未採用）</div>"
            f"<div style='font-size:18px;font-weight:800;color:#5a6472;'>{intv(w3_v21)}<small style='font-size:11px'>円</small></div></div>"
            f"<div><div style='font-size:10.5px;color:#8a94a3;'>v3(Challenger)予測</div>"
            f"<div style='font-size:18px;font-weight:800;color:#3a4658;'>{intv(w3_total)}<small style='font-size:11px'>円</small></div></div>"
            f"<div><div style='font-size:10.5px;color:#8a94a3;'>v2.1との差額</div>"
            f"<div style='font-size:16px;font-weight:800;color:#B08A4E;'>{diff_txt}</div></div>"
            f"<div><div style='font-size:10.5px;color:#8a94a3;'>進捗率</div>"
            f"<div style='font-size:16px;font-weight:800;color:#5a6472;'>{prog_pct}</div></div>"
            f"<div><div style='font-size:10.5px;color:#8a94a3;'>重み（Ensemble / v2.1）</div>"
            f"<div style='font-size:16px;font-weight:800;color:#5a6472;'>{w3_ew} / {w3_vw}</div></div>"
            "</div>"
            f"<div style='font-size:11.5px;color:#6b7686;line-height:1.6;margin-top:10px;'>"
            f"<b style='color:#8a94a3;'>暫定予測区間：</b>"
            f"80% {intv(i80l)} 〜 {intv(i80h)}円 ／ 90% {intv(i90l)} 〜 {intv(i90h)}円"
            "<span style='color:#8a94a3;'>（予測区間は暫定較正中）</span></div>"
            f"<div style='font-size:11px;color:#6b7686;line-height:1.6;margin-top:6px;'>"
            f"<b style='color:#8a94a3;'>モデル説明：</b>{model_expl}</div>"
            f"<div style='font-size:11px;color:#6b7686;margin-top:4px;'>{same_note} 基準日 {v3cand.get('as_of_date','—')}</div>"
            "<div style='font-size:11px;color:#8a94a3;margin-top:8px;font-weight:700;'>"
            "※ v3は検証中の候補モデルです。現在の正式な基準予測ではありません。</div>"
            "</div>", unsafe_allow_html=True)
    else:
        st.markdown(
            "<div class='mfc-note' style='opacity:.6'>Challenger モデル v3（検証中）：本日のv3は未生成のため非表示。</div>",
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
        f"<div class='py'>保守 {man(cons)}／前年月末 {man(py)}<br>"
        f"前年総額比 {sman(yoy)}{yoy_pct}</div></div>"
        "</div>", unsafe_allow_html=True)

    _render_forecast_composition(roll)
    cal_cls = "red" if (yoy_td is not None and yoy_td < 0) else "green"
    biz_cls = "green" if (biz_diff is not None and biz_diff >= 0) else "red"
    st.markdown(
        "<div class='mfc-cmp'>"
        f"<span class='chip {cal_cls}'><span class='lbl'>暦同日</span><b>{smanv(yoy_td)}万円</b><em>{td_pct}</em></span>"
        f"<span class='chip {biz_cls}'><span class='lbl'>同じ診療日数</span><b>{smanv(biz_diff)}万円</b><em>{biz_pct}</em></span>"
        f"<span class='muted'>暦の同じ日で比べると当年{cur_days}日／前年{py_days}日と診療日数がずれる"
        f"（木曜休診）ため、同じ診療日数まで累計した前年との比較も並べています。"
        f"訪問・介護は入力が遅れるため、月末着地に分けて足しています。</span>"
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
    # 数字の読み方が変わるので、データの欠けは予測変更より先に知らせる。
    _render_data_completeness(_dq)
    # グラフは上下しか分からないので、どの区分が動いてそうなったかを直下に添える。
    _render_forecast_change(_fc, month, _fc_snaps, _fc_i)
    # 別ブロック。月末見込みの変化（上）と、1日の予想対実績（下）は違うもの。
    _render_daily_vs_expected(_dve)
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
        f"<div class='py'>過去12か月平均から、外来とは分けて見込む（予約ペース補正なし）</div></div>"
        "</div>", unsafe_allow_html=True)
    st.markdown(
        f"<div class='mfc-note'>① ＋ ② ＋ ③ ＋ ④ ＝ 月末着地見込み <b>{man(cur)}</b>。"
        "訪問・介護は入力が遅れるため外来の予約ペースとは分けて、過去12か月平均で見込んでいます。"
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
            f"（<b>{rg_mult:.2f}x</b>）を反映。上下限 0.85〜1.10。"
            "訪問・介護にはこの補正をかけず、④で分けて見込んでいます。</div>",
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
                       "空いた枠を再予約で埋め、来院数の落ち込みを防ぐ。</div></div>")
    else:
        cancel_card = ("<div class='mfc-card tp-r'><div class='lb'>キャンセル率"
                       "<span class='lab lab-ref'>データ未取得</span></div>"
                       "<div class='na'>データ未取得</div></div>")

    st.markdown(
        "<div class='mfc-cards4'>"
        + patient_card
        + cnt_card("来院回数", vis.get("forecast"), vis.get("prevyear"), "回", "est",
                   "来院回数の前年差はそのまま売上の下押しになる。他の曜日への振替と空き枠の再予約で戻す。", "tp-n")
        + cnt_card("初診", sho.get("forecast"), sho.get("prevyear"), "件", "est",
                   "初診のうち自費の相談・治療計画まで進んだ件数を確認し、自費につなげる。", "tp-o")
        + cancel_card
        + "</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='mfc-note'>来院回数・初診は当月着地見込み（確定＋残り見込み）。"
        "総患者数は当月レセコンの受診者を重複排除した確定人数を基に月末見込みを算出"
        "（人数のみ・個人情報は非保持）。キャンセル率・予約構成は as_of時点の登録済み予約の実データ。</div>",
        unsafe_allow_html=True)

    # ----- 外来患者価値・外来生産性（訪問診療を含まない確定実績）-----
    # 上のカードは訪問診療を含む総数の月末見込み。ここは訪問を除いた確定実績で、
    # 母集団も時点も違うため、続けて並べたうえで見出しと但し書きで区別する。
    _render_outpatient_value(mgmt)

    # ----- 予約構成（折りたたみ）-----
    with st.expander("予約ポートフォリオ（型別・登録済み予約）", expanded=False):
        comp = sup.get("reservation_composition") or {}
        if comp.get("available"):
            types = comp.get("types") or {}
            # 左＝データ上の分類キー、右＝画面に出す呼び方。キーは変えない。
            order = [("継続管理型", "定期管理の患者", "tp-g"),
                     ("都度治療型", "その都度の治療", "tp-n"),
                     ("高単価型", "高額な自費が見込まれる予約", "tp-o"),
                     ("混合・判定保留", "分類できていない予約", "tp-r")]
            cards = []
            for name, disp, tp in order:
                t = types.get(name) or {}
                cv = t.get("current"); pv = t.get("prevyear")
                diff = (cv - pv) if (cv is not None and pv is not None) else None
                pyline = (f"前年同月(実績) <b>{intv(pv)}件</b>　{sint(diff)}{pct_of(cv, pv)}"
                          if pv is not None else "前年同月：取得不可")
                cards.append(
                    f"<div class='mfc-card {tp}'><div class='lb'>{disp}{lab('act')}</div>"
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
    _render_position(mgmt)
    _render_mgmt_report(mgmt)

    with st.expander("売上内訳・判断サマリー（詳細）", expanded=False):
        st.markdown("<div class='mfc-sec'>総売上の前年差を、どの項目が作っているか</div>",
                    unsafe_allow_html=True)
        _render_contribution_table(mgmt)
        st.markdown(f"<div class='mfc-note'>{_html.escape((mgmt or {}).get('cause', {}).get('text', ''))}"
                    "</div>", unsafe_allow_html=True)

        st.markdown("<div class='mfc-sec'>稼働（診療日数・来院・単価）</div>", unsafe_allow_html=True)
        _render_capacity_table(mgmt)

        st.markdown("<div class='mfc-sec'>自費の見立て</div>", unsafe_allow_html=True)
        st.markdown("<div class='mfc-judge'>"
                    + _html.escape(((mgmt or {}).get("selfpay") or {}).get("text",
                        "自費の前年比較に必要なデータが取得できません。"))
                    + "</div>", unsafe_allow_html=True)

        # 「通常営業ベースとの差」は下の出力レポート（月初ベース）にも同じ名前で出るため、
        # どちらの基準の数字かを名前に入れて区別する。
        st.markdown("<div class='mfc-sec'>診療日数の変化（通常営業だった場合との差）</div>",
                    unsafe_allow_html=True)
        _stru_txt = ((mgmt or {}).get("structure") or {}).get("text")
        st.markdown(
            "<div class='mfc-judge'>"
            f"<b>予測基準日 {as_of} 時点の日次ローリング予測を基準にした差</b><br>"
            + (_html.escape(_stru_txt) if _stru_txt else
               f"通常営業だった場合の見込み <b>{man(base)}</b> に対し着地見込みは "
               f"<b>{man(cur)}</b>、差は <b>{sman(gap)}</b> です。")
            + "<br><span style='color:#8a94a3'>下の『出力レポート確認』に出てくる同じ名前の差は、"
              "月初時点のV2予測を基準にした別の数字です。基準日が違うため一致しません。</span>"
            "</div>", unsafe_allow_html=True)

        st.markdown("<div class='mfc-sec'>区分別の月末見込み</div>", unsafe_allow_html=True)

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
                f"訪問 <b>{man(vins)}</b>／介護 <b>{man(care)}</b>。訪問・介護は入力が遅れるため、"
                "過去12か月平均から分けて見込んでいます（未入力を0円とは扱いません）。</div>",
                unsafe_allow_html=True)

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

    with st.expander("今月の打ち手（院長・事務局向け）", expanded=True):
        _render_actions(mgmt)

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
                     caption="【参考表示・月初ベース】dashboard_v3（正データではありません／"
                             "正データは上部カード）。この画像の『通常営業ベースとの差』は"
                             "月初時点のV2予測を基準にした値で、"
                             "上部の予測基準日時点の差とは一致しません。")
        else:
            st.caption("このスナップショットの dashboard_v3.png はありません。")
        if summary_md:
            with st.expander("summary.md の内容（参考・月初ベース）", expanded=False):
                st.info("参考表示です。正データは上部の日次ローリング予測カードです。"
                        "この中の『通常営業ベースとの差』は月初時点のV2予測を基準にした値で、"
                        "上部に出ている予測基準日時点の同名の差とは基準が違うため一致しません。")
                st.markdown(relabel_v3_summary(summary_md))
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
            "data_cutoff_date", "actual_data_complete_through", "unrecorded_days_count",
            "reservation_data_through", "model_version", "pipeline_exit_code"]} or meta)
        st.caption("actual_data_through は data cutoff（基準日の前日）です。"
                   "実績が完全に揃った最終日は actual_data_complete_through を見てください。")
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
            "- 自費は月ごとの振れが大きく、前年差の主因になりやすい区分です。\n"
            "  高額な自費案件は院内の管理表で1件ずつ確認してください。\n"
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
def _load_actuals(mtime):
    """月次実績を読む。引数 mtime はキャッシュ無効化のためだけに受け取る。

    **引数名を _ で始めないこと。** st.cache_data は `_` 始まりの引数を
    ハッシュ対象から除外するため、`_mtime` にするとキャッシュキーが実質固定になり、
    ファイルを更新してもプロセスが生きている限り古い内容を返し続ける。
    実際、これが原因で更新済みの月が画面に現れなかった。
    """
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

# 月次グラフの横軸は「暦の1か月ごと」に1目盛り。
# 時間軸のまま目盛り粒度を自動に任せると、表示期間が短い月（今年度が4か月など）で
# 週ごとの目盛りが選ばれ、それを %Y-%m で整形するので同じ月名が4〜5回並ぶ。
# 目盛りの「本数」ではなく「間隔」を固定するのが要点。データ側は一切変えない。
MONTH_TICK = {"interval": "month", "step": 1}


def chart_total_sales(p):
    """月次総売上の推移（棒）。"""
    import pandas as pd
    import altair as alt
    d = pd.DataFrame({"月": _ymdate(p["年月"]), "総売上": p["月間総売上"] / 1e4})
    ch = alt.Chart(d).mark_bar(color="#0B1F3A", opacity=.92).encode(
        x=alt.X("月:T", axis=alt.Axis(format="%Y-%m", title=None, labelAngle=-55,
                                      tickCount=MONTH_TICK)),
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
        x=alt.X("月:T", axis=alt.Axis(format="%Y-%m", title=None, labelAngle=-55,
                                      tickCount=MONTH_TICK)),
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
        x=alt.X("月:T", axis=alt.Axis(format="%Y-%m", title=None, labelAngle=-55,
                                      tickCount=MONTH_TICK)),
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

    _render_month_close_list()

    if df is None or df.empty:
        st.warning("過去実績データがありません。"
                   "ローカルで scripts/build_history_aggregates.py を実行し、"
                   "data/history/monthly_actuals.csv を配置してください。")
        return

    meta = read_json(hist_path(F_HISTORY_META)) or {}

    # 単月閲覧と期間集計は別ロジック。
    #   単月閲覧 : 暫定締めの月も選べる（終了した月は確定前でも結果を見られる）
    #   期間集計 : 既定は確定月のみ。暫定月を混ぜたいときだけ明示的に選ぶ
    all_months = list(df["年月"])
    _has_status = "close_status" in df.columns
    fin_df = df[df["close_status"] == "finalized"] if _has_status else df
    fin_months = list(fin_df["年月"])

    _render_single_month(df)

    # ---- 期間選択 ----
    st.markdown("<div class='mfc-tier'><span class='n'>Period</span>期間を集計する</div>",
                unsafe_allow_html=True)
    include_prov = False
    if _has_status and len(all_months) > len(fin_months):
        include_prov = st.checkbox(
            "暫定締め月を含める", value=False, key="hist_include_prov",
            help="暫定締めの月は実績が未確定です。既定では期間集計に含めません。")
    agg_df = df if include_prov else fin_df
    months = list(agg_df["年月"])
    if not months:
        st.warning("期間集計に使える確定月がありません。")
        return

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
    p = agg_df[(agg_df["年月"] >= lo) & (agg_df["年月"] <= hi)]

    if p.empty:
        st.warning(f"選択した期間（{lo} 〜 {hi}）に該当する月がありません。"
                   f"収録範囲は {months[0]} 〜 {months[-1]} です。")
        return

    a_lo, a_hi = p["年月"].iloc[0], p["年月"].iloc[-1]
    _prov_in_p = (list(p.loc[p["close_status"] == "provisional_close", "年月"])
                  if _has_status else [])
    _scope = ("暫定値を含みます（" + "・".join(_ym_jp(m) for m in _prov_in_p) + "）"
              if _prov_in_p else "確定月のみ")
    _scope_color = "#B08A4E" if _prov_in_p else "#8a94a3"
    st.markdown(f"<div class='mfc-meta'>対象期間 <b>{a_lo} 〜 {a_hi}</b>（{len(p)}か月）"
                f"｜収録範囲 {all_months[0]} 〜 {all_months[-1]}"
                f"｜<span style='color:{_scope_color};font-weight:800;'>{_scope}</span></div>",
                unsafe_allow_html=True)
    # 集計に使う前年同期も同じ範囲から取る（暫定月の混入条件をそろえる）
    df = agg_df

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
def _load_portfolio(mtime):      # 引数名を _ で始めないこと（下の注記参照）
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


PF_CLOSE_FINALIZED = "finalized"


def pf_finalized_only(df):
    """確定月だけに絞る。close_status 列が無い古い形式はそのまま返す。

    履歴として持つことと、既定の集計へ含めることは別。暫定締めの月は実績が
    まだ動くので、期間集計の既定からは外す（過去実績画面と同じ考え方）。
    """
    if df is None or "close_status" not in df.columns:
        return df
    return df[df["close_status"] == PF_CLOSE_FINALIZED]


def pf_provisional_months(df):
    """暫定締めとして収録されている月の一覧。"""
    if df is None or "close_status" not in df.columns:
        return []
    return sorted(df.loc[df["close_status"] != PF_CLOSE_FINALIZED, "年月"].unique())


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
    """分類別の積み上げ売上推移。サブスク型を最下段に固定。"""
    import pandas as pd
    import altair as alt
    d = wide.reset_index()
    d["月"] = _ymdate(d["年月"])
    long = d.melt(id_vars="月", value_vars=PF_LABELS, var_name="分類", value_name="売上")
    long["売上"] = long["売上"] / 1e4
    long["順"] = long["分類"].map({n: o for _, n, _, o in PF_BUCKETS})
    ch = alt.Chart(long).mark_bar().encode(
        x=alt.X("月:T", axis=alt.Axis(format="%Y-%m", title=None, labelAngle=-55,
                                      tickCount=MONTH_TICK)),
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
def _load_pf_forecast(path, mtime):   # 引数名を _ で始めないこと（下の注記参照）
    return read_json(path)


def read_pf_forecast():
    """**当月**（active_forecast_month）の portfolio_forecast.json だけを読む。

    以前は全月を新しい順に走査して最初に見つかったものを返していたため、
    当月分が未生成だと前月のポートフォリオを「当月見込み」として表示していた。
    前月データを当月として代用しない。当月分が無ければ None（＝データなし表示）。
    """
    months = list_months()
    if not months:
        return None
    lc = _latest_lifecycle()
    active = lc.get("active_forecast_month")
    folder = active.replace("-", "_") if active else months[0]
    if folder not in months:
        return None
    latest = read_json(os.path.join(DATA, folder, F_LATEST)) or {}
    snap = os.path.basename(str(latest.get("latest_snapshot_dir", "")).rstrip("/"))
    if not snap:
        return None
    p = os.path.join(DATA, folder, "snapshots", snap, F_PF_FORECAST)
    if not os.path.isfile(p):
        return None
    try:
        fc = _load_pf_forecast(p, os.path.getmtime(p))
    except Exception:
        return None
    # 旧4分類（ストック型/高単価型…）で作られたスナップショットは表示に使わない。
    # 分類の定義が違うものを新しい名前で並べると、そのまま誤読になる。
    # 次の日次更新で新分類のスナップショットが出れば自動で復帰する。
    if not fc or {b.get("分類コード") for b in (fc.get("buckets") or [])} != set(PF_CODES):
        return None
    return fc


def last_pf_forecast_asof():
    """portfolio_forecast.json を含む最新スナップショットの as_of 日付（YYYY-MM-DD）を返す。無ければ None。

    ※ 古い当月見込みを自動で代用表示はしない。「最後に生成された日」を示す参照用のみ。
    """
    for month in list_months():            # 新しい月から
        for snap in list_snapshots(month):  # 新しい日から
            p = os.path.join(DATA, month, "snapshots", snap, F_PF_FORECAST)
            if os.path.isfile(p):
                return asof_from_dir(snap)
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
    sp = fc["selfpay_range"]

    # ---- A. 警告帯 ----
    st.markdown(
        f"<div class='pf-warn'>⚠ <b>これは確定実績ではありません。</b>"
        f"{as_of} 時点の実績・予約状況・過去傾向から算出した<b>当月見込み</b>です。"
        "分類別の金額は按分による推定であり、確定した内訳ではありません。"
        "月末後に確定実績と照合します。</div>", unsafe_allow_html=True)

    # ---- B. ヒーロー ----
    sub_pct = share[PF_SUB]
    sp_pct = share[PF_SELF]
    st.markdown(
        "<div class='pf-hero est'>"
        "<div class='l'>"
        f"<div class='k'>Forecast · as of {_html.escape(as_of)}</div>"
        f"<div class='big'>{sub_pct:.1f}<span>%</span></div>"
        f"<div class='cap'>が{PF_SUB}の見込み</div>"
        f"<div class='sub'>基準予測 {manv(total)} 万円のうち、"
        f"{manv(amt[PF_SUB])} 万円がメンテ・訪問・介護など継続的に発生する売上の見込みです。</div>"
        "</div>"
        "<div class='r'>"
        f"<div class='it'>{PF_SELF}見込み<b>{manv(amt[PF_SELF])}"
        "<span style='font-size:12px'> 万円</span></b></div>"
        f"<div class='it'>自費依存度<b>{sp_pct:.1f}<span style='font-size:12px'> %</span></b></div>"
        f"<div class='rng'>{PF_SELF} 参考レンジ "
        f"<b>{manv(sp['参考下限'])} 〜 {manv(sp['参考上限'])} 万円</b><br>"
        f"（月次変動係数 {sp['使用した変動係数']}% による±1σ・確定値ではありません）</div>"
        "</div></div>", unsafe_allow_html=True)

    # ---- C. KPIカード ----
    row1 = "".join([
        pf_card(f"{PF_SUB}見込み", manv(amt[PF_SUB]), "万円",
                f"構成比 <b>{share[PF_SUB]:.1f}%</b>", "a-navy"),
        pf_card(f"{PF_SELF}見込み", manv(amt[PF_SELF]), "万円",
                f"構成比 <b>{share[PF_SELF]:.1f}%</b>", "a-gold"),
        pf_card(f"{PF_INS}見込み", manv(amt[PF_INS]), "万円",
                f"構成比 <b>{share[PF_INS]:.1f}%</b>", "a-blue"),
        pf_card(f"{PF_OTHER}見込み", manv(amt[PF_OTHER]), "万円",
                f"構成比 <b>{share[PF_OTHER]:.1f}%</b>", "a-gray"),
    ])
    row2 = "".join([
        pf_card("サブスク比率", f"{sub_pct:.1f}", "%", "当月見込み", "a-green", small=True),
        pf_card("自費依存度", f"{sp_pct:.1f}", "%", "当月見込み", "a-gold", small=True),
        pf_card(f"{PF_SELF} 参考レンジ", f"{manv(sp['参考下限'])}〜{manv(sp['参考上限'])}", "万円",
                f"変動係数 <b>{sp['使用した変動係数']}%</b>・確定値ではありません", "a-gold",
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
        f"<b>分類方法</b>　{PF_SELF}と{PF_OTHER}（物販）は会計区分の見込みそのままで、"
        "推定が入るのはサブスク型に入れる継続管理の保険分だけです。"
        f"{ap.get('名称', '想定売上加重按分')}で、予約1件あたりの想定売上（{lt}）により"
        "継続管理型の金額を求め、確定実績の保険内訳比を掛けて保険分を取り出しています。"
        f"予約を伴わない来院と突合の残差として {manv(ap.get('残差先取り額', 0))} 万円を先取りし、"
        "残りを登録済み予約から按分しました。キャンセル済みの予約は按分から除外しています。<br>"
        f"<b>訪問・介護</b>　{manv(fc['visit_care_forecast_total'])} 万円はサブスク型に含めています。"
        "反復性が高く、確定実績の売上ポートフォリオと同じ定義です。<br>"
        f"<b>{PF_SELF}の参考レンジ</b>　確定実績から求めた月次変動係数による±1σの目安であり、"
        f"予測区間ではありません。{PF_SELF}は月ごとの振れが大きいため、点推定だけでは誤解を招きます。<br>"
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
        "<div class='mfc-sub'>この医院の売上が、継続的に発生する安定収益なのか、"
        "自費に依存しているのかを見る画面です。"
        f"{PF_SUB_NOTE}。</div>",
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
            last_asof = last_pf_forecast_asof()
            msg = ("当月見込みデータは本日分が未生成です。\n\n"
                   "日次更新時に当月ポートフォリオ見込みを生成できなかったため、"
                   "現在は確定実績のみ表示しています。日次更新ログを確認してください。")
            if last_asof:
                msg += f"\n\n最後に生成された当月見込み：{last_asof}"
            st.warning(msg)

    if dtype == PF_DATA_FORECAST and fc:
        render_portfolio_forecast(fc, df)
        return

    meta = read_json(hist_path(F_PORTFOLIO_META)) or {}
    # 期間集計は既定で確定月のみ。暫定締め月は「履歴にはあるが既定では集計しない」。
    prov = pf_provisional_months(df)
    include_prov = False
    if prov:
        include_prov = st.checkbox(
            "暫定締め月を含める", value=False, key="pf_include_prov",
            help="暫定締めの月は実績が未確定です。既定では期間集計に含めません。")
    agg_df = df if include_prov else pf_finalized_only(df)
    if agg_df is None or agg_df.empty:
        st.warning("期間集計に使える確定月がありません。")
        return
    wide_all = pf_pivot(agg_df)
    months = list(wide_all.index)
    if prov:
        _p = "・".join(prov)
        st.markdown(
            f"<div class='pf-pnote'>暫定締めの月（{_html.escape(_p)}）は"
            + ("集計に含めています。実績はまだ動きます。"
               if include_prov else "既定では集計に含めていません。")
            + "</div>", unsafe_allow_html=True)

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
    sub_pct = shares[PF_SUB]
    sp_pct = shares[PF_SELF]
    sp_m = wide[PF_SELF]
    # 振れ幅は2か月以上ないと意味を持たない（単月では常に1.00倍になる）
    swing = (sp_m.max() / sp_m.min()) if (len(wide) >= 2 and sp_m.min() > 0) else None
    driver = cvs.drop(PF_OTHER).idxmax() if cvs is not None else PF_SELF

    if len(wide) == 1:
        lead = (f"{ym_jp(a_hi)}は、売上の <b>{sub_pct:.1f}%</b> が{PF_SUB}、"
                f"{PF_SELF}が <b>{sp_pct:.1f}%</b> でした。")
    elif driver != PF_SELF:
        lead = (f"売上の <b>{sub_pct:.1f}%</b> が{PF_SUB}。"
                f"この期間は <b>{driver}</b> が最も大きく振れています。")
    else:
        lead = (f"売上の <b>{sub_pct:.1f}%</b> が{PF_SUB}。"
                f"{PF_SELF}が <b>{sp_pct:.1f}%</b> を占め、月次変動を押し上げる構造です。")

    st.markdown(
        "<div class='pf-hero'>"
        "<div class='l'>"
        "<div class='k'>Conclusion</div>"
        f"<div class='big'>{sub_pct:.1f}<span>%</span></div>"
        f"<div class='cap'>が{PF_SUB}</div>"
        "<div class='sub'>メンテ・訪問・介護など、継続的に発生する売上。"
        "この層が厚いほど、売上の土台は崩れにくくなります。</div>"
        "</div>"
        "<div class='r'>"
        f"<div class='it'>期間の総売上<b>{manv(total)}<span style='font-size:12px'> 万円</span></b></div>"
        f"<div class='it'>月あたり平均<b>{manv(total / len(wide))}"
        "<span style='font-size:12px'> 万円</span></b></div>"
        f"<div class='it'>自費依存度<b>{sp_pct:.1f}"
        "<span style='font-size:12px'> %</span></b></div>"
        "</div></div>"
        f"<div class='pf-lead'>{lead}</div>", unsafe_allow_html=True)

    # ---- B. KPIカード ----
    row1 = "".join([
        pf_card(PF_SUB, manv(amounts[PF_SUB]), "万円",
                f"構成比 <b>{shares[PF_SUB]:.1f}%</b>", "a-navy"),
        pf_card(PF_SELF, manv(amounts[PF_SELF]), "万円",
                f"構成比 <b>{shares[PF_SELF]:.1f}%</b>", "a-gold"),
        pf_card(PF_INS, manv(amounts[PF_INS]), "万円",
                f"構成比 <b>{shares[PF_INS]:.1f}%</b>", "a-blue"),
        pf_card(PF_OTHER, manv(amounts[PF_OTHER]), "万円",
                f"構成比 <b>{shares[PF_OTHER]:.1f}%</b>", "a-gray"),
    ])
    cv_na = "変動係数は3か月以上で算出します"
    row2 = "".join([
        pf_card("サブスク比率", f"{sub_pct:.1f}", "%",
                f"月次変動係数 <b>{cvs[PF_SUB]:.1f}%</b>" if cvs is not None else cv_na,
                "a-green", small=True),
        pf_card("自費依存度", f"{sp_pct:.1f}", "%",
                f"月次変動係数 <b>{cvs[PF_SELF]:.1f}%</b>" if cvs is not None else cv_na,
                "a-gold", small=True),
        pf_card(f"{PF_SELF}の振れ幅", f"{swing:.2f}" if swing else "—", "倍",
                (f"最小 <b>{manv(sp_m.min())}</b> 〜 最大 <b>{manv(sp_m.max())}</b> 万円"
                 if swing else "2か月以上の期間で算出します"), "a-gold", small=True),
        pf_card(f"{PF_OTHER}比率", f"{shares[PF_OTHER]:.1f}", "%",
                "物販売上", "a-gray", small=True),
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
                    f"・{PF_SUB}が最下段・単位：万円</div></div>", unsafe_allow_html=True)
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
            st.altair_chart(chart_pf_donut(shares, PF_SUB, f"{sub_pct:.1f}%"),
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
            ratio = cvs[PF_SELF] / max(cvs[PF_SUB], 0.1)
            st.markdown(
                f"<div class='pf-mx'><b>{PF_SUB}は安定した土台、"
                f"{PF_SELF}は売上を押し上げるが月次変動も大きい。</b><br>"
                f"{PF_SUB}は構成比 <b>{sub_pct:.1f}%</b> に対し変動係数 "
                f"<b>{cvs[PF_SUB]:.1f}%</b>。{PF_SELF}は構成比 <b>{sp_pct:.1f}%</b> に対し "
                f"<b>{cvs[PF_SELF]:.1f}%</b> で、<b>{ratio:.1f}倍</b> 振れます。"
                f"土台を{PF_SUB}が支え、振れ幅を{PF_SELF}が生む構造です。</div>",
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
        f"{PF_SUB}＝メンテ・検診・SPT・歯周/DH管理などの継続管理に紐づく保険売上"
        "＋訪問診療＋介護。月額課金ではなく、継続的・反復的に発生する売上という意味です。"
        f"{PF_SELF}＝レセコンの自費診療売上そのまま（矯正・インプラント・自費補綴・"
        "ホワイトニング等。継続通院する矯正もここに含みます）。"
        f"{PF_INS}＝外来保険売上から継続管理の保険分を除いたもの。"
        f"{PF_OTHER}＝物販売上。<br>"
        f"<b>按分方法</b>　金額は会計区分（保険・自費・物販）で決めています。"
        f"推定が入るのは{PF_SUB}に入れる継続管理の保険分だけで、"
        "同じ来院日に複数の分類が混在する場合は"
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
