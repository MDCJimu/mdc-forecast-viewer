# -*- coding: utf-8 -*-
"""経営分析コメントの生成（表示専用）

このモジュールは「すでに確定した予測値」を読み、経営判断に必要な文章を組み立てるだけ。
予測モデル・予測値・売上集計定義・月締め・学習には一切触れない。

つくり:
    daily_rolling_forecast.json（＝roll）
  + monthly_actuals.csv の前年同月の行（＝prev_year_row）
  + forecast_history.csv の前回スナップショットの行（＝prev_forecast_row）
      ↓
    _facts()      … 使える数字だけを取り出す（無い指標は None のまま。推測しない）
      ↓
    _components() … 前年差を項目ごとの寄与額に分解する
      ↓
    判定関数群     … 前年差の主因／稼働／構造変化／自費の見立て
      ↓
    _actions()    … 打ち手を生成し、経営インパクト順に最大5件へ絞る

数値は毎月このデータから計算する。特定の月の金額・件数をコードへ書かない。

用語は院長・事務長が一度で読める言葉に寄せる。
「再充填」「高単価型」「別建て反映」「実績日数基準」などの内部用語は使わない。
"""

MAN = 10000

# ======================================================================
# 「1日あたり」の2つの定義
# ----------------------------------------------------------------------
# この2つは別の指標。同じ「1診療日あたり売上」という名前で扱わない。
#
#   外来診療日あたり売上
#       分子 = 外来保険 ＋ 自費 ＋ 物販（訪問・介護を含めない）
#       分母 = 外来診療を行った日数
#       医院の通常診療の生産性を見る指標。
#
#   売上発生日あたり総売上
#       分子 = 外来保険 ＋ 訪問保険 ＋ 介護 ＋ 自費 ＋ 物販
#       分母 = 何らかの売上が発生した日数（訪問・介護だけの木曜も数える）
#       法人全体の売上発生日ベースの指標。
#
# 分子と分母の基準が食い違う組み合わせ（例：全売上 ÷ 外来診療日数）は作らない。
# 木曜休診が始まると訪問・介護だけ売上が立つ木曜が現れ、この2つが乖離する。
BASIS_OUTPATIENT = "外来診療日"      # 分子は外来3区分のみ
BASIS_REVENUE_DAY = "売上発生日"     # 分子は全区分

# スナップショットが持っている日数は、この2つのどちらでもない混合値。
#   actual_days_count           … 売上が発生した日（訪問・介護だけの日も数える）
#   elapsed_unrecorded_days_count … 経過した外来診療予定日で売上が未反映のもの
#   remaining_days_count        … これからの外来診療予定日
# 合計は「売上のあった日 ＋ 残りの外来診療予定日」であり、外来診療日数ではない。
# 外来診療日だけを数え直すには日次データが要るが、cloud_deploy は月次と
# スナップショットしか持っていないため、この画面では分けられない。
BASIS_MIXED_DAYS = "売上のあった日＋残りの外来診療予定日"

# cloud_deploy が持っている monthly_actuals.csv の「診療日数」は
# 「レセコン明細がある日 ＋ 介護のみ計上がある日」＝ 売上発生日数 であり、
# 外来診療日数ではない（scripts/monthly_actuals_source.py の定義）。
# 過去月の外来診療日数を出せる列は cloud_deploy 側に存在しない。
HIST_DAYS_BASIS = BASIS_REVENUE_DAY

# ---- 判定のしきい値（金額はすべて円）--------------------------------------
MATERIAL_YEN = 300_000      # これ未満の差は「ほぼ前年並み」として扱う
MATERIAL_RATE = 0.01        # 前年比1%未満も同様（大きい項目で金額だけ見ると誤判定するため）
PACE_ALERT = 0.05           # 残り期間に必要な1日あたり売上が現時点平均をこの比率以上上回ると論点化
CANCEL_ALERT_PT = 0.5       # キャンセル率が前年より何pt高ければ論点化するか
DENSITY_ALERT = 0.03        # 1診療日あたり・1来院あたりの増減をコメントする下限（比率）
MAX_ACTIONS = 5

# 優先順位（小さいほど上）。ルール: 1=寄与額が大きい 2=月内で改善可能
# 3=構造変化 4=先行指標 5=翌月以降の構造課題
T_DRIVER, T_INMONTH, T_STRUCTURE, T_LEADING, T_NEXT = 1, 2, 3, 4, 5


# ======================================================================
# 表示ヘルパー
# ======================================================================
def f_(v):
    """数値化できないものは None。0 は 0 のまま返す。"""
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def yen_man(v, unit=True):
    """1,234万円"""
    if v is None:
        return "取得不可"
    s = f"{round(float(v) / MAN):,}"
    return s + "万円" if unit else s


def yen_sman(v, unit=True):
    """▲212万円 / +172万円 / ±0万円"""
    if v is None:
        return "取得不可"
    n = round(float(v) / MAN)
    tail = "万円" if unit else ""
    if n < 0:
        return f"▲{abs(n):,}{tail}"
    if n > 0:
        return f"+{n:,}{tail}"
    return f"±0{tail}"


def cnt(v, unit=""):
    if v is None:
        return "取得不可"
    return f"{round(float(v)):,}{unit}"


def scnt(v, unit=""):
    if v is None:
        return "取得不可"
    n = round(float(v))
    if n < 0:
        return f"▲{abs(n):,}{unit}"
    if n > 0:
        return f"+{n:,}{unit}"
    return f"±0{unit}"


def rate(now, prev):
    """前年比の増減率（%）。前年が無い/0なら None。"""
    now, prev = f_(now), f_(prev)
    if now is None or not prev:
        return None
    return (now - prev) / abs(prev) * 100


def pct(v, digits=1):
    if v is None:
        return ""
    return f"{v:+.{digits}f}%"


def _updown_te(v):
    """「〜ているため」のように後ろへ続けるときの形。"""
    return _updown(v, up="上回っている", down="下回っている", flat="ほぼ並んでいる")


def _updown(v, up="上回る", down="下回る", flat="ほぼ並ぶ"):
    if v is None:
        return "—"
    if v > 0:
        return up
    if v < 0:
        return down
    return flat


def is_material(diff, base=None):
    """その差を「意味のある差」として扱ってよいか。"""
    if diff is None:
        return False
    if abs(diff) >= MATERIAL_YEN:
        return True
    b = f_(base)
    return bool(b) and abs(diff) >= abs(b) * MATERIAL_RATE


def _div(a, b):
    a, b = f_(a), f_(b)
    if a is None or not b:
        return None
    return a / b


def _sum(*vals):
    """ひとつでも欠けていたら None（欠損を0とみなさない）。"""
    out = 0.0
    for v in vals:
        v = f_(v)
        if v is None:
            return None
        out += v
    return out


# ---- 直近12か月の分布（A-1 / A-4）------------------------------------
# 前年同月1点だけで良し悪しを決めると、自費のように月ごとの振れが大きい区分で
# 判断を誤る。同じ区分の直近12か月の分布を並べて、今月と前年がその中の
# どこに位置するのかまで見る。
HIST_COLS = {
    "total": "月間総売上",
    "insurance": "保険診療売上",
    "selfpay": "自費診療売上",
    "product": "物販売上",
    "outpatient": "外来保険売上",
    "visit_ins": "訪問保険売上",
    "care": "介護売上",
}
HIST_MONTHS = 12
SPREAD_WIDE = 0.35      # (最大-最小)/中央値 がこれを超えたら「振れの大きい区分」


def _quantile(sorted_vals, q):
    """線形補間の分位点。numpy を持ち込まないための最小実装。"""
    if not sorted_vals:
        return None
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def _stats(vals):
    vals = [v for v in (f_(x) for x in vals) if v is not None]
    if len(vals) < 4:
        return None
    sv = sorted(vals)
    n = len(sv)
    med = _quantile(sv, 0.5)
    return {
        "n": n, "min": sv[0], "max": sv[-1], "mean": sum(sv) / n, "median": med,
        "q1": _quantile(sv, 0.25), "q3": _quantile(sv, 0.75), "sorted": sv,
        "spread": ((sv[-1] - sv[0]) / med) if med else None,
    }


def _level(st, v):
    """その値が分布のどこにいるか。経営判断に意味のある粒度だけ返す。"""
    if st is None or v is None:
        return None
    if v >= st["max"]:
        return "最高"
    if v <= st["min"]:
        return "最低"
    if v >= st["q3"]:
        return "上位25%"
    if v <= st["q1"]:
        return "下位25%"
    return "中位"


def _history(target_ym, history_rows):
    """対象月より前の直近12か月ぶんの分布を区分ごとに作る。"""
    rows = [r for r in (history_rows or [])
            if r.get("年月") and (not target_ym or r["年月"] < target_ym)]
    rows.sort(key=lambda r: r["年月"])
    rows = rows[-HIST_MONTHS:]
    if len(rows) < 4:
        return {"available": False, "months": [], "stats": {}, "per_day": []}
    stats = {k: _stats([r.get(col) for r in rows]) for k, col in HIST_COLS.items()}
    # 売上発生日あたり総売上の推移。
    # 分子は全区分、分母は売上発生日数（訪問・介護だけの日も含む）で、基準は揃っている。
    # ただし木曜休診が始まると分母の中身（訪問介護だけの日）が増えるため、
    # この系列をまたいで生産性のトレンドを読むことはできない。
    per_day = []
    for r in rows:
        tot, days = f_(r.get("月間総売上")), f_(r.get("診療日数"))
        per_day.append({"ym": r["年月"], "total": tot, "days": days,
                        "basis": HIST_DAYS_BASIS,
                        "per_day": (tot / days) if (tot and days) else None})
    stats["per_day"] = _stats([x["per_day"] for x in per_day])
    return {"available": True, "months": [r["年月"] for r in rows],
            "stats": stats, "per_day": per_day, "days_basis": HIST_DAYS_BASIS,
            "range": (rows[0]["年月"], rows[-1]["年月"])}


# ======================================================================
# 1. 事実（使える数字だけを取り出す）
# ======================================================================
def _shift_year(ym):
    try:
        return f"{int(ym[:4]) - 1}-{ym[5:7]}"
    except Exception:
        return None


def _facts(roll, prev_year_row=None, prev_forecast_row=None, history_rows=None):
    roll = roll or {}
    py = prev_year_row or {}
    sup = roll.get("supplementary") or {}
    prog = roll.get("progress_through_yesterday") or {}
    o_cur = prog.get("current") or {}
    o_pyd = prog.get("prev_year_same_day") or {}
    o_biz = prog.get("prev_year_same_bizdays") or {}

    def pyv(col):
        return f_(py.get(col))

    total = f_(roll.get("current_forecast_total"))
    prev_total = f_(roll.get("previous_year_actual"))
    yoy = f_(roll.get("yoy_diff"))
    if yoy is None and total is not None and prev_total is not None:
        yoy = total - prev_total

    d_act = f_(roll.get("actual_days_count"))
    d_unrec = f_(roll.get("elapsed_unrecorded_days_count"))
    d_rem = f_(roll.get("remaining_days_count"))
    days_month = _sum(d_act, d_unrec, d_rem)
    # 外来診療日ベースの日数。build_daily_rolling_forecast が出力する。
    # 訪問・介護だけ売上が立った日は含まれない。古いスナップショットには無いので None。
    d_out_act = f_(roll.get("outpatient_actual_days_count"))
    d_out_month = f_(roll.get("outpatient_month_days_count"))
    days_elapsed = _sum(d_act, d_unrec)
    # 履歴の「診療日数」は売上発生日数（訪問・介護だけの日を含む）。
    # 外来診療日数ではないので、外来3区分の分子と割り算するときは基準が食い違う。
    days_prev = pyv("診療日数")

    outp = f_(roll.get("outpatient_insurance_forecast"))
    selfpay = f_(roll.get("selfpay_forecast"))
    product = f_(roll.get("product_forecast"))
    # 外来3区分＝外来保険＋自費＋物販。訪問・介護は入力が遅れるため月末見込みを分けて置いており、
    # 「1日あたり」「1来院あたり」の比較にはこの3区分だけを使う（前年と同じ土俵にするため）。
    op_now = _sum(outp, selfpay, product)
    op_prev = _sum(pyv("外来保険売上"), pyv("自費診療売上"), pyv("物販売上"))

    vis = sup.get("visit") or {}
    sho = sup.get("shoshin") or {}
    pat = sup.get("patient_total") or {}
    can = sup.get("cancel") or {}
    comp = sup.get("reservation_composition") or {}

    visit_now = f_(vis.get("forecast")) if vis.get("available") else None
    visit_prev = f_(vis.get("prevyear")) or pyv("総来院回数")
    sho_now = f_(sho.get("forecast")) if sho.get("available") else None
    sho_prev = f_(sho.get("prevyear")) or pyv("初診件数")
    pat_now = f_(pat.get("forecast")) if pat.get("available") else None
    pat_prev = f_(pat.get("prevyear")) or pyv("総患者数")

    care_cmp = roll.get("care_component") or {}
    prev_fc_row = prev_forecast_row or {}
    prev_fc = f_(prev_fc_row.get("current_forecast_total"))
    prev_fc_selfpay = f_(prev_fc_row.get("selfpay_forecast"))
    prev_fc_ins = f_(prev_fc_row.get("insurance_forecast"))

    actual_td = f_(roll.get("actual_to_date_total"))
    remaining = f_(roll.get("remaining_forecast_total"))
    insurance = f_(roll.get("insurance_forecast"))

    f = {
        "target_month": roll.get("target_month"),
        "as_of": roll.get("as_of_date"),
        "prev_year_month": _shift_year(roll.get("target_month")),

        # --- A. 売上全体 ---
        "total": total,
        "conservative": f_(roll.get("conservative_forecast")),
        "low80": f_(roll.get("forecast_low_80")),
        "high80": f_(roll.get("forecast_high_80")),
        "prev_total": prev_total,
        "yoy": yoy,
        "yoy_rate": (f_(roll.get("yoy_rate")) if roll.get("yoy_rate") is not None
                     else rate(total, prev_total)),
        "baseline": f_(roll.get("normal_baseline_forecast")),
        "baseline_gap": f_(roll.get("gap_to_normal_baseline")),
        "prev_forecast": prev_fc,
        "prev_forecast_asof": prev_fc_row.get("as_of_date"),
        "prev_forecast_diff": ((total - prev_fc)
                               if (total is not None and prev_fc is not None) else None),
        "prev_forecast_selfpay_diff": ((selfpay - prev_fc_selfpay)
                                       if (selfpay is not None and prev_fc_selfpay is not None) else None),
        "prev_forecast_ins_diff": ((insurance - prev_fc_ins)
                                   if (insurance is not None and prev_fc_ins is not None) else None),
        # 目標は現在どのデータにも入っていない。入ってきたら自動で使う（推測では作らない）。
        "target_sales": f_(roll.get("monthly_sales_target")),

        # --- B. 売上構成 ---
        "insurance": insurance,
        "insurance_prev": f_(roll.get("insurance_prevyear")),
        "selfpay": selfpay,
        "selfpay_prev": f_(roll.get("selfpay_prevyear")),
        "product": product,
        "product_prev": f_(roll.get("product_prevyear")),
        "outpatient": outp,
        "outpatient_prev": pyv("外来保険売上"),
        "visit_ins": f_(roll.get("visit_insurance_forecast")),
        "visit_ins_prev": pyv("訪問保険売上"),
        "care": f_(roll.get("care_forecast")),
        "care_prev": pyv("介護売上"),
        "care_regime_changed": bool(care_cmp.get("care_revision_month")),
        "care_revision_month": care_cmp.get("care_revision_month"),
        "care_data_insufficient": bool(care_cmp.get("care_data_insufficient")),

        "selfpay_confirmed": f_(roll.get("selfpay_actual_to_date")),
        "selfpay_remaining": f_(roll.get("selfpay_remaining")),
        "insurance_confirmed": f_(roll.get("insurance_actual_to_date")),
        "product_confirmed": f_(roll.get("product_actual_to_date")),

        # 高額な自費案件の見込みレンジ。0〜0 は「算出できていない」であって
        # 「0円の見込み」ではない。両端0のときは金額として使わない。
        "hv_low": f_(roll.get("high_value_selfpay_low")),
        "hv_high": f_(roll.get("high_value_selfpay_high")),

        # --- C. 稼働 ---
        "days_actual": d_act,
        "days_unrecorded": d_unrec,
        "days_remaining": d_rem,
        "days_elapsed": days_elapsed,
        "days_month": days_month,
        "days_actual_outpatient": d_out_act,
        "days_month_outpatient": d_out_month,
        "has_outpatient_days": (d_out_act is not None and d_out_month is not None),
        "days_prev": days_prev,
        # 今月の日数は外来診療の予定日、前年の日数は売上発生日で、数え方が違う。
        # 引き算した値は意味を持たないので作らない。monthly_actuals.csv に
        # 外来診療日数の列が入り、同じ定義で数えられるようになったら復活させる。
        "days_diff": None,

        "op_now": op_now,
        "op_prev": op_prev,
        # 外来診療日あたり売上。分子は外来3区分、分母は外来診療日数。
        # 前年は同じ数え方の日数が monthly_actuals.csv に無いため前年側を作らない。
        # 混合分母（外来3区分 ÷ 売上発生日を含む日数）はどこにも持たない。
        "per_day_now": _div(op_now, d_out_month),
        "per_day_prev": None,
        "per_day_basis_now": BASIS_OUTPATIENT,
        "per_day_basis_prev": None,
        "ins_per_day_now": _div(outp, d_out_month),
        "ins_per_day_prev": None,
        # 売上発生日あたり総売上（分子は全区分・前年のみ算出可能）
        "rev_day_per_day_prev": _div(pyv("月間総売上"), days_prev),
        "per_visit_now": _div(op_now, visit_now),
        "per_visit_prev": _div(op_prev, visit_prev),
        # 来院回数は訪問診療の患者も含むため、外来診療日数で割ると基準が食い違う。
        # 同一定義の分母を用意できないので日割りしない（件数のまま前年と比べる）。
        "visit_per_day_now": None,
        "visit_per_day_prev": None,

        "visit": visit_now,
        "visit_prev": visit_prev,
        "visit_confirmed": f_(vis.get("actual_to_date")),
        "shoshin": sho_now,
        "shoshin_prev": sho_prev,
        "patients": pat_now,
        "patients_prev": pat_prev,
        "cancel_rate": f_(can.get("current_rate")) if can.get("available") else None,
        "cancel_rate_prev": f_(can.get("prevyear_rate")) if can.get("available") else None,
        "cancel_count": f_(can.get("current_cancels")) if can.get("available") else None,
        "reservations_registered": (f_(can.get("current_reservations"))
                                    if can.get("available") else None),
        "reservation_remaining": f_(roll.get("reservation_visible_remaining_as_of")),
        "reservation_projected": f_(roll.get("reservation_projected_final_remaining")),
        "reservation_types": (comp.get("types") or {}) if comp.get("available") else {},

        "actual_to_date": actual_td,
        "remaining_forecast": remaining,
        # 今月ここまでの1日あたり。分子は外来3区分なので外来診療日数で割る。
        "per_day_done": _div(actual_td, d_out_act),
        "per_day_needed": _div(remaining, d_rem),

        # --- C-2. 実測（予測基準日までに実際に起きたこと）---
        # 月末見込みと混ぜない。稼働の評価はこちらを主指標にする。
        "obs_days": f_(o_cur.get("clinic_days")),
        "obs_total": f_(o_cur.get("total")),
        "obs_outpatient": f_(o_cur.get("insurance_outpatient")),
        "obs_selfpay": f_(o_cur.get("selfpay")),
        "obs_product": f_(o_cur.get("product")),
        "obs_cutoff": prog.get("current_cutoff"),
        # 同じ診療日数まで累計した前年（診療日数を揃えた比較）
        # prev_year_same_bizdays は「売上が発生した日」を当年と同じ日数だけ前年から
        # 取ったもの（build_daily_rolling_forecast の _py_rows_all は診療日フラグで絞る）。
        # そのうち何日が外来診療日だったかはスナップショットに入っておらず、
        # 当年と同じ外来診療日数で比べられているかを画面側で確認できない。
        # 確認できない比較は稼働・生産性の根拠に使わないため、生値だけ保持する。
        "obs_prev_total": f_(o_biz.get("total")),
        "obs_prev_days": f_(o_biz.get("clinic_days")),
        # 前年側の外来診療日数。当年の outpatient_actual_days_count と一致した
        # ときだけ外来3区分の比較を出す。clinic_days が同じでも判定材料にしない。
        "obs_prev_outpatient_days": f_(o_biz.get("outpatient_days_count")),
        "obs_prev_outpatient": f_(o_biz.get("insurance_outpatient")),
        "obs_prev_selfpay": f_(o_biz.get("selfpay")),
        "obs_prev_product": f_(o_biz.get("product")),
        "obs_diff": None,
        "obs_rate": None,
        "obs_bizdays_raw_diff": f_(o_biz.get("diff_vs_current")),
        "obs_bizdays_raw_rate": f_(o_biz.get("rate")),
        # 暦の同じ日まで累計した前年（区分別の内訳はこちらにしかない）
        "obs_pyd_days": f_(o_pyd.get("clinic_days")),
        "obs_pyd_outpatient": f_(o_pyd.get("insurance_outpatient")),
        "obs_pyd_selfpay": f_(o_pyd.get("selfpay")),
        "obs_pyd_product": f_(o_pyd.get("product")),
        "obs_pyd_cutoff": prog.get("prev_year_cutoff"),

        # --- D. 構造変化 ---
        "thursday_closed": bool(roll.get("thursday_closed_target")),

        "data_status_resec": roll.get("resec_data_status"),
        "data_through": roll.get("actual_data_through"),
        "has_prev_year_row": bool(py),
    }

    # 「着地見込みと保守ラインの差」はここだけで計算する。
    # 残り期間の必要ペース差（pace_gap_yen）とは別物なので、混同しないよう名前を分ける。
    f["conservative_gap"] = ((f["total"] - f["conservative"])
                             if (f["total"] is not None and f["conservative"] is not None)
                             else None)
    f["pace_gap_rate"] = ((f["per_day_needed"] / f["per_day_done"] - 1)
                          if (f["per_day_needed"] and f["per_day_done"]) else None)
    f["pace_gap_yen"] = ((f["per_day_needed"] - f["per_day_done"]) * f["days_remaining"]
                         if (f["per_day_needed"] is not None and f["per_day_done"] is not None
                             and f["days_remaining"]) else None)

    # 木曜休診が効いている月は、当月の分母（外来診療予定日ベース）と
    # 前年の分母（売上発生日数）で中身が違う。黙って比べずに但し書きを出すため
    # のフラグ。訪問・介護だけ売上が立つ木曜が現れるのがこの状態。
    f_basis_gap = bool(roll.get("thursday_closed_target"))

    # 経過したが売上未反映の日の推定（実績とも残りとも別物として持つ）
    f["per_day_unrecorded"] = _div(roll.get("elapsed_unrecorded_total"), d_unrec)

    # 実測の1診療日あたり（A-2）。診療日数を揃えた前年と比べる。
    # 総額の前年比較は「同じ診療日数まで累計した総額」どうしで行い、日割りしない。
    f["obs_per_day"] = None
    f["obs_prev_per_day"] = None
    # 実測の区分別1日あたりも外来診療日数で割る。前年側は同一定義が無いので作らない。
    for k in ("outpatient", "selfpay", "product"):
        f[f"obs_{k}_per_day"] = _div(f[f"obs_{k}"], d_out_act)
        f[f"obs_pyd_{k}_per_day"] = None

    f["per_day_basis_gap"] = f_basis_gap
    # 外来診療日あたり売上。分子は外来3区分、分母は外来診療日数。
    # 前年の外来診療日数は monthly_actuals.csv に無いため、前年比較は作らない。
    f["op_per_day_actual"] = _div(f["obs_total"], d_out_act)
    f["op_per_day_month"] = _div(op_now, d_out_month)

    # 着地予測が置いている上振れ前提。予測値は変えず、達成条件として並べるだけ。
    #   ① 経過したが売上未反映の日を、確定済みの日より高い水準で推定している分
    #   ② 予約増加補正（1.00 を超える分）が残り期間へ乗せている分
    opt = []
    if (f["per_day_unrecorded"] and f["per_day_done"]
            and f["per_day_unrecorded"] > f["per_day_done"] and d_unrec):
        gap = (f["per_day_unrecorded"] - f["per_day_done"]) * d_unrec
        opt.append({"key": "unrecorded", "yen": gap,
                    "text": (f"売上がまだ入っていない{cnt(d_unrec, '日')}を1日あたり"
                             f"{yen_man(f['per_day_unrecorded'])}と置いています。"
                             f"外来診療を行った{cnt(d_out_act, '日')}の平均"
                             f"{yen_man(f['per_day_done'])}より高く、差は{yen_man(gap)}です。")})
    rf = f_(roll.get("reservation_factor_final", roll.get("reservation_factor")))
    if rf and rf > 1.0 and remaining:
        lift = remaining - remaining / rf
        opt.append({"key": "reservation_factor", "yen": lift,
                    "text": (f"残り期間に予約増加補正{rf:.2f}倍を掛けており、"
                             f"{yen_man(lift)}を上乗せしています。")})
    f["optimistic"] = opt
    f["optimistic_total"] = sum(o["yen"] for o in opt) if opt else None
    f["total_without_optimistic"] = ((f["total"] - f["optimistic_total"])
                                     if (f["total"] is not None and opt) else None)

    # 外来3区分の前年比較を出してよいかの判定。
    # 判定根拠は outpatient 日数どうしの一致だけ。clinic_days は使わない。
    _pod = f["obs_prev_outpatient_days"]
    f["outpatient_days_match"] = (d_out_act is not None and _pod is not None
                                  and d_out_act == _pod)
    if f["outpatient_days_match"]:
        f["op_per_day_prev"] = _div(f["obs_prev_total"], _pod)
        f["op_diff_total"] = f["obs_total"] - f["obs_prev_total"]
        f["op_rate_total"] = rate(f["obs_total"], f["obs_prev_total"])
        for k, prev_k in (("outpatient", "obs_prev_outpatient"),
                          ("selfpay", "obs_prev_selfpay"), ("product", "obs_prev_product")):
            f[f"op_prev_{k}_per_day"] = _div(f[prev_k], _pod)
    else:
        f["op_per_day_prev"] = None
        f["op_diff_total"] = None
        f["op_rate_total"] = None
        for k in ("outpatient", "selfpay", "product"):
            f[f"op_prev_{k}_per_day"] = None

    # 直近12か月の分布（A-1 / A-4 / A-6）
    f["hist"] = _history(f["target_month"], history_rows)
    st = f["hist"]["stats"]
    now_of = {"total": f["total"], "insurance": f["insurance"], "selfpay": f["selfpay"],
              "product": f["product"], "outpatient": f["outpatient"],
              "visit_ins": f["visit_ins"], "care": f["care"]}
    prev_of = {"total": f["prev_total"], "insurance": f["insurance_prev"],
               "selfpay": f["selfpay_prev"], "product": f["product_prev"],
               "outpatient": f["outpatient_prev"], "visit_ins": f["visit_ins_prev"],
               "care": f["care_prev"]}
    f["level_now"] = {k: _level(st.get(k), v) for k, v in now_of.items()}
    f["level_prev"] = {k: _level(st.get(k), v) for k, v in prev_of.items()}
    f["volatile"] = {k: bool(st.get(k) and st[k]["spread"] is not None
                             and st[k]["spread"] > SPREAD_WIDE)
                     for k in HIST_COLS}
    return f


# ======================================================================
# 2. 前年差の寄与分解
# ======================================================================
class Comp(object):
    def __init__(self, key, name, now, prev):
        self.key = key
        self.name = name
        self.now = f_(now)
        self.prev = f_(prev)
        self.diff = ((self.now - self.prev)
                     if (self.now is not None and self.prev is not None) else None)
        self.rate = rate(self.now, self.prev)

    @property
    def ok(self):
        return self.diff is not None

    @property
    def material(self):
        return is_material(self.diff, self.prev)

    def __repr__(self):
        return f"<Comp {self.name} {self.diff}>"


def _components(f):
    """売上を3区分・保険を3内訳に分けた寄与額。合計は総売上の前年差に一致する。"""
    main = [
        Comp("insurance", "保険診療", f["insurance"], f["insurance_prev"]),
        Comp("selfpay", "自費診療", f["selfpay"], f["selfpay_prev"]),
        Comp("product", "物販", f["product"], f["product_prev"]),
    ]
    sub = [
        Comp("outpatient", "外来保険", f["outpatient"], f["outpatient_prev"]),
        Comp("visit_ins", "訪問保険", f["visit_ins"], f["visit_ins_prev"]),
        Comp("care", "介護", f["care"], f["care_prev"]),
    ]
    return {"main": [c for c in main if c.ok],
            "sub": [c for c in sub if c.ok],
            "main_all": main, "sub_all": sub}


def _split(comps, total_diff):
    """総差額と同じ向き＝押し下げ／押し上げ要因、逆向き＝打ち消し要因。"""
    usable = [c for c in comps if c.ok and c.material]
    if total_diff is None or total_diff < 0:
        drivers = sorted([c for c in usable if c.diff < 0], key=lambda c: c.diff)
        offsets = sorted([c for c in usable if c.diff > 0], key=lambda c: -c.diff)
    else:
        drivers = sorted([c for c in usable if c.diff > 0], key=lambda c: -c.diff)
        offsets = sorted([c for c in usable if c.diff < 0], key=lambda c: c.diff)
    return drivers, offsets


def _netted(driver_sum, offset_sum, total_diff):
    """「結果として」と言い切れるのは、万円に丸めても引き算が合うときだけ。"""
    r = lambda v: round(abs(v) / MAN)
    if r(driver_sum) - r(offset_sum) == r(total_diff):
        return "結果として"
    return "差し引きで"


def _join(names):
    """名詞を読みやすく並べる。2つなら「AとB」、3つ以上なら「A・B・C」。"""
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]}と{names[1]}"
    return "・".join(names)


# ======================================================================
# 3. 前年差の主因
# ======================================================================
def _prevyear_outlier(f, key):
    """その区分について、前年同月が直近12か月の分布の端に寄っていないか。

    寄っていて、かつ今月が中位に収まっているなら、前年差は「今月が悪い」
    ではなく「前年が高かった／低かった」で説明できる。断定を避けるための判定。
    """
    st = (f.get("hist") or {}).get("stats", {}).get(key)
    if not st:
        return None
    lv_prev, lv_now = f["level_prev"].get(key), f["level_now"].get(key)
    if lv_prev not in ("最高", "上位25%", "最低", "下位25%"):
        return None
    if lv_now not in ("中位", "上位25%", "下位25%"):
        return None
    high = lv_prev in ("最高", "上位25%")
    # 今月が前年と同じ側に振れているなら「前年が特殊」では説明できない
    if high and lv_now == "上位25%":
        return None
    if (not high) and lv_now == "下位25%":
        return None
    return {"prev_level": lv_prev, "now_level": lv_now, "high": high,
            "stats": st, "volatile": f["volatile"].get(key, False)}


def _yoy_cause(f, comps):
    total_diff = f["yoy"]
    main = comps["main"]
    if not main or total_diff is None:
        return {"text": "前年同月の内訳が取得できないため、差の主因を分解できません。",
                "rows": [], "main": None, "drivers": [], "offsets": [], "flat": False}

    drivers, offsets = _split(main, total_diff)
    flat = not is_material(total_diff, f["prev_total"])
    head = drivers[0] if drivers else None

    rows = []
    for c in sorted(main, key=lambda c: -abs(c.diff)):
        if c.material:
            role = "押し下げ" if c.diff < 0 else "押し上げ"
        else:
            role = "ほぼ前年並み"
        rows.append({"name": c.name, "now": c.now, "prev": c.prev, "diff": c.diff,
                     "rate": c.rate, "role": role})

    parts = []
    if flat:
        parts.append(f"総売上は前年同月{yen_man(f['prev_total'])}に対して"
                     f"{yen_man(f['total'])}の見込みで、ほぼ前年並みです。")
    else:
        parts.append(f"総売上は前年同月を{yen_sman(total_diff)}"
                     f"（{pct(f['yoy_rate'])}）{_updown(total_diff)}見込みです。")

    outlier = _prevyear_outlier(f, head.key) if head is not None else None
    if head is None:
        parts.append("内訳のどの項目も前年と大きくは変わっていません。")
    else:
        direction = "下回る" if head.diff < 0 else "上回る"
        if offsets:
            off_txt = "、".join(f"{c.name}は{yen_sman(c.diff)}" for c in offsets[:2])
            head_txt = (f"{head.name}が{yen_sman(head.diff)}"
                        if outlier else
                        f"{head.name}の{yen_sman(head.diff)}が前年を{direction}主因です")
            parts.append(f"一方で{off_txt}と逆向きに動いており、前年差のほとんどは"
                         f"{head.name}の{yen_sman(head.diff)}によるものです。"
                         if outlier else
                         f"一方で{off_txt}と逆向きに動いており、{head_txt}。")
        else:
            parts.append(f"{head.name}の{yen_sman(head.diff)}が最大の要因です。")

    # 前年が分布の端にいる区分は「今月が悪い」と断定しない（A-1）
    if outlier:
        st = outlier["stats"]
        side = "高い" if outlier["high"] else "低い"
        parts.append(
            f"ただし{head.name}は月ごとの振れが大きい区分で、直近{st['n']}か月は"
            f"{yen_man(st['min'])}〜{yen_man(st['max'])}（中央値{yen_man(st['median'])}）"
            f"の範囲で動いています。前年同月の{yen_man(head.prev)}はこの中で"
            f"{outlier['prev_level']}にあたる{side}月でした。"
            f"今月の{yen_man(head.now)}は{outlier['now_level']}で、"
            f"平常の範囲に収まっています。"
            f"前年差は「今月が落ちた」よりも「前年が{side}月だった」ことで"
            "説明できる可能性が高い水準です。")

        # 打ち消しが効いている月は「何がマイナス／何が吸収／結果いくら」を1文で出す。
        offset_sum = sum(c.diff for c in main if c.ok and c.diff * head.diff < 0)
        driver_sum = sum(c.diff for c in main if c.ok and c.diff * head.diff > 0)
        if offset_sum and is_material(offset_sum):
            d_names = _join([c.name for c in main if c.ok and c.diff * head.diff > 0])
            o_names = _join([c.name for c in main if c.ok and c.diff * head.diff < 0])
            if head.diff < 0:
                parts.append(f"{d_names}のマイナス{yen_man(abs(driver_sum))}を、"
                             f"{o_names}のプラス{yen_man(abs(offset_sum))}が吸収しており、"
                             f"{_netted(driver_sum, offset_sum, total_diff)}"
                             f"全体では{yen_man(abs(total_diff))}の前年割れです。")
            else:
                parts.append(f"{d_names}のプラス{yen_man(abs(driver_sum))}が、"
                             f"{o_names}のマイナス{yen_man(abs(offset_sum))}を上回り、"
                             f"{_netted(driver_sum, offset_sum, total_diff)}"
                             f"全体では{yen_man(abs(total_diff))}の前年超えです。")

    # 保険の内訳まで踏み込む
    sub = comps["sub"]
    ins = next((c for c in main if c.key == "insurance"), None)
    if sub and ins is not None and ins.material:
        s_drv, s_off = _split(sub, ins.diff)
        shown = [c for c in (s_drv + s_off)][:3]
        if shown:
            parts.append("保険診療の内訳は"
                         + "、".join(f"{c.name}{yen_sman(c.diff)}" for c in shown) + "です。")

    return {"text": "".join(parts), "rows": rows, "main": head,
            "drivers": drivers, "offsets": offsets, "flat": flat}


# ======================================================================
# 4. 稼働の評価
# ======================================================================
def _capacity(f):
    rows = []

    def add(name, now, prev, fmt, difftxt, kind="月末見込み／前年は月末実績"):
        """kind は今月側の値の性格。予測から出した値は「見込み」、
        as_of時点の実データは「実績」。表の見出しと文章で混同しないため。"""
        if now is None or prev is None:
            return None
        d = now - prev
        rows.append({"name": name, "now": fmt(now), "prev": fmt(prev),
                     "diff": difftxt(d), "diff_raw": d, "rate": rate(now, prev),
                     "kind": kind})
        return d

    # --- 実績（予測基準日まで）を先に置く。判断はここから始める。---
    if f["has_outpatient_days"]:
        _m = f["outpatient_days_match"]
        rows.append({"name": "外来診療日あたり売上（実績・外来保険＋自費＋物販）",
                     "now": yen_man(f["op_per_day_actual"]),
                     "prev": yen_man(f["op_per_day_prev"]) if _m else "—",
                     "diff": (yen_sman(f["op_per_day_actual"] - f["op_per_day_prev"])
                              if _m else "—"),
                     "diff_raw": ((f["op_per_day_actual"] - f["op_per_day_prev"])
                                  if _m else 0),
                     "rate": (rate(f["op_per_day_actual"], f["op_per_day_prev"])
                              if _m else None),
                     "kind": (f"実績／同じ外来診療日数"
                              f"（{cnt(f['days_actual_outpatient'], '日')}）まで累計した前年と比較"
                              if _m else
                              f"実績／外来診療{cnt(f['days_actual_outpatient'], '日')}"
                              "・前年の外来診療日数が無いため比較しない")})
        rows.append({"name": "外来診療日あたり売上（月末見込み・外来保険＋自費＋物販）",
                     "now": yen_man(f["op_per_day_month"]), "prev": "—", "diff": "—",
                     "diff_raw": 0, "rate": None,
                     "kind": f"月末見込み／外来診療{cnt(f['days_month_outpatient'], '日')}"
                             "・前年は同じ数え方の日数が無いため比較しない"})
    d_obs = None
    if f["has_outpatient_days"]:
        for key, lab in (("outpatient", "うち外来保険（実績・外来診療日あたり）"),
                         ("selfpay", "うち自費（実績・外来診療日あたり）"),
                         ("product", "うち物販（実績・外来診療日あたり）")):
            v = f[f"obs_{key}_per_day"]
            if v is None:
                continue
            q = f[f"op_prev_{key}_per_day"] if _m else None
            rows.append({"name": lab, "now": yen_man(v),
                         "prev": yen_man(q) if q is not None else "—",
                         "diff": yen_sman(v - q) if q is not None else "—",
                         "diff_raw": (v - q) if q is not None else 0,
                         "rate": rate(v, q) if q is not None else None,
                         "kind": (f"実績／同じ外来診療日数"
                                  f"（{cnt(f['days_actual_outpatient'], '日')}）まで累計した前年と比較"
                                  if q is not None else
                                  f"実績／外来診療{cnt(f['days_actual_outpatient'], '日')}"
                                  "・前年の外来診療日数が無いため比較しない")})
    # --- ここから月末見込み ---
    # 診療日数は前年と数え方が違うため、差を出さず今月の内訳だけを載せる。
    d_days = None
    if not f["has_outpatient_days"]:
        rows.append({"name": "外来診療日あたり売上", "now": "算出不可",
                     "prev": "—", "diff": "—", "diff_raw": 0, "rate": None,
                     "kind": "この基準日のスナップショットに外来診療日数が入っていないため"})
    d_pd = None
    d_ipd = None
    if f["has_outpatient_days"] and f["ins_per_day_now"] is not None:
        rows.append({"name": "うち外来保険（月末見込み・外来診療日あたり）",
                     "now": yen_man(f["ins_per_day_now"]), "prev": "—", "diff": "—",
                     "diff_raw": 0, "rate": None,
                     "kind": f"月末見込み／外来診療{cnt(f['days_month_outpatient'], '日')}"
                             "・前年は同じ数え方の日数が無いため比較しない"})
    d_vis = add("来院回数", f["visit"], f["visit_prev"],
                lambda v: cnt(v, "回"), lambda v: scnt(v, "回"))
    d_vpd = None
    d_pv = add("1来院あたり売上（外来保険＋自費＋物販）", f["per_visit_now"], f["per_visit_prev"],
               lambda v: cnt(v, "円"), lambda v: scnt(v, "円"))
    d_pat = add("患者数", f["patients"], f["patients_prev"],
                lambda v: cnt(v, "人"), lambda v: scnt(v, "人"))
    d_sho = add("初診", f["shoshin"], f["shoshin_prev"],
                lambda v: cnt(v, "件"), lambda v: scnt(v, "件"))

    if f["cancel_rate"] is not None and f["cancel_rate_prev"] is not None:
        d_can = f["cancel_rate"] - f["cancel_rate_prev"]
        rows.append({"name": "キャンセル率", "now": f"{f['cancel_rate']:.1f}%",
                     "prev": f"{f['cancel_rate_prev']:.1f}%", "diff": f"{d_can:+.1f}pt",
                     "diff_raw": d_can, "rate": None,
                     "kind": "実績／前年は月末実績"})
    else:
        d_can = None

    # 判定
    volume_up = (d_vis is not None and d_vis > 0)
    density_up = (d_pd is not None and bool(f["per_day_prev"])
                  and d_pd / f["per_day_prev"] > DENSITY_ALERT)
    density_dn = (d_pd is not None and bool(f["per_day_prev"])
                  and d_pd / f["per_day_prev"] < -DENSITY_ALERT)
    ins_density_up = (d_ipd is not None and bool(f["ins_per_day_prev"])
                      and d_ipd / f["ins_per_day_prev"] > DENSITY_ALERT)
    per_visit_dn = (d_pv is not None and bool(f["per_visit_prev"])
                    and d_pv / f["per_visit_prev"] < -DENSITY_ALERT)

    parts = []
    # --- 実績で見た稼働（主指標）---
    if f["has_outpatient_days"]:
        seg = []
        for key, lab in (("outpatient", "外来保険"), ("selfpay", "自費"), ("product", "物販")):
            v = f[f"obs_{key}_per_day"]
            if v is not None:
                seg.append(f"{lab}{yen_man(v)}")
        parts.append(f"外来診療を行った{cnt(f['days_actual_outpatient'], '日')}で見ると、"
                     f"1日あたり{yen_man(f['op_per_day_actual'])}です"
                     "（外来保険＋自費＋物販。訪問・介護だけ売上が立った日は数えていません）。"
                     + (f"内訳は{'、'.join(seg)}です。" if seg else "")
                     + f"月末見込みでは外来診療{cnt(f['days_month_outpatient'], '日')}で"
                     f"1日あたり{yen_man(f['op_per_day_month'])}になります"
                     "（月末見込みは、前年の外来診療日数が月次実績に無いため前年比較を出しません）。")
    else:
        parts.append("このスナップショットには外来診療日数が入っていないため、"
                     "外来診療日あたり売上は算出できません。"
                     "次の日次更新から表示されます。")
    if f["outpatient_days_match"]:
        nd = cnt(f["days_actual_outpatient"], "日")
        seg = []
        for key, lab in (("outpatient", "外来保険"), ("selfpay", "自費"), ("product", "物販")):
            a, b = f[f"obs_{key}_per_day"], f[f"op_prev_{key}_per_day"]
            if a is not None and b is not None:
                seg.append(f"{lab}{pct(rate(a, b))}")
        parts.append(f"前年も同じ外来診療日数（{nd}）まで累計すると"
                     f"{yen_man(f['obs_prev_total'])}、1日あたり{yen_man(f['op_per_day_prev'])}で、"
                     f"今年は{yen_sman(f['op_diff_total'])}（{pct(f['op_rate_total'])}）"
                     f"{_updown(f['op_diff_total'])}水準です。"
                     + (f"区分別の1日あたりは{'、'.join(seg)}です。" if seg else ""))
    elif f["obs_bizdays_raw_diff"] is not None:
        parts.append("前年の同時期との比較は、この画面では出していません。"
                     + ("前年側の外来診療日数がスナップショットに入っていないためです。"
                        if f["obs_prev_outpatient_days"] is None else
                        f"前年側の外来診療日数（{cnt(f['obs_prev_outpatient_days'], '日')}）が"
                        f"当年（{cnt(f['days_actual_outpatient'], '日')}）と一致せず、"
                        "同じ日数で比べられないためです。"))
    if f["days_month"] is None:
        parts.append("今月の診療日数が取得できません。")
    else:
        # 13 と 6 だけを並べると 22 と合わずに見えるため、3つとも書く。
        # 前年の日数は数え方が違うので、差は出さない。
        if f["has_outpatient_days"]:
            parts.append(f"今月の外来診療日数は{cnt(f['days_month_outpatient'], '日')}です。"
                         f"内訳は、外来診療を終えた{cnt(f['days_actual_outpatient'], '日')}、"
                         f"すでに終わったが売上がまだ入っていない{cnt(f['days_unrecorded'], '日')}、"
                         f"これから診療する{cnt(f['days_remaining'], '日')}です。")

    # --- 月末見込み（予測前提を含むことを明示）---
    if f.get("per_day_basis_gap") and f["days_prev"] is not None:
        parts.append("なお月次実績が持つ前年の日数は「売上が発生した日」を数えたもので、"
                     "訪問・介護だけ売上が立った日も含みます。数え方が違うため、"
                     "月の診療日数そのものの前年差は出していません。")
    if f["pace_gap_rate"] is not None and f["pace_gap_rate"] > PACE_ALERT:
        parts.append(f"月末見込みは、これから診療する{cnt(f['days_remaining'], '日')}に"
                     f"1日あたり{yen_man(f['per_day_needed'])}を積む前提を含んでいます。"
                     f"外来診療を行った{cnt(f['days_actual_outpatient'], '日')}の平均は"
                     f"{yen_man(f['per_day_done'])}で、必要な水準はこれを"
                     f"{pct(f['pace_gap_rate'] * 100)}上回ります"
                     + (f"（売上がまだ入っていない{cnt(f['days_unrecorded'], '日')}は"
                        f"1日あたり{yen_man(f['per_day_unrecorded'])}の推定）"
                        if f["per_day_unrecorded"] else "")
                     + "。実績がこの水準に達しているわけではありません。")
    if d_vis is not None:
        parts.append(f"来院回数は{cnt(f['visit'], '回')}の見込みで前年実績{cnt(f['visit_prev'], '回')}を"
                     f"{scnt(d_vis, '回')}（{pct(rate(f['visit'], f['visit_prev']))}）"
                     f"{_updown(d_vis)}見込みです。")
    if per_visit_dn and volume_up:
        parts.append(f"一方で1来院あたりの売上は見込みで{cnt(f['per_visit_now'], '円')}となり、前年実績"
                     f"{cnt(f['per_visit_prev'], '円')}を"
                     f"{pct(rate(f['per_visit_now'], f['per_visit_prev']))}下回る計算です。"
                     "来院は増える一方で、1回あたりの単価は下がる見込みです。")

    if f["pace_gap_rate"] is not None and f["days_remaining"]:
        if f["pace_gap_rate"] < -PACE_ALERT:
            parts.append(f"残り{cnt(f['days_remaining'], '日')}は1日あたり"
                         f"{yen_man(f['per_day_needed'])}の見込みで、今月ここまでの平均"
                         f"{yen_man(f['per_day_done'])}を下回る控えめな前提です。")

    # 吸収の判定は、日数を揃えて比べられる総額（obs_diff）だけで行う。
    # 1日あたりは前年側に同じ数え方の日数が無いため使わない。
    return {"text": "".join(parts), "rows": rows,
            "obs_diff": f["op_diff_total"],
            "obs_down": (f["op_diff_total"] is not None and f["op_diff_total"] < 0),
            "obs_ins_up": False,
            "volume_up": volume_up, "density_up": density_up, "density_dn": density_dn,
            "ins_density_up": ins_density_up, "per_visit_dn": per_visit_dn,
            "days_diff": d_days, "visit_diff": d_vis, "shoshin_diff": d_sho,
            "patient_diff": d_pat, "cancel_diff": d_can,
            "per_day_diff": d_pd, "per_visit_diff": d_pv}


# ======================================================================
# 5. 構造変化（診療日数の変化・通常営業ベースとの差）
# ======================================================================
def _structure(f, cap):
    gap = f["baseline_gap"]
    if f["baseline"] is None or gap is None:
        return None
    if not f["thursday_closed"] and not is_material(gap, f["baseline"]):
        return None
    if not is_material(gap, f["baseline"]):
        # 木曜休診はあるが差がほぼ無い月。ここは「差がない」と言い切ってよい。
        return {"text": (f"通常営業だった場合の見込み{yen_man(f['baseline'])}と現在の着地見込み"
                         f"{yen_man(f['total'])}の差は{yen_sman(gap)}で、ほとんどありません。"
                         "診療日を減らした分は他の曜日で吸収できている状態です。"),
                "short": f"通常営業だった場合との差は{yen_sman(gap)}で、ほとんどありません。",
                "gap": gap, "label": "木曜休診", "absorbed": True, "negligible": True}

    label = "木曜休診" if f["thursday_closed"] else "診療日の変更"
    parts = [f"{label}がない通常営業だった場合の見込み{yen_man(f['baseline'])}に対し、"
             f"現在の着地見込みは{yen_man(f['total'])}で、差は{yen_sman(gap)}です。",
             f"これは{label}による診療日数の減少で説明できる可能性がある範囲であり、"
             "確定した損失ではありません。"]

    # 吸収できているかは、当年と前年を同じ外来診療日数でそろえた比較でだけ語る。
    # 一致していない月・前年側の日数が無い月は判定しない。
    absorbed = False
    if f["outpatient_days_match"]:
        nd = cnt(f["days_actual_outpatient"], "日")
        if f["op_diff_total"] < 0:
            parts.append(f"前年と同じ外来診療日数（{nd}）まで累計して比べると、"
                         f"外来保険＋自費＋物販は{pct(f['op_rate_total'])}下回っており、"
                         f"{label}で減った分を吸収できているとまでは言えません。")
        else:
            absorbed = True
            parts.append(f"前年と同じ外来診療日数（{nd}）まで累計して比べても下回っておらず、"
                         f"{label}で減った分は他の曜日で埋められている状態です。")
    else:
        parts.append(f"{label}で減った分を他の曜日で吸収できているかは、この画面では"
                     "判定していません。当年と前年を同じ外来診療日数でそろえた比較が"
                     "必要ですが、前年側の外来診療日数がそろっていないためです。")

    return {"text": "".join(parts), "short": "".join(parts[:2]), "gap": gap,
            "label": label, "absorbed": absorbed, "negligible": False}


def _productivity_trend(f):
    """生産性の連続トレンド。基準を揃えられないときは判定そのものを出さない。

    使えるはずだった指標は2つあるが、cloud_deploy が持つデータでは
    どちらも過去月とそろえられない。

      外来診療日あたり売上
        過去月の外来診療日数を出せる列が monthly_actuals.csv に無い。
        「診療日数」は売上発生日数（訪問・介護だけの日を含む）で、外来診療日数ではない。

      売上発生日あたり総売上
        式そのものは全月そろっているが、木曜休診が始まると分母の中身が変わる。
        訪問・介護だけ売上が立つ木曜が分母に入り、1日あたりが機械的に下がる。
        これを生産性の低下とは読めない。

    そのため木曜休診が効いている間は判定を出さず、出さない理由を返す。
    定義がそろわない数字からトレンドを推測しない。
    """
    hist = f.get("hist") or {}
    series = [x for x in (hist.get("per_day") or []) if x["per_day"]]
    if len(series) < 4:
        return None
    if f.get("per_day_basis_gap"):
        return {"suppressed": True, "text": (
            "1日あたり売上の推移は、今回は判定を出していません。"
            "木曜休診が始まってから、訪問・介護だけ売上が立つ木曜が現れており、"
            "過去月と同じ数え方の「1日あたり」を作れないためです。"
            "月次実績に外来診療日数の列が入れば、外来診療日あたり売上として"
            "同じ基準で並べられるようになります。"),
            "months": 0, "direction": 0, "series": [], "days_diff": None}
    run, direction = 1, 0
    for i in range(len(series) - 1, 0, -1):
        d = series[i]["per_day"] - series[i - 1]["per_day"]
        cur_dir = 1 if d > 0 else (-1 if d < 0 else 0)
        if cur_dir == 0:
            break
        if direction == 0:
            direction = cur_dir
        elif cur_dir != direction:
            break
        run += 1
    if run < 3 or direction == 0:
        return None

    seg = series[-run:]
    word = "低下" if direction < 0 else "上昇"
    chain = " → ".join(f"{x['ym'][5:7]}月 {x['per_day'] / MAN:.1f}万円" for x in seg)
    basis = hist.get("days_basis", HIST_DAYS_BASIS)
    d_days = seg[-1]["days"] - seg[0]["days"]
    parts = [f"{basis}あたりの総売上が{run}か月続けて{word}しています（{chain}）。"]
    if d_days > 0 and direction < 0:
        parts.append(f"同じ期間に診療日数は{cnt(seg[0]['days'], '日')}から"
                     f"{cnt(seg[-1]['days'], '日')}へ{scnt(d_days, '日')}増えており、"
                     f"{basis}を増やしながら1日あたりが落ちている形です。"
                     "月の売上が保たれていても、1日あたりの生産性は下がっています。")
    elif d_days < 0 and direction < 0:
        parts.append(f"同じ期間に診療日数も{scnt(d_days, '日')}減っており、"
                     "日数と1日あたりの両方が下がっています。")
    else:
        parts.append(f"同じ期間の診療日数は{cnt(seg[0]['days'], '日')}から"
                     f"{cnt(seg[-1]['days'], '日')}です。")
    parts.append("これは今月だけの動きではないため、月内の打ち手ではなく"
                 "来月以降の構造として扱います。")
    return {"text": "".join(parts), "months": run, "direction": direction,
            "series": seg, "days_diff": d_days}


# ======================================================================
# 6. 自費の見立て
# ======================================================================
def _hv_range(f):
    """高額な自費案件の見込みレンジ。両端0は『算出できていない』であって0円ではない。"""
    lo, hi = f["hv_low"], f["hv_high"]
    if lo is None or hi is None:
        return {"available": False, "reason": "missing"}
    if lo == 0 and hi == 0:
        return {"available": False, "reason": "zero"}
    if hi < lo:
        return {"available": False, "reason": "invalid"}
    return {"available": True, "low": lo, "high": hi}


def _selfpay_view(f, comps):
    sp = next((c for c in comps["main"] if c.key == "selfpay"), None)
    if sp is None:
        return None
    hv = _hv_range(f)
    ins = next((c for c in comps["main"] if c.key == "insurance"), None)

    outlier = _prevyear_outlier(f, "selfpay")
    parts = []
    if sp.material:
        parts.append(f"自費は前年を{yen_sman(sp.diff)}（{pct(sp.rate)}）{_updown(sp.diff)}見込みです。")
    else:
        parts.append(f"自費は{yen_man(sp.now)}の見込みで、前年{yen_man(sp.prev)}とほぼ同水準です。")

    if outlier:
        st = outlier["stats"]
        side = "高い" if outlier["high"] else "低い"
        parts.append(f"ただし直近{st['n']}か月の自費は{yen_man(st['min'])}〜{yen_man(st['max'])}"
                     f"（中央値{yen_man(st['median'])}）で動いており、今月の{yen_man(sp.now)}は"
                     f"{outlier['now_level']}です。前年同月は{outlier['prev_level']}の{side}月で、"
                     "前年差の大きさは自費の月次変動の範囲で説明できます。")
    elif (ins is not None and ins.material and sp.material and f["yoy"]
            and ins.diff * sp.diff < 0):
        share = abs(sp.diff) / abs(f["yoy"])
        if share >= 0.8:
            parts.append(f"保険は前年を{yen_sman(ins.diff)}{_updown_te(ins.diff)}ため、"
                         "今月の前年差は自費でほぼ説明できます。")

    if f["selfpay_confirmed"] is not None:
        parts.append(f"今月すでに計上されている自費は{yen_man(f['selfpay_confirmed'])}で、"
                     f"残りの期間に追加で計上される見込みが{yen_man(f['selfpay_remaining'])}、"
                     f"合わせて月末{yen_man(sp.now)}という組み立てです。")

    if f["target_sales"] is None:
        parts.append("自費の月次目標はデータに登録されていないため、目標との差は出していません。")

    if hv["available"]:
        parts.append(f"高額な自費案件から見込める金額は"
                     f"{yen_man(hv['low'])}〜{yen_man(hv['high'])}の範囲です。")
    elif hv["reason"] == "zero":
        parts.append("高額な自費案件の見込みレンジは、今月分の予約が予測モデル側の集計に"
                     "まだ入っていないため算出できていません（0円という意味ではありません）。"
                     "契約済み案件の金額は院内の管理表で確認してください。")
    else:
        parts.append("高額な自費案件の見込みレンジは、このスナップショットでは取得できていません。")

    return {"text": "".join(parts), "comp": sp, "hv": hv}


# ======================================================================
# 7. 打ち手の生成
# ======================================================================
# 並べ替えに使う金額の意味。名前を付けずに「影響額」とだけ書くと、
# その打ち手で動かせる金額だと誤解される。中身が違うものは違う名前で持つ。
AMOUNT_KINDS = ("前年差寄与", "着地リスク", "回復可能額", "関連差額", "金額換算なし")


# 並び順を決める軸。金額ではなくこの3つで決める。いずれも 1 が高い。
#   directness … 手を打つと今月の着地が動くか
#   urgency    … 残り日数のうちに動かないと取り返せないか
#   confidence … その判断の根拠が実測か、予測前提を含むか、仮説か
AXIS_LABELS = {
    "directness": {1: "着地に直接効く", 2: "今月の判断材料になる", 3: "主に来月以降に効く"},
    "urgency": {1: "残り日数内に動く必要がある", 2: "今月中に確認すればよい", 3: "締切なし"},
    "confidence": {1: "実測から言える", 2: "予測前提を含む", 3: "仮説"},
}


def _act(headline, target, why, check, decide, tier, amount, amount_kind,
         inmonth=True, directness=2, urgency=2, confidence=2):
    """amount は打ち手の意味を説明する補助情報であって、順位は決めない。

    性質の違う金額（前年差寄与・着地リスク・回復可能額…）を大小比較しても
    経営上の意味がないため、順位は tier と上の3軸で決める。amount は
    同じ amount_kind どうしの並びを整えるときにだけ使う。

    inmonth=False は今月の残り日数では結果を動かせないもの。
    月内の打ち手と混ぜず、来月以降の構造課題として別枠に出す。
    """
    assert amount_kind in AMOUNT_KINDS, amount_kind
    for k, v in (("directness", directness), ("urgency", urgency),
                 ("confidence", confidence)):
        assert v in (1, 2, 3), (k, v)
    return {"headline": headline, "target": target, "why": why,
            "check": check, "decide": decide, "tier": tier,
            "amount": abs(amount) if amount is not None else 0.0,
            "amount_kind": amount_kind, "inmonth": bool(inmonth),
            "directness": directness, "urgency": urgency, "confidence": confidence}


def _rank(actions):
    """順位づけ。異なる amount_kind の金額どうしは比較しない。

    金額を使うのは「同じ amount_kind の中での並び」を決めるところだけで、
    その結果は順位そのものではなく、上の軸が全部同点になったときの
    最後の手がかりとしてしか効かない。
    """
    rank_in_kind = {}
    for kind in AMOUNT_KINDS:
        same = sorted([a for a in actions if a["amount_kind"] == kind],
                      key=lambda a: -a["amount"])
        for i, a in enumerate(same):
            rank_in_kind[id(a)] = i
    return sorted(actions, key=lambda a: (a["tier"], a["directness"], a["urgency"],
                                          a["confidence"], rank_in_kind[id(a)]))


def _actions(f, comps, cause, cap, stru, spv):
    out = []
    main = {c.key: c for c in comps["main"]}
    sub = {c.key: c for c in comps["sub"]}
    sp = main.get("selfpay")
    ins = main.get("insurance")
    prod = main.get("product")
    n_rem = cnt(f["days_remaining"], "日") if f["days_remaining"] is not None else "残り"

    # --- 自費が前年割れ ---------------------------------------------------
    sp_outlier = _prevyear_outlier(f, "selfpay") if sp is not None else None
    if sp is not None and sp.material and sp.diff < 0 and sp_outlier:
        # 前年が高月で今月が平常範囲。案件棚卸しではなく、水準の監視に切り替える。
        st = sp_outlier["stats"]
        out.append(_act("自費が平常の範囲に収まっているかを、前年比ではなく水準で確認する",
                        "自費の月次水準",
                        f"自費は前年を{yen_sman(sp.diff)}下回りますが、前年同月"
                        f"{yen_man(sp.prev)}は直近{st['n']}か月で{sp_outlier['prev_level']}の"
                        f"高い月でした。今月の{yen_man(sp.now)}は中央値{yen_man(st['median'])}"
                        "と同水準で、構造的に減っている証拠は現時点ではありません。",
                        [f"直近{st['n']}か月の自費の並び"
                         f"（{yen_man(st['min'])}〜{yen_man(st['max'])}）における今月の位置",
                         f"確定した自費 {yen_man(f['selfpay_confirmed'])}＋"
                         f"残り期間の追加見込み {yen_man(f['selfpay_remaining'])}"
                         f"＝月末{yen_man(sp.now)}という内訳"],
                        f"今月が下位25%（{yen_man(st['q1'])}未満）に入っていなければ、"
                        "月内の追加対応は不要です。2か月続けて下位25%に入った場合にだけ、"
                        "案件不足として初診からの自費相談の導線を見直します。",
                        T_LEADING, abs(sp.diff), "関連差額",
                        directness=2, urgency=2, confidence=1))
    elif sp is not None and sp.material and sp.diff < 0:
        why = [f"自費は前年を{yen_sman(sp.diff)}下回る見込みです。"]
        if ins is not None and ins.material and ins.diff > 0:
            why.append(f"保険は前年を{yen_sman(ins.diff)}上回っているため、"
                       "今月の前年割れは自費の不足でほぼ説明できます。")
        check = []
        if f["selfpay_confirmed"] is not None:
            check.append(f"今月すでに計上された自費 {yen_man(f['selfpay_confirmed'])}")
        if f["selfpay_remaining"] is not None:
            check.append(f"残りの期間に追加で計上される見込みの自費 "
                         f"{yen_man(f['selfpay_remaining'])}"
                         f"（確定分と合わせて月末{yen_man(sp.now)}）")
        check.append("契約済み案件を A＝今月中に売上計上できるもの／"
                     "B＝翌月以降に売上計上されるもの に分けた金額")
        rem_txt = yen_man(f["selfpay_remaining"])
        decide = (
            f"Aの合計が、残りの期間に追加で見込んでいる自費{rem_txt}に届くなら、"
            f"今の着地見込み{yen_man(f['total'])}を維持できる根拠になります。"
            f"Aがこの{rem_txt}に届かないなら、その不足分だけ今月の自費の着地を下方に見直します"
            "（今月の着地は下がります）。"
            "Bが大きい場合、今月足りない分のうちBに当たる部分は案件そのものの不足ではなく"
            "売上に計上される時期のずれと判断します。"
            "ただしBは今月の売上には戻らないため、今月の着地は下げたうえで、"
            "Bは翌月の先行売上として別に管理します。")
        if spv and not spv["hv"]["available"]:
            decide += "（高額案件の見込みレンジは自動では出せていないため、院内の管理表で数えます。）"
        out.append(_act("自費の不足が、案件不足なのか売上に計上される時期のずれなのかを切り分ける",
                        "今月分の契約済み自費案件", "".join(why), check, decide,
                        T_DRIVER, sp.diff, "前年差寄与",
                        directness=1, urgency=1, confidence=2))

    # --- 自費が上振れ -----------------------------------------------------
    if sp is not None and sp.material and sp.diff > 0:
        out.append(_act("自費の上振れが今月限りか、来月以降も続くのかを見極める",
                        "今月計上された自費案件",
                        f"自費は前年を{yen_sman(sp.diff)}上回る見込みで、今月の着地を押し上げています。",
                        [f"今月計上された自費 {yen_man(f['selfpay_confirmed'])}のうち"
                         "高額案件の件数と金額",
                         "来月以降に計上予定の契約済み案件の金額"],
                        "高額案件が特定の月に偏っているだけなら、来月は反動で落ちる前提で見ます。"
                        "件数そのものが増えているなら、来月以降も同じ水準を計画に入れられます。",
                        T_DRIVER, sp.diff, "前年差寄与",
                        directness=2, urgency=3, confidence=2))

    # --- 保険が前年割れ ---------------------------------------------------
    if ins is not None and ins.material and ins.diff < 0:
        why = [f"保険診療は前年を{yen_sman(ins.diff)}下回る見込みです。"]
        op = sub.get("outpatient")
        if op is not None and op.material:
            why.append(f"内訳では外来保険が{yen_sman(op.diff)}です。")
        out.append(_act("保険診療の減少が、来院数の減少なのか1回あたりの単価なのかを分ける",
                        "外来保険", "".join(why),
                        [f"外来診療日あたりの外来保険（今月見込み"
                         f"{yen_man(f['ins_per_day_now'])}）",
                         f"来院回数（今月見込み{cnt(f['visit'], '回')}／"
                         f"前年{cnt(f['visit_prev'], '回')}）"],
                        "来院回数が前年並みで1日あたりが下がっているなら、処置内容や算定の問題です。"
                        "来院回数そのものが減っているなら、予約枠の埋まり方の問題として扱います。",
                        T_DRIVER, ins.diff, "前年差寄与",
                        directness=1, urgency=2, confidence=1))

    # --- 保険が今月を支えている（維持できるか）-----------------------------
    if (ins is not None and ins.material and ins.diff > 0
            and f["days_remaining"]):
        check = [f"残り{n_rem}分の予約 {cnt(f['reservation_remaining'], '件')}"
                 + (f"（月末までの追加を見込んで{cnt(f['reservation_projected'], '件')}）"
                    if f["reservation_projected"] is not None else "")]
        if f["ins_per_day_now"] is not None:
            check.append("外来診療日あたりの外来保険が"
                         f"{yen_man(f['ins_per_day_now'])}を保てているか")
        out.append(_act(f"保険診療の来院水準を残り{n_rem}も保てるかを確認する",
                        "残りの診療日の予約",
                        f"保険は前年を{yen_sman(ins.diff)}上回り、今月の着地を支えています。"
                        "ここが落ちると着地がそのまま下がります。",
                        check,
                        f"この水準を保てるなら着地{yen_man(f['total'])}は妥当です。"
                        f"落ちる場合は保守ライン{yen_man(f['conservative'])}側に寄るものとして見ます。",
                        T_INMONTH, ins.diff, "前年差寄与",
                        directness=1, urgency=1, confidence=2))

    # --- 残り期間に必要なペース --------------------------------------------
    if (f["pace_gap_rate"] is not None and f["pace_gap_rate"] > PACE_ALERT
            and f["days_remaining"]):
        out.append(_act(f"残り{n_rem}に必要なペースが今月の平均を上回っている点を確認する",
                        "残りの診療日",
                        f"着地見込み{yen_man(f['total'])}は、残り{n_rem}で1日あたり"
                        f"{yen_man(f['per_day_needed'])}を積む前提です。今月ここまでの平均は"
                        f"{yen_man(f['per_day_done'])}で、{pct(f['pace_gap_rate'] * 100)}"
                        "高いペースが必要です。",
                        [f"残り{n_rem}の予約 {cnt(f['reservation_remaining'], '件')}と"
                         "空いている枠の数",
                         "今月キャンセルになった枠のうち、まだ次の予約が入っていない患者の数"],
                        f"空き枠が埋まる見込みが立たない場合、着地は保守ライン"
                        f"{yen_man(f['conservative'])}に近づくものとして扱います。"
                        f"着地見込みとの差は{yen_man(f['conservative_gap'])}です。"
                        f"なお、必要ペースに届かない分だけを積み上げると"
                        f"{yen_man(f['pace_gap_yen'])}相当です。",
                        T_INMONTH, f["pace_gap_yen"], "着地リスク",
                        directness=1, urgency=1, confidence=1))

    # --- 来院回数が前年割れ -------------------------------------------------
    if cap["visit_diff"] is not None and cap["visit_diff"] < 0 and f["per_visit_prev"]:
        loss = abs(cap["visit_diff"]) * f["per_visit_prev"]
        if is_material(loss):
            out.append(_act(f"来院回数の不足を残り{n_rem}の空き枠で埋められるかを確認する",
                            "残りの診療日の空き枠と、キャンセルになった枠",
                            f"来院回数は{cnt(f['visit'], '回')}の見込みで前年を"
                            f"{scnt(cap['visit_diff'], '回')}下回ります。前年の1来院あたり売上"
                            f"{cnt(f['per_visit_prev'], '円')}で換算すると、"
                            f"およそ{yen_man(loss)}分の下押しです。",
                            [f"残り{n_rem}の空き枠の数",
                             f"今月キャンセルになった{cnt(f['cancel_count'], '件')}のうち、"
                             "次の予約が入っていない患者の数"],
                            "既存患者の再予約で埋められる枠がどれだけあるかを見て、"
                            "着地見込みを維持できるか下方に見直すかを決めます。",
                            T_INMONTH, loss, "着地リスク",
                        directness=1, urgency=1, confidence=2))

    # --- キャンセル率の悪化 --------------------------------------------------
    if (cap["cancel_diff"] is not None and cap["cancel_diff"] > CANCEL_ALERT_PT
            and f["reservations_registered"] and f["per_visit_prev"]):
        extra = f["reservations_registered"] * cap["cancel_diff"] / 100.0
        loss = extra * f["per_visit_prev"]
        out.append(_act("キャンセル率の上昇が来院数をどれだけ削っているかを確認する",
                        "今月の登録済み予約",
                        f"キャンセル率は現時点の実績で{f['cancel_rate']:.1f}%、"
                        f"前年同月実績{f['cancel_rate_prev']:.1f}%を"
                        f"{cap['cancel_diff']:+.1f}pt上回っています。今月の予約"
                        f"{cnt(f['reservations_registered'], '件')}に対して"
                        f"およそ{cnt(extra, '件')}多くキャンセルが出ている計算です。",
                        ["キャンセルが集中している曜日・時間帯",
                         "前日までに連絡があったものと当日分の件数"],
                        f"前年並みまで戻せば来院がおよそ{cnt(extra, '回')}、"
                        f"金額でおよそ{yen_man(loss)}戻る計算になります。"
                        "戻せない場合は、キャンセルを見込んだ予約の入れ方に変えるかを判断します。",
                        T_LEADING, loss, "回復可能額",
                        directness=2, urgency=2, confidence=1))

    # --- 初診 ----------------------------------------------------------------
    if cap["shoshin_diff"] is not None and f["shoshin_prev"]:
        if cap["shoshin_diff"] < 0 and abs(cap["shoshin_diff"]) / f["shoshin_prev"] > 0.05:
            out.append(_act("初診の減少が来月以降の売上に効く前に、流入元を確認する",
                            "今月の初診",
                            f"初診は{cnt(f['shoshin'], '件')}の見込みで前年"
                            f"{cnt(f['shoshin_prev'], '件')}を{scnt(cap['shoshin_diff'], '件')}"
                            "下回ります。初診は当月よりも来月以降の売上に効きます。",
                            ["初診の流入元別の件数", "初診から2回目の予約に進んだ割合"],
                            "流入そのものが減っているなら来月以降の計画を下げます。"
                            "流入は変わらず2回目に進んでいないなら、初回の説明内容を見直します。",
                            T_LEADING, abs(cap["shoshin_diff"]) * (f["per_visit_prev"] or 0), "関連差額",
                        directness=3, urgency=3, confidence=1))
        elif cap["shoshin_diff"] > 0 and sp is not None and sp.material and sp.diff < 0:
            sp_note = ("自費は前年を下回りますが、これは前年が高い月だったことが大きく、"
                       "今月の水準そのものは平常の範囲です。"
                       if sp_outlier else
                       f"自費は前年を{yen_sman(sp.diff)}下回っています。")
            out.append(_act("初診が前年を上回っているうちに、自費相談への流れを作る",
                            "今月の初診",
                            f"初診は{cnt(f['shoshin'], '件')}で前年を"
                            f"{scnt(cap['shoshin_diff'], '件')}上回っています。" + sp_note,
                            ["初診のうち自費の相談・治療計画の説明まで進んだ件数",
                             "そのうち今月中に契約に至った件数"],
                            "初診は増えているのに自費の相談に進んでいないなら、"
                            "今月ではなく来月以降の自費を作る打ち手として初診対応を見直します。",
                            T_LEADING, 0.0, "金額換算なし",
                        directness=3, urgency=3, confidence=2))

    # --- 構造変化（診療日数）--------------------------------------------------
    if stru is not None and not stru.get("negligible"):
        check = []
        if f["ins_per_day_now"] is not None:
            check.append(f"{stru['label']}以外の曜日の外来診療日あたり外来保険"
                         f"（今月見込み{yen_man(f['ins_per_day_now'])}）")
        check.append("外来診療日ごとの来院回数（前年と並べるには月次実績に"
                     "外来診療日数の列が必要）")
        if not check:
            check = ["診療日ごとの来院回数と外来保険売上を前年同月と並べた表"]
        decide = ("前年より高い水準が続いているなら、減った診療日の分は他の曜日で吸収できていると"
                  "判断してよい範囲です。下がってくるなら、減った分がそのまま売上減になるため、"
                  "枠の増設や診療日の見直しを検討します。")
        out.append(_act(f"{stru['label']}で減った診療日が、他の曜日でどこまで吸収できているかを確認する",
                        "通常営業だった場合との差",
                        stru.get("short") or stru["text"], check, decide,
                        T_STRUCTURE, stru["gap"], "関連差額", inmonth=False,
                        directness=2, urgency=3, confidence=2))

    # --- 介護（制度改定の影響）-----------------------------------------------
    care = sub.get("care")
    if care is not None and care.material and care.diff < 0 and f["care_regime_changed"]:
        out.append(_act("介護売上の減少が制度改定後の新しい水準なのかを確かめる",
                        "介護売上",
                        f"介護は{yen_man(care.now)}の見込みで前年{yen_man(care.prev)}を"
                        f"{yen_sman(care.diff)}下回ります。{f['care_revision_month']}の"
                        "制度改定後の水準をもとに見込んでおり、"
                        + ("改定後の確定月がまだ少ないため精度は高くありません。"
                           if f["care_data_insufficient"]
                           else "改定前の金額とは単純に比較できません。"),
                        ["改定後の各月の介護売上と訪問した日数",
                         "算定できていない項目がないか"],
                        "改定後の水準として妥当なら、来年度の計画をこの水準に置き換えます。"
                        "算定漏れがあるなら今月中に修正します。",
                        T_STRUCTURE, care.diff, "前年差寄与", inmonth=False,
                        directness=2, urgency=3, confidence=2))

    # --- 訪問保険 --------------------------------------------------------------
    vi = sub.get("visit_ins")
    if vi is not None and vi.material and vi.diff < 0:
        out.append(_act("訪問診療の件数が落ちていないかを確認する",
                        "訪問保険",
                        f"訪問保険は{yen_man(vi.now)}の見込みで前年を{yen_sman(vi.diff)}下回ります。",
                        ["今月の訪問した日数と訪問先の件数", "前年同月の訪問した日数"],
                        "訪問した日数が減っているなら訪問枠の組み方の問題、"
                        "日数が同じで金額が落ちているなら算定内容の問題として扱います。",
                        T_NEXT, vi.diff, "前年差寄与", inmonth=False,
                        directness=3, urgency=3, confidence=2))

    # --- 物販 ------------------------------------------------------------------
    if prod is not None and prod.material and prod.diff < 0:
        out.append(_act("物販の落ち込みが在庫か案内かを確認する", "物販",
                        f"物販は{yen_man(prod.now)}の見込みで前年を{yen_sman(prod.diff)}下回ります。",
                        ["主力商品の在庫切れの有無", "自費の説明時に物販を案内した件数"],
                        "在庫切れなら発注、案内が減っているなら説明の流れに戻します。",
                        T_NEXT, prod.diff, "前年差寄与",
                        directness=2, urgency=2, confidence=1))

    # 生産性トレンドは今月の打ち手ではなく、来月以降の構造課題として置く（A-6）
    trend = _productivity_trend(f)
    if trend is not None and not trend.get("suppressed"):
        word = "低下" if trend["direction"] < 0 else "上昇"
        out.append(_act(f"1診療日あたりの生産性が{trend['months']}か月続けて{word}している"
                        "原因を分解する",
                        "診療日数と1日あたり売上",
                        trend["text"],
                        ["月ごとの 診療日数 / 1日あたり売上 / 1日あたり来院回数",
                         "同じ期間の自費と外来保険の1日あたりの推移"],
                        "1日あたり来院回数が下がっているなら予約の埋まり方の問題、"
                        "来院回数は同じで金額が下がっているなら診療内容と単価の問題です。"
                        "来月以降の計画をどちらの前提で置くかを決めます。",
                        T_NEXT, 0.0, "金額換算なし", inmonth=False,
                        directness=3, urgency=3, confidence=1))

    # 今月の打ち手は「月内に動かせるもの」だけ。売上影響→緊急性の順に並べる。
    inmonth = [a for a in out if a["inmonth"]]
    later = [a for a in out if not a["inmonth"]]
    return _rank(inmonth)[:MAX_ACTIONS], _rank(later)


# ======================================================================
# 8. 今月の結論 / 月末までの最大論点
# ======================================================================
def now_of_key(f, key):
    return {"total": f["total"], "insurance": f["insurance"], "selfpay": f["selfpay"],
            "product": f["product"], "outpatient": f["outpatient"],
            "visit_ins": f["visit_ins"], "care": f["care"]}.get(key)


def _conclusion(f, comps, cause, cap):
    if f["total"] is None:
        return ["着地見込みが取得できないため、今月の結論を出せません。"]

    s = []
    head = f"今月の着地見込みは{yen_man(f['total'])}です。"
    if f["prev_total"] is not None:
        head += (f"前年同月{yen_man(f['prev_total'])}に対して{yen_sman(f['yoy'])}"
                 f"（{pct(f['yoy_rate'])}）の見込みです。")
    s.append(head)

    main = cause.get("main")
    offs = cause.get("offsets") or []
    out = _prevyear_outlier(f, main.key) if main is not None else None
    if main is not None:
        if out:
            # 前年が分布の端にいる区分は「今月が落ちた／伸びた」と断定しない（A-1）
            side = "高い" if out["high"] else "低い"
            st = out["stats"]
            s.append(f"前年差のほとんどは{main.name}の{yen_sman(main.diff)}によるものですが、"
                     f"前年同月の{yen_man(main.prev)}は直近{st['n']}か月で"
                     f"{out['prev_level']}にあたる{side}月でした。"
                     f"今月の{yen_man(main.now)}は中央値{yen_man(st['median'])}と同水準で、"
                     f"{main.name}が落ち込んだというより前年が{side}月だったと見るのが妥当です。")
        elif offs:
            s.append(f"内訳では{_join([c.name for c in offs[:2]])}が前年を上回る一方、"
                     f"{main.name}が{yen_sman(main.diff)}で、これが前年差の主因です。")
        else:
            s.append(f"内訳では{main.name}の{yen_sman(main.diff)}が最大の要因です。")
    elif cause.get("flat"):
        s.append("内訳にも前年から大きく動いた項目はありません。")

    # 前年比だけでは意味が伝わらない水準を拾う（A-4）
    hist = f.get("hist") or {}
    if hist.get("available"):
        n = (hist["stats"].get("total") or {}).get("n", HIST_MONTHS)
        NAMES = {"total": "総売上", "insurance": "保険診療", "selfpay": "自費診療",
                 "product": "物販"}
        notable = []
        for k in ("insurance", "selfpay", "product", "total"):
            lv = f["level_now"].get(k)
            if lv in ("最高", "最低"):
                st = hist["stats"].get(k) or {}
                prev_best = st.get("max") if lv == "最高" else st.get("min")
                notable.append(
                    f"{NAMES[k]}の{yen_man(now_of_key(f, k))}は直近{n}か月で{lv}水準です"
                    f"（これまでの{lv}は{yen_man(prev_best)}）")
        if notable:
            s.append("、".join(notable) + "。")

    if f.get("outpatient_days_match"):
        s.append(f"実績では、前年を同じ外来診療日数"
                 f"（{cnt(f['days_actual_outpatient'], '日')}）まで累計した金額と比べて"
                 f"{pct(f['op_rate_total'])}{_updown(f['op_diff_total'])}水準です。")

    ups, downs = [], []
    for name, d in (("来院回数", cap["visit_diff"]), ("患者数", cap["patient_diff"]),
                    ("初診", cap["shoshin_diff"])):
        if d is None or d == 0:
            continue
        (ups if d > 0 else downs).append(name)
    # 件数はいずれも月末見込み。実績確定値と読めない書き方にする。
    # 「稼働が主因ではない」と言えるのは、売上が前年を下回っている月だけ。
    down_month = (f["yoy"] is not None and f["yoy"] < 0
                  and is_material(f["yoy"], f["prev_total"]))
    if len(ups) >= 2 and not downs:
        if down_month:
            s.append(f"月末見込みでは、{_join(ups)}はいずれも前年を上回る見込みです。"
                     "現時点では、診療の稼働そのものが弱いことが前年を下回る主因とは見ていません。")
        else:
            s.append(f"月末見込みでは、{_join(ups)}はいずれも前年を上回る見込みで、"
                     "稼働の面でも前年を上回る形です。")
    elif len(downs) >= 2 and not ups:
        if down_month:
            s.append(f"月末見込みでは、{_join(downs)}がいずれも前年を下回る見込みです。"
                     "現時点では、診療の稼働そのものが弱まっている可能性が高いと見ています。")
        else:
            s.append(f"月末見込みでは、{_join(downs)}がいずれも前年を下回る見込みです。"
                     "売上は前年を上回る見込みですが、稼働の量は前年に届いていません。")

    if f["prev_forecast_diff"] is not None and is_material(f["prev_forecast_diff"], f["total"]):
        tail = (f"前回（{f['prev_forecast_asof']}）の{yen_man(f['prev_forecast'])}から"
                f"{yen_sman(f['prev_forecast_diff'])}動きました。")
        if (f["prev_forecast_selfpay_diff"] is not None
                and abs(f["prev_forecast_selfpay_diff"]) >= abs(f["prev_forecast_diff"]) * 0.5):
            tail += f"うち自費が{yen_sman(f['prev_forecast_selfpay_diff'])}です。"
        s.append(tail)

    return s[:5]


def _focus(f, actions):
    """月末までにまだ変えられるものだけを論点にする。"""
    left = cnt(f["days_remaining"], "日") if f["days_remaining"] is not None else "残り日数不明"
    inmonth = [a for a in actions if a.get("inmonth", True)]
    if not inmonth:
        return (f"今月の残り{left}で動かせる論点は、現在のデータからは見つかっていません。"
                "来月以降の構造課題を参照してください。")
    txt = f"月末まで残り{left}。今から変えられる最大の論点は「{inmonth[0]['headline']}」です。"
    if len(inmonth) > 1:
        txt += f"次に「{inmonth[1]['headline']}」です。"
    if f["conservative"] is not None and f["total"] is not None:
        txt += (f"ここが崩れると着地は保守ライン{yen_man(f['conservative'])}側へ、"
                f"保てれば{yen_man(f['total'])}が妥当な線になります。")
    if f.get("optimistic"):
        txt += ("なお着地見込みには上振れ前提が入っています。"
                + "".join(o["text"] for o in f["optimistic"])
                + f"この2つを外すと着地はおよそ{yen_man(f['total_without_optimistic'])}です。"
                if len(f["optimistic"]) == 2 else
                "なお着地見込みには上振れ前提が入っています。"
                + "".join(o["text"] for o in f["optimistic"])
                + f"これを外すと着地はおよそ{yen_man(f['total_without_optimistic'])}です。")
    return txt


# ======================================================================
# 9. データの注意書き
# ======================================================================
def _data_notes(f):
    notes = []
    if not f["has_prev_year_row"]:
        notes.append("前年同月の月次実績が読めないため、外来・訪問・介護の内訳と、"
                     "1日あたり・1来院あたりの前年比較は出していません。")
    if f["target_sales"] is None:
        notes.append("売上目標がデータに登録されていないため、目標との差は表示していません。")
    hv = _hv_range(f)
    if not hv["available"]:
        if hv["reason"] == "zero":
            notes.append("高額な自費案件の見込みレンジは、今月分の予約が予測モデル側の集計に"
                         "入っていないため算出できず、上下限とも0で出力されています。"
                         "これは「0円の見込み」ではないため、金額としては表示していません。")
        else:
            notes.append("高額な自費案件の見込みレンジは、"
                         "このスナップショットでは取得できていません。")
    if f["care_data_insufficient"]:
        notes.append(f"介護は{f['care_revision_month']}の制度改定後の確定月がまだ少なく、"
                     "見込みの幅が広い状態です。")
    if f["data_status_resec"] and f["data_status_resec"] != "反映済み":
        notes.append("当月のレセコン実績が未反映のため、経過分も推定値で計算しています。")
    return notes


# ======================================================================
# 入口
# ======================================================================
def build_management_report(roll, prev_year_row=None, prev_forecast_row=None,
                            history_rows=None):
    f = _facts(roll, prev_year_row, prev_forecast_row, history_rows)
    comps = _components(f)
    cause = _yoy_cause(f, comps)
    cap = _capacity(f)
    stru = _structure(f, cap)
    spv = _selfpay_view(f, comps)
    actions, later = _actions(f, comps, cause, cap, stru, spv)
    return {
        "next_month_actions": later,
        "trend": _productivity_trend(f),
        "facts": f,
        "components": comps,
        "conclusion": _conclusion(f, comps, cause, cap),
        "cause": cause,
        "capacity": cap,
        "structure": stru,
        "selfpay": spv,
        "focus": _focus(f, actions),
        "actions": actions,
        "notes": _data_notes(f),
    }
