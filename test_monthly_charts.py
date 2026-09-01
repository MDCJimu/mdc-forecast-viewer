# -*- coding: utf-8 -*-
"""test_monthly_charts.py — 月次グラフの横軸が「暦の1か月ごと」であることの回帰テスト

背景
  過去実績画面の「売上の推移」で、横軸に 2026-04 が4回、2026-05 が4回…と
  同じ月名が並んだ。原因はデータではなく横軸の目盛り粒度。
  時間軸（月:T）のまま tick 粒度を自動に任せると、表示期間が短い月
  （今年度が4か月など）で週ごとの目盛りが選ばれ、それを %Y-%m で整形するため
  同じ月名が繰り返される。目盛りの「本数」ではなく「間隔」を固定して直した。

  monthly_actuals.csv は1か月1行で正しく、集計側は一切変えていない。
  このテストは「入力は月ごとに1行のまま」「横軸は月間隔」の両方を見張る。

実行:
    py cloud_deploy/test_monthly_charts.py
"""
import io
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)                       # streamlit_app はカレントからデータを読む

import pandas as pd                  # noqa: E402
import streamlit_app as A            # noqa: E402

MONTH_TICK = {"interval": "month", "step": 1}
ACTUALS = os.path.join(HERE, "data", "history", "monthly_actuals.csv")
PORTFOLIO = os.path.join(HERE, "data", "history", "portfolio_monthly.csv")

# 確定月は据え置きが原則（restatement を経ないと動かない）。動いたら気づきたい。
FY2026_TOTALS = {"2026-04": 22695610, "2026-05": 19078020,
                 "2026-06": 20221040, "2026-07": 20303270}


def x_encoding(chart):
    """facet されていても x エンコーディングを取り出す。"""
    spec = chart.to_dict()
    enc = spec.get("encoding") or (spec.get("spec") or {}).get("encoding") or {}
    return enc.get("x")


def tooltip_formats(chart):
    spec = chart.to_dict()
    enc = spec.get("encoding") or (spec.get("spec") or {}).get("encoding") or {}
    return [(t.get("field"), t.get("format")) for t in (enc.get("tooltip") or [])]


def fiscal_year_of(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    return y - 1 if m < 4 else y


class Base(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(ACTUALS):
            raise unittest.SkipTest("monthly_actuals.csv がない")
        df = pd.read_csv(ACTUALS, encoding="utf-8-sig").sort_values("年月")
        cls.df = df.reset_index(drop=True)
        cls.fin = (cls.df[cls.df["close_status"] == "finalized"]
                   if "close_status" in cls.df.columns else cls.df)

    def periods(self, agg):
        """画面の期間プリセットと同じ範囲（period_bounds と同じ意味）。"""
        months = list(agg["年月"])
        hi = months[-1]
        fy = fiscal_year_of(hi)
        return {
            "直近12か月": ((months[-12] if len(months) >= 12 else months[0]), hi),
            "今年度": (f"{fy}-04", f"{fy + 1}-03"),
            "昨年度": (f"{fy - 1}-04", f"{fy}-03"),
            "全期間": (months[0], hi),
        }

    def slice_(self, agg, lo, hi):
        return agg[(agg["年月"] >= lo) & (agg["年月"] <= hi)]


class TestSourceDataIsOneRowPerMonth(Base):
    """今回の不具合はグラフ側。元データが重複していないことを固定する。"""

    def test_monthly_actuals_has_exactly_one_row_per_month(self):
        self.assertEqual(len(self.df), self.df["年月"].nunique())
        self.assertEqual(self.df["年月"].duplicated().sum(), 0)

    def test_portfolio_monthly_pivots_to_one_row_per_month(self):
        if not os.path.exists(PORTFOLIO):
            self.skipTest("portfolio_monthly.csv がない")
        wide = A.pf_pivot(pd.read_csv(PORTFOLIO, encoding="utf-8-sig"))
        self.assertEqual(len(wide), len(set(wide.index)))


class TestMonthTickInterval(Base):
    """4つの月次グラフすべてで、横軸が月間隔になっていること。"""

    def _assert_month_axis(self, chart, label):
        x = x_encoding(chart)
        self.assertIsNotNone(x, label)
        self.assertEqual(x["type"], "temporal", label)
        axis = x.get("axis") or {}
        self.assertEqual(axis.get("tickCount"), MONTH_TICK, f"{label}: {axis}")
        self.assertEqual(axis.get("format"), "%Y-%m", label)      # 表示形式は据え置き
        self.assertEqual(axis.get("labelAngle"), -55, label)      # 見た目も据え置き

    def test_all_three_history_charts_in_every_period(self):
        for incl_prov in (False, True):
            agg = self.df if incl_prov else self.fin
            for name, (lo, hi) in self.periods(agg).items():
                p = self.slice_(agg, lo, hi)
                if p.empty:
                    continue
                for fn in (A.chart_total_sales, A.chart_breakdown, A.chart_visits):
                    label = f"{'暫定込' if incl_prov else '確定のみ'}/{name}/{fn.__name__}"
                    with self.subTest(case=label):
                        self._assert_month_axis(fn(p), label)

    def test_portfolio_stack_chart(self):
        if not os.path.exists(PORTFOLIO):
            self.skipTest("portfolio_monthly.csv がない")
        wide = A.pf_pivot(pd.read_csv(PORTFOLIO, encoding="utf-8-sig"))
        for tail in (4, 12, 24):
            with self.subTest(tail=tail):
                self._assert_month_axis(A.chart_pf_stack(wide.tail(tail)),
                                        f"chart_pf_stack/tail{tail}")

    def test_the_constant_is_a_月間隔_not_a_本数(self):
        """tick 数への置き換えではなく、間隔の固定であること。"""
        self.assertEqual(A.MONTH_TICK, MONTH_TICK)
        self.assertEqual(A.MONTH_TICK["interval"], "month")
        self.assertEqual(A.MONTH_TICK["step"], 1)


class TestChartInputsAreUnchanged(Base):
    """グラフへ渡す DataFrame の形と値。ここが変わったら集計side に触れている。"""

    def test_total_sales_input_is_one_point_per_month(self):
        p = self.slice_(self.fin, *self.periods(self.fin)["今年度"])
        d = pd.DataFrame({"月": A._ymdate(p["年月"]), "総売上": p["月間総売上"] / 1e4})
        self.assertEqual(len(d), p["年月"].nunique())
        self.assertEqual(d["月"].duplicated().sum(), 0)

    def test_fiscal_2026_has_four_finalized_months(self):
        p = self.slice_(self.fin, *self.periods(self.fin)["今年度"])
        self.assertEqual(list(p["年月"]), list(FY2026_TOTALS))     # 4か月＝4ラベル
        self.assertEqual(len(p), 4)

    def test_monthly_totals_are_untouched(self):
        got = {r["年月"]: int(r["月間総売上"])
               for _, r in self.fin.iterrows() if r["年月"] in FY2026_TOTALS}
        self.assertEqual(got, FY2026_TOTALS)

    def test_breakdown_input_is_month_times_three(self):
        p = self.slice_(self.fin, *self.periods(self.fin)["今年度"])
        d = p[["年月", "保険診療売上", "自費診療売上", "物販売上"]].copy()
        d["月"] = A._ymdate(d["年月"])
        long = d.melt(id_vars="月",
                      value_vars=["保険診療売上", "自費診療売上", "物販売上"],
                      var_name="区分", value_name="売上")
        self.assertEqual(len(long), len(p) * 3)
        self.assertEqual(len(long), 12)
        self.assertEqual(long.duplicated(subset=["月", "区分"]).sum(), 0)

    def test_breakdown_sums_to_the_monthly_total(self):
        """内訳の値そのものが変わっていないこと（合計との整合で見る）。"""
        p = self.slice_(self.fin, *self.periods(self.fin)["今年度"])
        for _, r in p.iterrows():
            with self.subTest(month=r["年月"]):
                self.assertAlmostEqual(
                    r["保険診療売上"] + r["自費診療売上"] + r["物販売上"],
                    r["月間総売上"], delta=1)

    def test_provisional_month_is_excluded_by_default_and_kept_intact(self):
        """暫定締め月は既定で期間集計に入らない。含めた場合の元値も不変。"""
        if "close_status" not in self.df.columns:
            self.skipTest("close_status 列がない")
        prov = list(self.df.loc[self.df["close_status"] == "provisional_close", "年月"])
        p_fin = self.slice_(self.fin, *self.periods(self.fin)["今年度"])
        for m in prov:
            self.assertNotIn(m, list(p_fin["年月"]))
        # 含めた場合、行が増えるだけで既存の月の値は変わらない
        p_all = self.slice_(self.df, *self.periods(self.df)["今年度"])
        base = p_fin.set_index("年月")["月間総売上"].to_dict()
        for m, v in base.items():
            self.assertEqual(p_all.set_index("年月")["月間総売上"].to_dict()[m], v)


class TestLookAndFeelUnchanged(Base):
    """色・高さ・凡例・tooltip・stack を触っていないこと。"""

    def test_tooltip_formats_are_kept(self):
        p = self.slice_(self.fin, *self.periods(self.fin)["今年度"])
        self.assertIn(("月", "%Y-%m"), tooltip_formats(A.chart_total_sales(p)))
        self.assertIn(("月", "%Y-%m"), tooltip_formats(A.chart_breakdown(p)))
        self.assertIn(("月", "%Y-%m"), tooltip_formats(A.chart_visits(p)))

    def test_total_sales_mark_and_height(self):
        p = self.slice_(self.fin, *self.periods(self.fin)["今年度"])
        spec = A.chart_total_sales(p).to_dict()
        self.assertEqual(spec["mark"]["type"], "bar")
        self.assertEqual(spec["mark"]["color"], "#0B1F3A")
        self.assertEqual(spec["height"], 260)

    def test_breakdown_keeps_stack_order_and_colors(self):
        p = self.slice_(self.fin, *self.periods(self.fin)["今年度"])
        enc = A.chart_breakdown(p).to_dict()["encoding"]
        self.assertEqual(enc["y"]["stack"], "zero")
        self.assertEqual(enc["color"]["scale"]["range"],
                         ["#0B1F3A", "#B08A4E", "#9AA3B0"])
        self.assertEqual(enc["color"]["scale"]["domain"],
                         ["保険診療売上", "自費診療売上", "物販売上"])

    def test_visits_chart_is_still_faceted_with_independent_y(self):
        p = self.slice_(self.fin, *self.periods(self.fin)["今年度"])
        spec = A.chart_visits(p).to_dict()
        self.assertIn("facet", spec)
        self.assertEqual(spec["resolve"]["scale"]["y"], "independent")
        self.assertEqual(spec["spec"]["height"], 95)

    def test_only_the_axis_line_changed_in_the_source(self):
        """差分が x 軸1か所（＋定数定義）に閉じていること。"""
        with io.open(os.path.join(HERE, "streamlit_app.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertEqual(src.count("tickCount=MONTH_TICK"), 4)
        self.assertEqual(src.count('MONTH_TICK = {"interval": "month", "step": 1}'), 1)
        # 目盛り本数での置き換えをしていない
        self.assertNotIn("tickCount=len(d)", src)
        self.assertNotIn("tickCount=len(long)", src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
