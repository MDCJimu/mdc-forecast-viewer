# -*- coding: utf-8 -*-
"""mgmt_report の判定テスト。

実行: py -m unittest test_mgmt_report -v   （cloud_deploy ディレクトリで）

確認すること
  1. 保険↑自費↓全体↓ / 保険↑自費↓全体↑ / 保険↓自費↑ / 全項目↑ / 全項目↓
  2. 木曜休診の影響候補あり / 通常営業ベースとの差なし
  3. 自費案件レンジあり / 欠損（0〜0）
  4. 「0〜0万円」のような意味のない表示が出ないこと
  5. 同じ画面に矛盾した数値・文章が出ないこと
"""
import io
import os
import unittest

import mgmt_report as MR


# ----------------------------------------------------------------------
# テスト用データ
#   実データと同じキーだけを使う。金額は自由に組み替えられる形にしておく。
# ----------------------------------------------------------------------
def make_roll(insurance, selfpay, product,
              insurance_prev, selfpay_prev, product_prev,
              outpatient=None, visit_ins=1_400_000, care=600_000,
              baseline=None, thursday_closed=True,
              hv_low=0, hv_high=0,
              days_actual=13, days_unrec=3, days_remaining=6,
              visit=1500, visit_prev=1450, shoshin=39, shoshin_prev=37,
              patients=950, patients_prev=900,
              cancel_rate=15.1, cancel_rate_prev=15.7,
              actual_to_date=None, remaining_forecast=None,
              unrecorded_total=None,
              care_revision="2026-06",
              obs_days=13, obs_total=10_912_740, obs_outp=7_727_810,
              obs_jihi=2_981_000, obs_buppin=203_930,
              obs_prev_total=11_878_440, obs_prev_rate=-8.1,
              pyd_days=15, pyd_outp=7_264_860, pyd_jihi=5_585_250, pyd_buppin=185_990,
              out_days=12, with_outpatient_days=True,
              py_biz_out_days=12, with_prev_outpatient_days=True,
              pyb_outp=6_453_630, pyb_jihi=5_244_250, pyb_buppin=180_560,
              op_visits=915, op_patients=649,
              pyb_op_visits=798, pyb_op_patients=589,
              with_outpatient_counts=True, with_prev_outpatient_counts=True):
    total = insurance + selfpay + product
    prev_total = insurance_prev + selfpay_prev + product_prev
    if outpatient is None:
        outpatient = insurance - visit_ins - care
    if baseline is None:
        baseline = total + 950_000
    if actual_to_date is None:
        actual_to_date = int(total * 0.5)
    if remaining_forecast is None:
        remaining_forecast = int(total * 0.26)
    return {
        "target_month": "2026-08",
        "as_of_date": "2026-08-22",
        "current_forecast_total": total,
        "conservative_forecast": int(total * 0.967),
        "forecast_low_80": int(total * 0.95),
        "forecast_high_80": int(total * 1.03),
        "previous_year_actual": prev_total,
        "yoy_diff": total - prev_total,
        "yoy_rate": round((total - prev_total) / prev_total * 100, 1),
        "normal_baseline_forecast": baseline,
        "gap_to_normal_baseline": total - baseline,
        "thursday_closed_target": thursday_closed,
        "insurance_forecast": insurance,
        "selfpay_forecast": selfpay,
        "product_forecast": product,
        "insurance_prevyear": insurance_prev,
        "selfpay_prevyear": selfpay_prev,
        "product_prevyear": product_prev,
        "outpatient_insurance_forecast": outpatient,
        "visit_insurance_forecast": visit_ins,
        "care_forecast": care,
        "insurance_actual_to_date": int(insurance * 0.57),
        "selfpay_actual_to_date": int(selfpay * 0.5),
        "product_actual_to_date": int(product * 0.64),
        "selfpay_remaining": selfpay - int(selfpay * 0.5),
        "high_value_selfpay_low": hv_low,
        "high_value_selfpay_high": hv_high,
        "actual_days_count": days_actual,
        "elapsed_unrecorded_days_count": days_unrec,
        "remaining_days_count": days_remaining,
        **({"outpatient_actual_days_count": out_days,
            "outpatient_elapsed_unrecorded_days_count": days_unrec,
            "outpatient_remaining_days_count": days_remaining,
            "outpatient_month_days_count": out_days + days_unrec + days_remaining}
           if with_outpatient_days else {}),
        # 純外来の分母（訪問診療を含まない確定実績）。月末見込みは存在しない。
        **({"outpatient_visit_actual_to_date": op_visits,
            "outpatient_unique_patients_actual_to_date": op_patients}
           if with_outpatient_counts else {}),
        "actual_to_date_total": actual_to_date,
        "remaining_forecast_total": remaining_forecast,
        # 実スナップショットでは
        #   確定実績 + 経過未反映 + 残り見込み = 外来3区分の月末見込み
        # が成り立つ。"auto" を渡すと、その形になる残差を入れる。
        **({"elapsed_unrecorded_total": (
            (outpatient + selfpay + product) - actual_to_date - remaining_forecast
            if unrecorded_total == "auto" else unrecorded_total)}
           if unrecorded_total is not None else {}),
        "reservation_visible_remaining_as_of": 452,
        "reservation_projected_final_remaining": 496,
        "resec_data_status": "反映済み",
        "actual_data_through": "2026-08-21",
        "care_component": {"care_revision_month": care_revision,
                           "care_data_insufficient": True},
        "progress_through_yesterday": {
            "current_cutoff": "2026-08-21", "prev_year_cutoff": "2025-08-21",
            "current": {"total": obs_total, "insurance_outpatient": obs_outp,
                        "selfpay": obs_jihi, "product": obs_buppin,
                        "clinic_days": obs_days},
            "prev_year_same_day": {"total": 13_036_100, "insurance_outpatient": pyd_outp,
                                   "selfpay": pyd_jihi, "product": pyd_buppin,
                                   "clinic_days": pyd_days},
            "prev_year_same_bizdays": {
                "total": obs_prev_total, "clinic_days": obs_days,
                "diff_vs_current": obs_total - obs_prev_total, "rate": obs_prev_rate,
                **({"outpatient_days_count": py_biz_out_days,
                    "insurance_outpatient": pyb_outp, "selfpay": pyb_jihi,
                    "product": pyb_buppin} if with_prev_outpatient_days else {}),
                **({"outpatient_visit_count": pyb_op_visits,
                    "outpatient_unique_patient_count": pyb_op_patients}
                   if with_prev_outpatient_counts else {})},
        },
        "supplementary": {
            "visit": {"available": True, "forecast": visit, "prevyear": visit_prev,
                      "actual_to_date": int(visit * 0.6)},
            "shoshin": {"available": True, "forecast": shoshin, "prevyear": shoshin_prev},
            "patient_total": {"available": True, "forecast": patients, "prevyear": patients_prev},
            "cancel": {"available": True, "current_rate": cancel_rate,
                       "prevyear_rate": cancel_rate_prev,
                       "current_reservations": 1593, "current_cancels": 240},
            "reservation_composition": {"available": True, "current_total": 1593, "types": {}},
        },
    }


def hist_rows(selfpay=None, per_day_trend=None, out_days=None,
              op_totals=None, with_outpatient_days=True):
    """直近12か月の月次実績。年月・区分・診療日数・外来診療日数を持つ最小形。

    out_days を渡すと外来診療日数だけを差し替えられる（外来診療日あたり売上の
    推移を作るのに使う）。with_outpatient_days=False は列が入る前の履歴の再現。
    """
    base = [
        # 年月, 月間総売上, 保険診療売上, 自費, 物販, 診療日数, 総来院回数, 総患者数
        ("2025-08", 21805410, 13393890, 8131750, 279770, 23, 1439, 891),
        ("2025-09", 19752670, 13693510, 5869820, 189340, 24, 1358, 860),
        ("2025-10", 18072000, 14510000, 3320000, 242000, 26, 1488, 902),
        ("2025-11", 20380000, 13930000, 6250000, 190000, 23, 1380, 886),
        ("2025-12", 19320000, 14920000, 4140000, 260000, 24, 1483, 968),
        ("2026-01", 20460000, 14070000, 6150000, 250000, 23, 1437, 933),
        ("2026-02", 20560000, 12490000, 7780000, 290000, 22, 1312, 849),
        ("2026-03", 23230000, 14580000, 8300000, 350000, 25, 1568, 972),
        ("2026-04", 22700000, 13220000, 9250000, 220000, 26, 1398, 854),
        ("2026-05", 19080000, 13420000, 5460000, 200000, 24, 1387, 879),
        ("2026-06", 20221040, 14963140, 5019300, 238600, 26, 1506, 943),
        ("2026-07", 20303270, 14481250, 5577000, 245020, 27, 1512, 920),
    ]
    rows = []
    for i, (ym, tot, hok, jih, bup, days, vis, pat) in enumerate(base):
        if selfpay is not None:
            jih = selfpay[i]
        if per_day_trend is not None:
            tot, days = per_day_trend[i]
        gairai = hok - 1_400_000 - 600_000
        if op_totals is not None:
            # 外来3区分（外来保険+自費+物販）の合計を狙った値に合わせる。
            gairai = op_totals[i] - jih - bup
            hok = gairai + 1_400_000 + 600_000
        row = {"年月": ym, "月間総売上": tot, "保険診療売上": hok,
               "自費診療売上": jih, "物販売上": bup, "診療日数": days,
               "外来保険売上": gairai,
               "訪問保険売上": 1_400_000, "介護売上": 600_000,
               # 患者価値KPIの分母。どちらも訪問診療の患者を含む総数。
               "総来院回数": vis, "総患者数": pat}
        if with_outpatient_days:
            # 既定は「訪問・介護だけの日が無い月」＝診療日数と同じ。
            row[MR.HIST_OUTPATIENT_DAYS_COL] = (out_days[i] if out_days else days)
        rows.append(row)
    return rows


PREV_ROW = {
    "年月": "2025-08", "診療日数": "23", "外来診療日数": "22",
    "月間総売上": "21805410",
    "保険診療売上": "13393890", "自費診療売上": "8131750", "物販売上": "279770",
    "外来保険売上": "11057460", "訪問保険売上": "1359740", "介護売上": "976690",
    "総患者数": "891", "総来院回数": "1439", "初診件数": "37",
}

PREV_FC = {"as_of_date": "2026-08-21", "current_forecast_total": "21878649",
           "insurance_forecast": "15132014", "selfpay_forecast": "6429462"}


def build(roll, prev_row=PREV_ROW, prev_fc=PREV_FC, hist=None, targets=None):
    return MR.build_management_report(roll, prev_row, prev_fc,
                                      hist_rows() if hist is None else hist,
                                      targets)


def make_roll_selfpay_real_drop(**kw):
    """前年同月が分布の中位＝「前年が高月だった」では説明できないケース。
    このときだけ A/B（今月計上／翌月以降）の切り分けが打ち手になる。"""
    kw.setdefault("selfpay_prev", 6_150_000)
    return make_roll(15_113_808, 3_000_000, 316_528,
                     13_393_890, kw.pop("selfpay_prev"), 279_770, **kw)


def all_text(rep):
    """画面に出る文章をすべて連結して返す（禁止語・矛盾のチェック用）。"""
    parts = list(rep["conclusion"])
    parts.append(rep["cause"]["text"])
    parts.append(rep["capacity"]["text"])
    parts.append((rep.get("outpatient_value") or {}).get("text", ""))
    parts.append(rep["focus"])
    if rep["structure"]:
        parts.append(rep["structure"]["text"])
    if rep["selfpay"]:
        parts.append(rep["selfpay"]["text"])
    parts.extend(rep["notes"])
    for a in rep["actions"]:
        parts += [a["headline"], a["target"], a["why"], a["decide"]] + list(a["check"])
    return "\n".join(parts)


def action_headlines(rep):
    return [a["headline"] for a in rep["actions"]]


# ======================================================================
class TestDriverDetection(unittest.TestCase):
    """1. どの項目が全体差を作っているかを寄与額で特定できるか。"""

    def test_insurance_up_selfpay_down_total_down(self):
        """保険↑ 自費↓ 全体↓ … 主因は自費で、保険は打ち消し側に回る。"""
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770))
        self.assertEqual(rep["cause"]["main"].key, "selfpay")
        self.assertEqual([c.key for c in rep["cause"]["offsets"]], ["insurance", "product"])
        t = rep["cause"]["text"]
        self.assertIn("自費診療", t)
        self.assertIn("+172万円", t)     # 保険は上回っていると明示される
        self.assertIn("▲212万円", t)
        # 前年8月が上位25%の高月なので「今月が落ちた」と断定しない
        self.assertIn("前年が高い月だった", t)
        self.assertIn("平常の範囲", t)
        self.assertNotIn("前年を下回る主因です", t)
        # 稼働が落ちているとは書かない（来院・患者・初診はすべて前年超のため）
        self.assertNotIn("稼働そのものが弱まって", all_text(rep))
        # 件数はすべて月末見込み。実績確定値のように書かない。
        self.assertIn("月末見込みでは", " ".join(rep["conclusion"]))
        # 前年が高月なので、自費の案件棚卸しを最優先には置かない（A-1 / A-5）
        self.assertNotIn("案件不足", action_headlines(rep)[0])

    def test_insurance_up_selfpay_down_total_up(self):
        """保険↑ 自費↓ 全体↑ … 主因は保険。自費は打ち消し側。"""
        rep = build(make_roll(16_500_000, 7_000_000, 320_000,
                              13_393_890, 8_131_750, 279_770))
        self.assertGreater(rep["facts"]["yoy"], 0)
        self.assertEqual(rep["cause"]["main"].key, "insurance")
        self.assertIn("selfpay", [c.key for c in rep["cause"]["offsets"]])
        self.assertIn("上回る見込み", rep["cause"]["text"])
        # 全体は上振れでも、自費の前年割れは打ち手として残る
        self.assertTrue(any("自費" in h for h in action_headlines(rep)))

    def test_insurance_down_selfpay_up(self):
        """保険↓ 自費↑ … 保険側の打ち手（来院数か単価かの切り分け）が出る。"""
        rep = build(make_roll(12_000_000, 9_500_000, 300_000,
                              13_393_890, 8_131_750, 279_770))
        keys = {c.key for c in rep["cause"]["drivers"] + rep["cause"]["offsets"]}
        self.assertIn("insurance", keys)
        self.assertIn("selfpay", keys)
        self.assertTrue(any("保険診療の減少" in h for h in action_headlines(rep)))
        self.assertTrue(any("自費の上振れ" in h for h in action_headlines(rep)))

    def test_all_up(self):
        """全項目↑ … 押し下げ要因が無く、下振れの言葉が出ない。"""
        rep = build(make_roll(14_500_000, 8_600_000, 300_000,
                              13_393_890, 8_131_750, 279_770))
        self.assertEqual(rep["cause"]["offsets"], [])
        self.assertEqual(rep["cause"]["main"].key, "insurance")
        self.assertIn("上回る見込み", rep["cause"]["text"])
        # 上振れの月に「前年割れ」「前年を下回る主因」の言葉を出さない
        for bad in ("前年割れ", "前年を下回る主因"):
            self.assertNotIn(bad, " ".join(rep["conclusion"]) + rep["cause"]["text"])

    def test_all_down(self):
        """全項目↓ … 打ち消し要因なし。稼働も落ちていれば、そう書く。"""
        rep = build(make_roll(12_000_000, 6_500_000, 200_000,
                              13_393_890, 8_131_750, 279_770,
                              visit=1300, visit_prev=1439,
                              patients=830, patients_prev=891,
                              shoshin=30, shoshin_prev=37))
        self.assertEqual(rep["cause"]["offsets"], [])
        self.assertEqual(rep["cause"]["main"].key, "selfpay")
        self.assertIn("稼働そのものが弱まっている可能性が高い", " ".join(rep["conclusion"]))

    def test_contributions_sum_to_total(self):
        """寄与額の合計は総売上の前年差に一致する（画面上で数字が食い違わない）。"""
        roll = make_roll(15_113_808, 6_010_211, 316_528,
                         13_393_890, 8_131_750, 279_770)
        rep = build(roll)
        s = sum(r["diff"] for r in rep["cause"]["rows"])
        self.assertAlmostEqual(s, rep["facts"]["yoy"], delta=1)
        subs = sum(c.diff for c in rep["components"]["sub"])
        ins = next(c for c in rep["components"]["main"] if c.key == "insurance")
        self.assertAlmostEqual(subs, ins.diff, delta=1)


# ======================================================================
class TestStructure(unittest.TestCase):
    """2. 構造変化（木曜休診・通常営業ベースとの差）。"""

    def test_thursday_gap_present_is_not_asserted_as_loss(self):
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770,
                              baseline=22_386_557))
        st = rep["structure"]
        self.assertIsNotNone(st)
        self.assertIn("確定した損失ではありません", st["text"])
        self.assertNotIn("失った", st["text"])
        self.assertNotIn("損失額", st["text"])
        self.assertIn("可能性がある範囲", st["text"])

    def test_absorption_needs_matched_outpatient_days(self):
        """吸収判定は、当年と前年の外来診療日数が一致したときだけ行う。"""
        # 一致（12日 vs 12日）→ 判定する
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770,
                              baseline=22_386_557))
        st = rep["structure"]
        self.assertTrue(rep["facts"]["outpatient_days_match"])
        self.assertFalse(st["absorbed"])
        self.assertIn("同じ外来診療日数（12日）まで累計して比べると", st["text"])
        self.assertIn("吸収できているとまでは言えません", st["text"])
        # 一致しない（12日 vs 11日）→ 判定しない
        ng = build(make_roll(15_113_808, 6_010_211, 316_528,
                             13_393_890, 8_131_750, 279_770,
                             baseline=22_386_557, py_biz_out_days=11))
        self.assertFalse(ng["facts"]["outpatient_days_match"])
        self.assertIn("この画面では判定していません", ng["structure"]["text"])
        self.assertNotIn("吸収できているとまでは言えません", ng["structure"]["text"])
        # 前年が上回っていれば吸収できていると判定
        ok = build(make_roll(15_113_808, 6_010_211, 316_528,
                             13_393_890, 8_131_750, 279_770,
                             baseline=22_386_557, obs_prev_total=10_000_000))
        self.assertTrue(ok["structure"]["absorbed"])
        self.assertIn("埋められている状態です", ok["structure"]["text"])

    def test_clinic_days_alone_never_authorizes_comparison(self):
        """clinic_days が同じでも、外来診療日数が違えば比較を出さない。"""
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770,
                              py_biz_out_days=11))
        f = rep["facts"]
        self.assertEqual(f["obs_days"], f["obs_prev_days"])      # clinic_days は 13 で同じ
        self.assertNotEqual(f["days_actual_outpatient"], f["obs_prev_outpatient_days"])
        self.assertFalse(f["outpatient_days_match"])
        self.assertIsNone(f["op_diff_total"])
        self.assertIsNone(f["op_per_day_prev"])
        t = rep["capacity"]["text"]
        self.assertIn("一致せず", t)
        self.assertNotIn("-8.1%", t)
        row = next(r for r in rep["capacity"]["rows"]
                   if r["name"].startswith("外来診療日あたり売上（実績"))
        self.assertEqual(row["prev"], "—")

    def test_old_snapshot_without_prev_outpatient_days(self):
        """前年側のキーが無い旧snapshotでは比較を出さない（推測しない）。"""
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770,
                              with_prev_outpatient_days=False))
        f = rep["facts"]
        self.assertIsNone(f["obs_prev_outpatient_days"])
        self.assertFalse(f["outpatient_days_match"])
        self.assertIsNone(f["op_diff_total"])
        self.assertIn("前年側の外来診療日数がスナップショットに入っていない",
                      rep["capacity"]["text"])

    def test_matched_comparison_uses_same_outpatient_days(self):
        """外来保険・自費・物販・合計の比較が同じ外来診療日数に基づくこと。"""
        roll = make_roll(15_113_808, 6_010_211, 316_528, 13_393_890, 8_131_750, 279_770)
        f = build(roll)["facts"]
        n = f["days_actual_outpatient"]
        self.assertEqual(n, f["obs_prev_outpatient_days"])
        biz = roll["progress_through_yesterday"]["prev_year_same_bizdays"]
        for key, prev_amt in (("outpatient", biz["insurance_outpatient"]),
                              ("selfpay", biz["selfpay"]), ("product", biz["product"])):
            self.assertAlmostEqual(f[f"op_prev_{key}_per_day"], prev_amt / n, places=6)
        self.assertAlmostEqual(f["op_per_day_prev"], biz["total"] / n, places=6)
        self.assertAlmostEqual(f["op_diff_total"], f["obs_total"] - biz["total"], places=6)

    def test_no_absorption_claim_when_density_is_down(self):
        rep = build(make_roll(11_500_000, 5_000_000, 200_000,
                              13_393_890, 8_131_750, 279_770,
                              baseline=18_000_000,
                              visit=1200, visit_prev=1439))
        self.assertFalse(rep["structure"]["absorbed"])
        self.assertNotIn("吸収できている可能性", rep["structure"]["text"])

    def test_no_baseline_gap(self):
        """通常営業ベースとの差が無い月は「差がある」と書かない。"""
        total = 15_113_808 + 6_010_211 + 316_528
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770,
                              baseline=total))
        st = rep["structure"]
        self.assertTrue(st["negligible"])
        self.assertIn("ほとんどありません", st["text"])
        # 差がない月に、休診の打ち手を並べない
        self.assertFalse(any("減った診療日" in h for h in action_headlines(rep)))

    def test_no_thursday_closure(self):
        total = 15_113_808 + 6_010_211 + 316_528
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770,
                              baseline=total, thursday_closed=False))
        self.assertIsNone(rep["structure"])


# ======================================================================
class TestSelfpayRange(unittest.TestCase):
    """3-4. 自費案件レンジ。0〜0 を金額として出さない。"""

    def test_range_available(self):
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770,
                              hv_low=2_501_297, hv_high=3_835_323))
        self.assertTrue(rep["selfpay"]["hv"]["available"])
        self.assertIn("250万円〜384万円", rep["selfpay"]["text"])
        self.assertNotIn("算出できていません", rep["selfpay"]["text"])

    def test_range_zero_is_reported_as_unavailable(self):
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770,
                              hv_low=0, hv_high=0))
        self.assertFalse(rep["selfpay"]["hv"]["available"])
        self.assertIn("算出できていません", rep["selfpay"]["text"])
        self.assertIn("0円という意味ではありません", rep["selfpay"]["text"])
        self.assertTrue(any("0で出力されています" in n for n in rep["notes"]))

    def test_range_missing_key(self):
        roll = make_roll(15_113_808, 6_010_211, 316_528,
                         13_393_890, 8_131_750, 279_770)
        del roll["high_value_selfpay_low"]
        del roll["high_value_selfpay_high"]
        rep = build(roll)
        self.assertFalse(rep["selfpay"]["hv"]["available"])
        self.assertIn("取得できていません", rep["selfpay"]["text"])

    def test_no_zero_to_zero_string_anywhere(self):
        """「0〜0万円」のような意味のない表示を出さない。"""
        for lo, hi in ((0, 0), (None, None), (2_501_297, 3_835_323)):
            roll = make_roll(15_113_808, 6_010_211, 316_528,
                             13_393_890, 8_131_750, 279_770,
                             hv_low=lo, hv_high=hi)
            text = all_text(build(roll))
            for bad in ("0〜0万円", "0〜0百万円", "0万円〜0万円", "取得不可〜取得不可"):
                self.assertNotIn(bad, text, f"{bad} が {lo}/{hi} で出力された")

    def test_selfpay_deepdive_has_confirmed_and_remaining(self):
        """不足額だけで終わらせず、確定済み・月内見込み・切り分け方まで出す。"""
        rep = build(make_roll_selfpay_real_drop())
        t = rep["selfpay"]["text"]
        self.assertIn("すでに計上されている自費", t)
        # 303万円が月末総額に見えないよう、合計まで書く
        self.assertIn("残りの期間に追加で計上される見込み", t)
        self.assertIn("合わせて月末", t)
        a = next(a for a in rep["actions"] if a["headline"].startswith("自費"))
        self.assertIn("時期のずれ", a["decide"])
        self.assertIn("案件そのもの", a["decide"])


# ======================================================================
class TestActionQuality(unittest.TestCase):
    """5-6. 打ち手の中身と優先順位。"""

    def test_each_action_has_four_fields(self):
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770))
        self.assertTrue(rep["actions"])
        for a in rep["actions"]:
            # 対象は短い名詞句でよい。理由と判断は説明になっている必要がある。
            self.assertTrue(a["target"] and len(a["target"]) >= 4,
                            f"対象が薄い: {a['headline']}")
            for k in ("why", "decide"):
                self.assertTrue(a[k] and len(a[k]) > 20, f"{k} が薄い: {a['headline']}")
            self.assertTrue(a["check"], f"確認する数字が無い: {a['headline']}")
            # 「確認する」で終わる抽象アクションを許さない。
            # 判断は必ず「確認した数字がこうなら、こう見る」の条件付きで書く。
            self.assertTrue(any(ch in a["decide"] for ch in ("なら", "場合", "かどうか")),
                            f"判断の分かれ目が無い: {a['headline']}")
            self.assertGreater(len(a["decide"]), 30, a["headline"])

    def test_at_most_five_and_sorted_by_priority(self):
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770))
        self.assertLessEqual(len(rep["actions"]), MR.MAX_ACTIONS)
        tiers = [a["tier"] for a in rep["actions"]]
        self.assertEqual(tiers, sorted(tiers))
        # 順位は tier → 着地への直接性 → 緊急性 → 根拠の確度 で決まる
        keys = [(a["tier"], a["directness"], a["urgency"], a["confidence"])
                for a in rep["actions"]]
        self.assertEqual(keys, sorted(keys))

    def test_amount_never_decides_order_across_kinds(self):
        """性質の違う金額どうしの大小で順位が決まっていないこと。"""
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770,
                              baseline=22_386_557))
        acts = rep["actions"]
        for i in range(len(acts) - 1):
            a, b = acts[i], acts[i + 1]
            if a["amount_kind"] == b["amount_kind"]:
                continue
            # 種別が違う組では、金額が小さい側が上に来ることを許す。
            # つまり金額の大小は順位を決めていない。
            axes_a = (a["tier"], a["directness"], a["urgency"], a["confidence"])
            axes_b = (b["tier"], b["directness"], b["urgency"], b["confidence"])
            self.assertLessEqual(axes_a, axes_b,
                                 f"{a['headline']} / {b['headline']}")
        # 金額の大きい自費（関連差額212万）が先頭に来ないこと
        names = action_headlines(rep)
        self.assertNotIn("水準で確認", names[0])

    def test_every_amount_declares_what_it_means(self):
        """並べ替えに使う金額は、何を表すのかを必ず持つ（根拠のない影響額を出さない）。"""
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770,
                              baseline=22_386_557))
        for a in rep["actions"] + rep["next_month_actions"]:
            self.assertIn(a["amount_kind"], MR.AMOUNT_KINDS, a["headline"])
            if a["amount_kind"] == "金額換算なし":
                self.assertEqual(a["amount"], 0.0, a["headline"])
            else:
                self.assertGreater(a["amount"], 0.0, a["headline"])

    def test_biggest_contributor_comes_first(self):
        """分布で説明できない落ち込みなら、その区分が最優先に立つ。"""
        rep = build(make_roll_selfpay_real_drop())
        self.assertEqual(rep["actions"][0]["tier"], MR.T_DRIVER)
        self.assertIn("自費", rep["actions"][0]["headline"])

    def test_top_action_is_the_most_direct_and_grounded(self):
        """着地に直接効き、根拠が実測のものが先頭に来る。"""
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770))
        top = rep["actions"][0]
        self.assertEqual(top["directness"], 1)
        self.assertEqual(top["urgency"], 1)
        self.assertTrue(all(a["inmonth"] for a in rep["actions"]))
        # 自費は水準監視として残るが、金額が大きくても最優先ではない
        self.assertTrue(any("水準で確認" in h for h in action_headlines(rep)))
        sp = next(a for a in rep["actions"] if "水準で確認" in a["headline"])
        self.assertGreater(sp["amount"], top["amount"])   # 金額は上、順位は下

    def test_no_banned_phrases(self):
        """禁止表現を出さない。"""
        banned = ["再充填", "高単価型", "別建て反映", "足元は弱め",
                  "実績日数基準", "案件別進捗を確認", "パラダイム", "シナジー",
                  "ソリューション", "最適化"]
        cases = [
            make_roll(15_113_808, 6_010_211, 316_528, 13_393_890, 8_131_750, 279_770),
            make_roll(12_000_000, 9_500_000, 300_000, 13_393_890, 8_131_750, 279_770),
            make_roll(14_500_000, 8_600_000, 300_000, 13_393_890, 8_131_750, 279_770),
            make_roll(12_000_000, 6_500_000, 200_000, 13_393_890, 8_131_750, 279_770,
                      visit=1200, visit_prev=1439),
        ]
        for roll in cases:
            text = all_text(build(roll))
            for b in banned:
                self.assertNotIn(b, text, f"禁止表現「{b}」が出力された")

    def test_cancel_action_only_when_rate_worsens(self):
        good = build(make_roll(15_113_808, 6_010_211, 316_528,
                               13_393_890, 8_131_750, 279_770,
                               cancel_rate=15.1, cancel_rate_prev=15.7))
        self.assertFalse(any("キャンセル率の上昇" in h for h in action_headlines(good)))
        flat_total = 13_393_890 + 8_131_750 + 279_770
        bad = build(make_roll(13_393_890, 8_131_750, 279_770,
                              13_393_890, 8_131_750, 279_770,
                              visit_ins=1_359_740, care=976_690,
                              baseline=flat_total,
                              cancel_rate=19.0, cancel_rate_prev=15.7))
        self.assertTrue(any("キャンセル率の上昇" in h for h in action_headlines(bad)),
                        action_headlines(bad))

    def test_structural_items_are_moved_out_of_this_month(self):
        """今月動かせないテーマが ACTION 1〜5 の枠を占めない（A-5）。"""
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770,
                              baseline=22_386_557))
        self.assertLessEqual(len(rep["actions"]), MR.MAX_ACTIONS)
        self.assertTrue(all(a["inmonth"] for a in rep["actions"]))
        # 木曜休診・介護は来月以降の枠にある
        later = [a["headline"] for a in rep["next_month_actions"]]
        self.assertTrue(any("木曜休診" in h for h in later), later)
        self.assertTrue(any("介護" in h for h in later), later)
        self.assertFalse(any("木曜休診" in h for h in action_headlines(rep)))
        self.assertFalse(any("介護" in h for h in action_headlines(rep)))
        for a in rep["next_month_actions"]:
            self.assertFalse(a["inmonth"])


# ======================================================================
class TestConsistency(unittest.TestCase):
    """矛盾した数値・文章が同じ画面に出ないこと。"""

    def test_direction_words_match_the_numbers(self):
        for ins, sp in ((15_113_808, 6_010_211), (16_500_000, 7_000_000),
                        (12_000_000, 9_500_000), (14_500_000, 8_600_000)):
            rep = build(make_roll(ins, sp, 316_528, 13_393_890, 8_131_750, 279_770))
            yoy = rep["facts"]["yoy"]
            text = " ".join(rep["conclusion"]) + rep["cause"]["text"]
            if yoy < 0:
                self.assertIn("下回る", text)
                self.assertNotIn("上回る見込みです。一方", text)
            else:
                self.assertIn("上回る", text)

    def test_days_are_derived_not_hardcoded(self):
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770,
                              days_actual=10, days_unrec=2, days_remaining=9))
        self.assertEqual(rep["facts"]["days_month"], 21)
        self.assertIn("これから診療する9日", rep["capacity"]["text"])

    def test_no_target_comparison_when_target_missing(self):
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770))
        self.assertIsNone(rep["facts"]["target_sales"])
        self.assertIn("目標", rep["selfpay"]["text"])
        self.assertIn("登録されていない", rep["selfpay"]["text"])

    def test_missing_prev_year_row_degrades_gracefully(self):
        """前年の月次実績が無くても落ちず、無い比較を作らない。"""
        rep = MR.build_management_report(
            make_roll(15_113_808, 6_010_211, 316_528,
                      13_393_890, 8_131_750, 279_770), None, None)
        self.assertTrue(rep["conclusion"])
        self.assertIsNone(rep["facts"]["days_prev"])
        self.assertIn("今月の外来診療日数は", rep["capacity"]["text"])
        self.assertTrue(any("前年同月の月次実績が読めない" in n for n in rep["notes"]))

    def test_empty_roll_does_not_crash(self):
        rep = MR.build_management_report({}, None, None)
        self.assertTrue(rep["conclusion"])
        self.assertEqual(rep["actions"], [])

    def test_conservative_gap_is_forecast_minus_conservative(self):
        """保守ラインとの差は、必ず 着地見込み − 保守ライン と一致すること。"""
        roll = make_roll(15_113_808, 6_010_211, 316_528,
                         13_393_890, 8_131_750, 279_770)
        rep = build(roll)
        want = roll["current_forecast_total"] - roll["conservative_forecast"]
        self.assertEqual(rep["facts"]["conservative_gap"], want)
        want_txt = MR.yen_man(want)
        for a in rep["actions"]:
            if "保守ライン" in a["decide"] and "着地見込みとの差" in a["decide"]:
                self.assertIn(want_txt, a["decide"], a["headline"])
        # 必要ペース差はこれとは別物なので、同じ額にはならない
        self.assertNotEqual(round(rep["facts"]["pace_gap_yen"]), round(want))

    def test_no_two_different_amounts_for_the_landing_gap(self):
        """『保守ラインに近づく』と書いた文の中に、着地差以外の金額を混ぜない。"""
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770))
        gap_txt = MR.yen_man(rep["facts"]["conservative_gap"])
        pace_txt = MR.yen_man(rep["facts"]["pace_gap_yen"])
        for a in rep["actions"]:
            d = a["decide"]
            if "保守ライン" not in d or pace_txt not in d:
                continue
            # 両方出す場合は、どちらが何かが読めるようになっていること
            self.assertIn("着地見込みとの差", d)
            self.assertIn(gap_txt, d)
            self.assertIn("必要ペース", d)

    def test_yoy_offset_sentence_adds_up(self):
        """マイナス − 吸収 ＝ 全体差 が、万円に丸めても合うこと。"""
        for ins, sp, pr in ((15_113_808, 6_010_211, 316_528),
                            (16_500_000, 7_000_000, 320_000),
                            (12_000_000, 9_500_000, 300_000)):
            rep = build(make_roll(ins, sp, pr, 13_393_890, 8_131_750, 279_770))
            t = rep["cause"]["text"]
            if "結果として" not in t and "差し引きで" not in t:
                continue
            main = rep["components"]["main"]
            head = rep["cause"]["main"]
            drv = sum(c.diff for c in main if c.diff * head.diff > 0)
            off = sum(c.diff for c in main if c.diff * head.diff < 0)
            tot = rep["facts"]["yoy"]
            r = lambda v: round(abs(v) / 10000)
            if "結果として" in t:
                self.assertEqual(r(drv) - r(off), r(tot))
            self.assertIn(MR.yen_man(abs(drv)), t)
            self.assertIn(MR.yen_man(abs(off)), t)
            self.assertIn(MR.yen_man(abs(tot)), t)

    def test_selfpay_action_does_not_excuse_this_month(self):
        """「来月積み上がるから今月の着地はそのままでよい」と読める文を出さない。"""
        rep = build(make_roll_selfpay_real_drop())
        a = next(a for a in rep["actions"] if a["headline"].startswith("自費"))
        d = a["decide"]
        self.assertIn("下方に見直します", d)
        self.assertIn("今月の着地は下がります", d)
        self.assertIn("翌月の先行売上", d)
        for bad in ("着地を見ればよく", "そのままでよい", "着地は変えなくてよい"):
            self.assertNotIn(bad, d)
        # A / B の判断分岐が両方書かれていること
        self.assertIn("届くなら", d)
        self.assertIn("届かないなら", d)

    def test_forecast_values_are_not_stated_as_facts(self):
        """予測から出した数字を、実績確定値のように断定しないこと。"""
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770))
        cap = rep["capacity"]["text"]
        # 来院・患者・初診・1日あたり・1来院あたりを含む文には「見込み」系の語が要る
        import re
        for sent in [x for x in re.split("。", cap) if x.strip()]:
            if ("実績で見ると" in sent or "実績" in sent[:6]
                    or "区分別の1日あたり" in sent or "内訳は、売上が確定している" in sent
                    or "今月の診療日数は" in sent
                    or "今月の外来診療日数は" in sent
                    or "外来診療を行った" in sent
                    or "前年と比べられるのは" in sent
                    or "外来診療を行った日だけ" in sent
                    or "1日あたりの売上は、その日も分母" in sent
                    or "前年の日数は" in sent
                    or "なお月次実績が持つ前年の日数は" in sent
                    or "月の診療日数そのものの前年差は出していません" in sent
                    or "前年の同時期との比較" in sent
                    or "前年側の日数は" in sent
                    or "前年も同じ外来診療日数" in sent
                    or "ここまでの日数はすべて外来診療日数" in sent
                    or "月次実績にはもう一つ" in sent
                    or "外来診療日数そのものは" in sent
                    or "区分別の1日あたりは" in sent
                    or "前年を同じ診療日数まで累計した" in sent):
                continue          # 実測を述べた文はそのまま断定してよい
            if any(k in sent for k in ("来院回数", "1診療日あたり", "1来院あたり", "診療日数")):
                self.assertTrue(any(k in sent for k in ("見込み", "計算です", "実績のある日数")),
                                f"予測値が断定形: {sent}")
        # 結論でも件数は見込みと分かる形
        concl = " ".join(rep["conclusion"])
        if "来院回数" in concl:
            self.assertIn("月末見込みでは", concl)
        # 稼働表：今月側が見込みか実績か、前年側が何との比較かを行ごとに持っている
        for r in rep["capacity"]["rows"]:
            k = r.get("kind") or ""
            if r["prev"] == "—":
                self.assertEqual(r["diff"], "—", r["name"])
                continue
            self.assertTrue(k.startswith("実績") or k.startswith("月末見込み"), r["name"])
            self.assertIn("前年", k, r["name"])
        kinds = {r["name"]: r["kind"] for r in rep["capacity"]["rows"]}
        self.assertTrue(kinds.get("キャンセル率", "").startswith("実績"))
        self.assertTrue(kinds.get("総来院回数", "").startswith("月末見込み"))

    def test_percent_sign_matches_amount_sign(self):
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770))
        for r in rep["cause"]["rows"]:
            if r["diff"] < 0:
                self.assertLess(r["rate"], 0, r["name"])
            elif r["diff"] > 0:
                self.assertGreater(r["rate"], 0, r["name"])


# ======================================================================
class TestDistributionAxis(unittest.TestCase):
    """A-1 / A-4: 直近12か月の分布を比較軸に使えているか。"""

    def test_prev_year_high_month_is_not_called_this_month_slump(self):
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770))
        t = rep["cause"]["text"]
        self.assertIn("中央値", t)
        self.assertIn("前年が高い月だった", t)
        self.assertEqual(rep["facts"]["level_prev"]["selfpay"], "上位25%")
        self.assertEqual(rep["facts"]["level_now"]["selfpay"], "中位")

    def test_prev_year_low_month_is_not_called_this_month_boom(self):
        """逆向き。前年が下位なら「今月が伸びた」と断定しない。"""
        rep = build(make_roll(15_113_808, 8_000_000, 316_528,
                              13_393_890, 3_320_000, 279_770))
        self.assertIn("前年が低い月だった", rep["cause"]["text"])

    def test_no_outlier_note_when_prev_year_is_mid(self):
        """前年が中位なら余計な但し書きを足さない。"""
        rep = build(make_roll(15_113_808, 3_000_000, 316_528,
                              13_393_890, 6_150_000, 279_770))
        self.assertNotIn("前年が高い月だった", rep["cause"]["text"])
        self.assertNotIn("前年が低い月だった", rep["cause"]["text"])

    def test_record_level_is_surfaced(self):
        """直近12か月で最高／最低の水準は結論で拾う（A-4）。"""
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770))
        concl = " ".join(rep["conclusion"])
        self.assertEqual(rep["facts"]["level_now"]["insurance"], "最高")
        self.assertIn("最高水準", concl)
        self.assertIn("保険診療", concl)

    def test_no_distribution_when_history_missing(self):
        """履歴が無ければ分布の話はしない（推測で作らない）。"""
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770), hist=[])
        self.assertFalse(rep["facts"]["hist"]["available"])
        self.assertNotIn("中央値", rep["cause"]["text"])
        self.assertNotIn("最高水準", " ".join(rep["conclusion"]))


# ======================================================================
class TestObservedFirst(unittest.TestCase):
    """A-2 / A-3: 実測と月末見込みが混ざっていないか。"""

    def test_capacity_leads_with_observed(self):
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770))
        t = rep["capacity"]["text"]
        self.assertTrue(t.startswith("外来診療を行った"), t[:30])
        self.assertIn("-8.1%", t)
        self.assertIn("月末見込みでは外来診療", t)
        self.assertIn("前年も同じ外来診療日数（12日）まで累計すると", t)

    def test_observed_rows_are_labelled(self):
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770))
        kinds = {r["name"]: r["kind"] for r in rep["capacity"]["rows"]}
        # 外来系はすべて外来診療日ベース。前年比較を持たない。
        # 外来系はすべて外来診療日ベース
        for n in ("外来診療日あたり売上（実績・外来保険＋自費＋物販）",
                  "うち自費（実績・外来診療日あたり）",
                  "外来診療日あたり売上（月末見込み・外来保険＋自費＋物販）"):
            self.assertIn("外来診療", kinds[n], n)
        # 日数が一致した実績行は前年と比較する
        self.assertIn("同じ外来診療日数",
                      kinds["外来診療日あたり売上（実績・外来保険＋自費＋物販）"])
        # 月末見込みも、前年側の外来診療日数がそろったので比較する。
        # 当年が見込み・前年が確定実績であることは kind に書いてある。
        k = kinds["外来診療日あたり売上（月末見込み・外来保険＋自費＋物販）"]
        self.assertIn("月末見込み", k)
        self.assertIn("前年は確定実績", k)
        self.assertNotIn("比較しない", k)

    def test_structure_never_calls_forecast_observed(self):
        """予測値を「実際には」と書かない（A-3）。"""
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770,
                              baseline=22_386_557))
        t = rep["structure"]["text"]
        self.assertNotIn("実際には", t)
        # 混合分母の1日あたり比較を根拠にしない
        self.assertNotIn("前年48万円", t)
        # 判定根拠は「同じ外来診療日数まで累計した比較」だけ
        self.assertIn("同じ外来診療日数", t)


# ======================================================================
class TestProductivityTrend(unittest.TestCase):
    """A-6: 外来診療日あたり売上の推移。分子は外来3区分、分母は外来診療日数。

    以前は「売上発生日あたり総売上」で判定しており、木曜休診で訪問・介護だけ
    売上が立つ日が分母に入ったせいで「6か月連続低下」と出ていた。月次実績に
    「外来診療日数」の列が入ったので、全期間を同じ分母で並べて判定する。
    """

    # 2025-08〜2026-07 の実データ（外来3区分の合計, 外来診療日数）。
    # 外来診療日あたりは 88.5 / 74.1 / 60.0 / 77.0 / 69.9 / 78.8 /
    #                    83.9 / 84.2 / 81.8 / 73.0 / 69.7 / 86.2 万円。
    REAL_OP = [19468980, 17052060, 15610779, 17706461, 16781039, 18132176,
               18458460, 21046870, 20444300, 16782690, 18122820, 18109870]
    REAL_DAYS = [22, 23, 26, 23, 24, 23, 22, 25, 25, 23, 26, 21]

    def _real(self, **kw):
        return build(make_roll(15_113_808, 6_010_211, 316_528,
                               13_393_890, 8_131_750, 279_770, **kw),
                     hist=hist_rows(op_totals=self.REAL_OP,
                                    out_days=self.REAL_DAYS))

    def test_real_series_is_decline_then_rebound(self):
        """3月から6月まで低下し、7月に反発、という形で出ること。"""
        tr = self._real(thursday_closed=True)["trend"]
        self.assertIsNotNone(tr)
        self.assertFalse(tr.get("suppressed"))
        self.assertEqual(tr["kind"], "turn")
        self.assertEqual(tr["months"], 3)          # 03→04, 04→05, 05→06
        self.assertEqual(tr["direction"], -1)
        self.assertIn("03月", tr["text"])
        self.assertIn("06月", tr["text"])
        self.assertIn("反発", tr["text"])
        self.assertIn("84.2万円", tr["text"])
        self.assertIn("69.7万円", tr["text"])
        self.assertIn("86.2万円", tr["text"])

    def test_real_series_never_says_six_months_of_decline(self):
        """撤回済みの『6か月連続低下』が新しい系列から出ないこと。"""
        rep = self._real(thursday_closed=True)
        for t in (rep["trend"]["text"], all_text(rep)):
            for n in range(4, 13):
                self.assertNotIn(f"{n}か月続けて低下", t)
                self.assertNotIn(f"{n}か月続けて前月を下回り", t)

    def test_rebound_is_not_reported_as_plain_improvement(self):
        """『改善した』とだけ言わず、低下局面と水準まで出すこと。"""
        tr = self._real(thursday_closed=True)["trend"]
        self.assertIn("直前3か月平均", tr["text"])
        self.assertIn("直前6か月平均", tr["text"])
        self.assertIn("直近12か月の分布では", tr["text"])
        self.assertIn("外来診療日数は", tr["text"])
        self.assertIsNotNone(tr["prev3"])
        self.assertIsNotNone(tr["prev6"])
        self.assertEqual(tr["level"], "上位25%")

    def test_thursday_closure_no_longer_suppresses(self):
        """分母がそろったので、木曜休診中でも判定を出す。"""
        tr = self._real(thursday_closed=True)["trend"]
        self.assertFalse(tr.get("suppressed"))
        self.assertEqual(tr["basis"], MR.BASIS_OUTPATIENT)

    def test_denominator_is_outpatient_days_not_clinic_days(self):
        """診療日数ではなく外来診療日数で割っていること。"""
        rep = self._real(thursday_closed=True)
        series = rep["facts"]["hist"]["op_per_day"]
        self.assertEqual([x["days"] for x in series], self.REAL_DAYS)
        for x, op, d in zip(series, self.REAL_OP, self.REAL_DAYS):
            self.assertAlmostEqual(x["per_day"], op / d, places=6)
            self.assertEqual(x["basis"], MR.BASIS_OUTPATIENT)

    def test_continuous_decline_is_still_reported(self):
        """一方向に下がり続ける月は、これまでどおり連続低下として出す。"""
        op = [20_000_000 - i * 300_000 for i in range(12)]
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770),
                    hist=hist_rows(op_totals=op, out_days=[23] * 12))
        tr = rep["trend"]
        self.assertEqual(tr["kind"], "run")
        self.assertEqual(tr["direction"], -1)
        self.assertIn(f"{tr['months']}か月続けて低下", tr["text"])
        self.assertTrue(any("外来診療日あたり売上" in a["headline"]
                            for a in rep["next_month_actions"]))

    def test_suppressed_when_column_is_missing(self):
        """外来診療日数が入っていない履歴では、判定せず理由を返す。"""
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770),
                    hist=hist_rows(with_outpatient_days=False))
        tr = rep["trend"]
        self.assertTrue(tr["suppressed"])
        self.assertIn("判定を出していません", tr["text"])
        self.assertIn("外来診療日数が入っていない月", tr["text"])
        self.assertFalse(any("外来診療日あたり売上" in a["headline"]
                             for a in rep["next_month_actions"]))

    def test_flat_series_makes_no_trend_claim(self):
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770),
                    hist=hist_rows(op_totals=[18_000_000] * 12,
                                   out_days=[23] * 12))
        tr = rep["trend"]
        self.assertEqual(tr["kind"], "level")
        self.assertIn("一方向に続けて動いてはいません", tr["text"])
        self.assertFalse(any("外来診療日あたり売上" in a["headline"]
                             for a in rep["next_month_actions"]))

    def test_no_trend_without_history(self):
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770), hist=[])
        self.assertIsNone(rep["trend"])


# ======================================================================
class TestPerDayDefinitions(unittest.TestCase):
    """「1日あたり」の2定義が混ざらないこと。"""

    ROLL = dict(insurance=15_113_808, selfpay=6_010_211, product=316_528,
                insurance_prev=13_393_890, selfpay_prev=8_131_750, product_prev=279_770)

    def _rep(self, **kw):
        return build(make_roll(self.ROLL["insurance"], self.ROLL["selfpay"],
                               self.ROLL["product"], self.ROLL["insurance_prev"],
                               self.ROLL["selfpay_prev"], self.ROLL["product_prev"], **kw))

    def test_outpatient_per_day_excludes_visit_and_care(self):
        """外来診療日あたり売上の分子に訪問・介護を入れない。"""
        roll = make_roll(15_113_808, 6_010_211, 316_528,
                         13_393_890, 8_131_750, 279_770,
                         visit_ins=1_466_828, care=584_800)
        rep = build(roll)
        f = rep["facts"]
        want = (roll["outpatient_insurance_forecast"] + roll["selfpay_forecast"]
                + roll["product_forecast"])
        self.assertEqual(f["op_now"], want)
        self.assertNotIn(roll["visit_insurance_forecast"], (f["op_now"],))
        self.assertAlmostEqual(f["per_day_now"], want / f["days_month_outpatient"], places=6)
        # 訪問＋介護を足した額では割っていない
        allrev = want + roll["visit_insurance_forecast"] + roll["care_forecast"]
        self.assertNotAlmostEqual(f["per_day_now"], allrev / f["days_month_outpatient"], places=0)
        self.assertEqual(f["per_day_basis_now"], MR.BASIS_OUTPATIENT)
        # 混合分母では割っていない
        self.assertNotAlmostEqual(f["per_day_now"], want / f["days_month"], places=0)

    def test_total_revenue_is_never_divided_by_outpatient_days(self):
        """全売上 ÷ 外来診療日数 という混ざった値を作らない。"""
        roll = make_roll(15_113_808, 6_010_211, 316_528,
                         13_393_890, 8_131_750, 279_770)
        rep = build(roll)
        f = rep["facts"]
        bad = f["total"] / f["days_month_outpatient"]   # 全売上 ÷ 外来診療日数
        for k, v in f.items():
            if not k.endswith("per_day") and "per_day" not in k:
                continue
            if not isinstance(v, (int, float)):
                continue
            self.assertNotAlmostEqual(v, bad, places=0, msg=k)
        # 画面文にもその金額を出さない
        self.assertNotIn(MR.yen_man(bad), all_text(rep))

    def test_revenue_day_basis_includes_visit_only_days(self):
        """売上発生日あたり総売上は、分子も分母も全区分の基準。"""
        rep = self._rep()
        f = rep["facts"]
        prow = PREV_ROW
        want = float(prow["月間総売上"]) / float(prow["診療日数"])
        self.assertAlmostEqual(f["rev_day_per_day_prev"], want, places=6)
        # 前年側の外来系per-dayは外来診療日数を分母にする（診療日数は使わない）。
        self.assertEqual(f["per_day_basis_prev"], MR.BASIS_OUTPATIENT)
        self.assertEqual(MR.HIST_DAYS_BASIS, MR.BASIS_REVENUE_DAY)
        self.assertEqual(MR.HIST_OP_DAYS_BASIS, MR.BASIS_OUTPATIENT)

    def test_basis_gap_is_stated_when_thursday_is_closed(self):
        """分母の数え方が違うことを黙って比べない。"""
        rep = self._rep(thursday_closed=True)
        self.assertTrue(rep["facts"]["per_day_basis_gap"])
        t = rep["capacity"]["text"]
        self.assertIn("売上が発生した日", t)
        self.assertIn("月の診療日数そのものの前年差は出していません", t)
        # 外来系の日数は外来診療日数で語る（診療日数を分母にしない）。
        self.assertIn("ここまでの日数はすべて外来診療日数", t)

    def test_no_basis_note_when_thursday_is_open(self):
        rep = self._rep(thursday_closed=False)
        self.assertFalse(rep["facts"]["per_day_basis_gap"])
        self.assertNotIn("月次実績が持つ前年の日数は", rep["capacity"]["text"])

    def test_no_year_over_year_day_count_difference(self):
        """数え方が違う日数どうしを引き算して表示しない。"""
        rep = self._rep(thursday_closed=True)
        self.assertIsNone(rep["facts"]["days_diff"])
        txt = all_text(rep) + rep["capacity"]["text"]
        for bad in ("前年同月23日に対し", "診療日数そのものは前年より",
                    "前年と同じです。内訳は"):
            self.assertNotIn(bad, txt)
        # 表の日数行にも前年・差を入れない
        self.assertIn("今月の外来診療日数は21日です", rep["capacity"]["text"])

    def test_old_snapshot_shows_not_computable(self):
        """外来診療日数が無い古いスナップショットでは、誤った値を出さず算出不可とする。"""
        rep = self._rep(thursday_closed=True, with_outpatient_days=False)
        f = rep["facts"]
        self.assertFalse(f["has_outpatient_days"])
        # 混合分母の per-day を作らない
        for k in ("per_day_now", "ins_per_day_now", "op_per_day_actual",
                  "op_per_day_month", "obs_per_day", "per_day_done"):
            self.assertIsNone(f[k], k)
        t = rep["capacity"]["text"]
        self.assertIn("外来診療日あたり売上は算出できません", t)
        row = next(r for r in rep["capacity"]["rows"] if r["name"] == "外来診療日あたり売上")
        self.assertEqual(row["now"], "算出不可")

    def test_outpatient_days_replace_the_caveat(self):
        """外来診療日数が取れている月は、暫定の注意書きを出さない。"""
        rep = self._rep(thursday_closed=True)
        self.assertTrue(rep["facts"]["has_outpatient_days"])
        t = rep["capacity"]["text"]
        self.assertNotIn("控えめな値", t)
        self.assertIn("今月の外来診療日数は21日です", t)

    def test_outpatient_per_day_uses_outpatient_days(self):
        """外来診療日あたり売上の分母が外来診療日数であること。"""
        # 2026年8月の実データに合わせる（訪問・介護の実額）
        rep = self._rep(thursday_closed=True, visit_ins=1_466_828, care=584_800)
        f = rep["facts"]
        self.assertEqual(f["days_actual_outpatient"], 12)
        self.assertEqual(f["days_month_outpatient"], 21)
        self.assertAlmostEqual(f["op_per_day_actual"], f["obs_total"] / 12, places=6)
        self.assertAlmostEqual(f["op_per_day_month"], f["op_now"] / 21, places=6)
        # 2026年8月の実データでおよそ91万円 / 92万円
        self.assertAlmostEqual(f["op_per_day_actual"] / 10000, 91, delta=0.6)
        self.assertAlmostEqual(f["op_per_day_month"] / 10000, 92, delta=0.6)
        t = rep["capacity"]["text"]
        self.assertIn("外来診療を行った12日で見ると、1日あたり91万円です", t)
        self.assertIn("外来診療21日で1日あたり92万円", t)
        # 旧混合分母（外来3区分 ÷ 売上のあった日を含む日数）で作った値を、
        # 今月の外来生産性として出さない。当年側の per-day は必ず外来診療日数割り。
        for k in ("per_day_now", "op_per_day_month"):
            self.assertAlmostEqual(f[k], f["op_now"] / 21, places=6)
        self.assertAlmostEqual(f["per_day_done"], f["actual_to_date"] / 12, places=6)
        self.assertNotIn("外来診療21日で1日あたり84万円", t)
        self.assertNotIn("外来診療21日で1日あたり88万円", t)
        # 日数が一致しているので前年比較を出す（同じ外来診療日数どうし）
        row = next(r for r in rep["capacity"]["rows"]
                   if r["name"].startswith("外来診療日あたり売上（実績"))
        self.assertIn("同じ外来診療日数", row["kind"])
        self.assertNotEqual(row["prev"], "—")
        # 月末見込みの前年側は、月次実績の外来診療日数から作る（診療日数は使わない）
        m = next(r for r in rep["capacity"]["rows"]
                 if r["name"].startswith("外来診療日あたり売上（月末見込み"))
        self.assertNotEqual(m["prev"], "—")
        pv = float(PREV_ROW["外来保険売上"]) + float(PREV_ROW["自費診療売上"]) \
            + float(PREV_ROW["物販売上"])
        want = pv / float(PREV_ROW["外来診療日数"])
        self.assertAlmostEqual(f["per_day_prev"], want, places=6)
        # 診療日数（23日）で割った値にはなっていない
        self.assertNotAlmostEqual(f["per_day_prev"],
                                  pv / float(PREV_ROW["診療日数"]), places=0)

    def test_visit_care_never_enters_outpatient_numerator(self):
        """訪問介護売上を外来診療日あたり売上の分子に入れない。"""
        roll = make_roll(15_113_808, 6_010_211, 316_528, 13_393_890, 8_131_750, 279_770,
                         visit_ins=1_466_828, care=584_800)
        f = build(roll)["facts"]
        vc = roll["visit_insurance_forecast"] + roll["care_forecast"]
        self.assertAlmostEqual(f["op_per_day_month"], f["op_now"] / 21, places=6)
        self.assertNotAlmostEqual(f["op_per_day_month"], (f["op_now"] + vc) / 21, places=0)

    def test_indicator_names_are_distinct(self):
        """2つの指標を同じ名前で並べない。"""
        rep = self._rep()
        names = [r["name"] for r in rep["capacity"]["rows"]]
        self.assertEqual(len(names), len(set(names)))
        for n in names:
            self.assertNotEqual(n, "1診療日あたり売上")
        self.assertIn("外来診療日あたり売上（月末見込み・外来保険＋自費＋物販）", names)
        # 分母を言わない曖昧な「1日あたり売上」を残さない
        self.assertNotIn("1日あたり売上（外来保険＋自費＋物販）", names)
        # 分母が外来診療日数だと言い切る名前を使わない
        # 外来診療日数が取れている月だけ「外来診療日あたり」を名乗ってよい
        self.assertTrue(rep["facts"]["has_outpatient_days"])
        self.assertTrue(any(n.startswith("外来診療日あたり売上") for n in names))

    def test_august_report_has_no_six_month_decline(self):
        """本番に出ていた「6か月続けて低下」が現在の2026年8月レポートに出ない。"""
        rep = self._rep(thursday_closed=True)
        text = all_text(rep) + (rep["trend"] or {}).get("text", "")
        for bad in ("6か月続けて低下", "6か月続けて上昇", "か月続けて低下しています（02月"):
            self.assertNotIn(bad, text)


# ======================================================================
class TestPublishedOutpatientDays(unittest.TestCase):
    """公開している monthly_actuals.csv の外来診療日数を固定する。

    外来保険+自費+物販 のいずれかが計上された日数。2019-11〜2026-07 の全81か月で
    検証済みで、診療日数との差が出る17か月・のべ23日はすべて説明がついている
    （訪問介護のみ7日 ＋ 売上ゼロ16日）。既存の診療日数は意味も値も変えない。
    """

    COL = "外来診療日数"

    @classmethod
    def setUpClass(cls):
        import csv
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", "history", "monthly_actuals.csv")
        if not os.path.isfile(path):
            raise unittest.SkipTest("monthly_actuals.csv が無い")
        with io.open(path, encoding="utf-8-sig", newline="") as fh:
            cls.rows = [r for r in csv.DictReader(fh) if r.get("年月")]
        cls.by = {r["年月"]: r for r in cls.rows}

    def test_column_exists_for_every_month(self):
        self.assertEqual(len(self.rows), 81)
        missing = [r["年月"] for r in self.rows if not str(r.get(self.COL, "")).strip()]
        self.assertEqual(missing, [], f"外来診療日数が空の月: {missing}")

    def test_no_zero_or_negative_month(self):
        bad = [(r["年月"], r[self.COL]) for r in self.rows
               if float(r[self.COL]) <= 0]
        self.assertEqual(bad, [], f"0以下の月: {bad}")

    def test_never_exceeds_clinic_days(self):
        """外来診療日は診療日の部分集合。上回る月があれば数え方が壊れている。"""
        bad = [(r["年月"], r["診療日数"], r[self.COL]) for r in self.rows
               if float(r[self.COL]) > float(r["診療日数"])]
        self.assertEqual(bad, [])

    def test_2026_07_is_fixed(self):
        r = self.by["2026-07"]
        self.assertEqual(int(float(r["診療日数"])), 27)     # 既存列は変えない
        self.assertEqual(int(float(r[self.COL])), 21)       # 外来診療 21日
        # 内訳: 外来診療21 + 訪問介護のみ4 + 売上ゼロ2 = 27
        self.assertEqual(21 + 4 + 2, int(float(r["診療日数"])))

    def test_months_that_differ_from_clinic_days(self):
        """差が出る月と差の大きさを固定する（調査で1日ずつ突合済み）。"""
        want = {"2019-11": 1, "2019-12": 1, "2020-05": 1, "2020-06": 1,
                "2020-08": 1, "2020-11": 1, "2021-08": 2, "2022-03": 1,
                "2023-10": 1, "2024-05": 1, "2024-06": 1, "2024-08": 1,
                "2025-08": 1, "2025-09": 1, "2026-04": 1, "2026-05": 1,
                "2026-07": 6}
        got = {r["年月"]: int(float(r["診療日数"])) - int(float(r[self.COL]))
               for r in self.rows
               if int(float(r["診療日数"])) != int(float(r[self.COL]))}
        self.assertEqual(got, want)

    def test_recent_outpatient_per_day_series(self):
        """2026-02〜07 の外来診療日あたり売上（万円・小数1桁）を固定する。"""
        want = {"2026-02": 83.9, "2026-03": 84.2, "2026-04": 81.8,
                "2026-05": 73.0, "2026-06": 69.7, "2026-07": 86.2}
        for ym, v in want.items():
            r = self.by[ym]
            op = sum(float(r[c]) for c in
                     ("外来保険売上", "自費診療売上", "物販売上"))
            self.assertAlmostEqual(op / float(r[self.COL]) / 10000, v, delta=0.05,
                                   msg=ym)

    def test_series_is_decline_then_rebound_not_six_month_decline(self):
        """撤回済みの『6か月連続低下』にならないこと。06月→07月は反発。"""
        ms = ["2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07"]
        vals = []
        for ym in ms:
            r = self.by[ym]
            op = sum(float(r[c]) for c in
                     ("外来保険売上", "自費診療売上", "物販売上"))
            vals.append(op / float(r[self.COL]))
        downs = sum(1 for i in range(1, len(vals)) if vals[i] < vals[i - 1])
        self.assertLess(downs, 5, f"連続低下として読める並び: {vals}")
        self.assertGreater(vals[-1], vals[-2], "07月は06月を上回る（反発）")
        self.assertAlmostEqual(vals[-2] / 10000, 69.7, delta=0.05)
        self.assertAlmostEqual(vals[-1] / 10000, 86.2, delta=0.05)

    def test_report_uses_outpatient_days_for_past_months(self):
        """実データを渡したとき、過去月のper-dayが外来診療日数割りであること。"""
        hist = [dict(r) for r in self.rows]
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770,
                              thursday_closed=True),
                    prev_row=self.by["2025-08"], hist=hist)
        series = rep["facts"]["hist"]["op_per_day"]
        self.assertEqual(len(series), 12)
        for x in series:
            r = self.by[x["ym"]]
            self.assertEqual(x["days"], float(r[self.COL]))
            if r["診療日数"] != r[self.COL]:
                # 差がある月は、診療日数で割っていないことがここで分かる
                self.assertNotEqual(x["days"], float(r["診療日数"]))
            op = sum(float(r[c]) for c in
                     ("外来保険売上", "自費診療売上", "物販売上"))
            self.assertAlmostEqual(x["per_day"], op / float(r[self.COL]), places=6)


# ======================================================================
class TestTargetAndLevels(unittest.TestCase):
    """経営計画目標（人が決める1本）と参考水準（自動計算）を混ぜないこと。"""

    ROLL = dict(insurance=15_113_808, selfpay=6_010_211, product=316_528,
                insurance_prev=13_393_890, selfpay_prev=8_131_750, product_prev=279_770,
                thursday_closed=True)

    def _rep(self, targets=None, **kw):
        kw = dict(self.ROLL, **kw)
        return build(make_roll(**kw), targets=targets)

    # ---- 未設定 ----------------------------------------------------
    def test_empty_file_is_normal(self):
        """monthly_targets.csv が空でも落ちない。"""
        for t in (None, [], [{"年月": "2026-08", "経営計画目標": "", "備考": ""}]):
            rep = self._rep(targets=t)
            self.assertFalse(rep["target"]["has_target"], t)
            self.assertIsNone(rep["facts"]["target_sales"], t)

    def test_missing_target_is_not_filled_in(self):
        """目標未設定を、過去実績や参考水準で勝手に埋めない。"""
        rep = self._rep(targets=[])
        self.assertIsNone(rep["target"]["target"])
        self.assertIsNone(rep["target"]["diff"])
        self.assertIsNone(rep["target"]["rate"])
        self.assertIsNone(rep["target"]["pace"])
        # 参考水準は出ているが、それを目標として持ち込んでいないこと
        self.assertTrue(rep["levels"]["display"])
        for r in rep["levels"]["display"]:
            self.assertNotEqual(r["total"], rep["facts"]["target_sales"])

    def test_no_achievement_verdict_without_target(self):
        """目標未設定では達成・未達を判定しない。"""
        rep = self._rep(targets=[])
        t = " ".join(rep["position"]["lines"])
        self.assertIn("経営計画目標は未設定です。", t)
        self.assertIn("目標達成・未達の判定は行っていません", t)
        for ng in ("目標未達", "未達です", "達成見込み", "目標を上回"):
            self.assertNotIn(ng, t)
        self.assertIsNone(rep["target"]["achieved"])

    def test_zero_or_negative_target_is_treated_as_unset(self):
        for v in ("0", "-1", "abc"):
            rep = self._rep(targets=[{"年月": "2026-08", "経営計画目標": v, "備考": ""}])
            self.assertFalse(rep["target"]["has_target"], v)

    def test_target_of_another_month_is_not_used(self):
        rep = self._rep(targets=[{"年月": "2026-09", "経営計画目標": "21500000",
                                  "備考": ""}])
        self.assertFalse(rep["target"]["has_target"])

    # ---- 目標あり ---------------------------------------------------
    def test_target_diff_and_rate(self):
        """目標が入ったときだけ目標差と達成見込み率を出す。"""
        rep = self._rep(targets=[{"年月": "2026-08", "経営計画目標": "21500000",
                                  "備考": "検証用"}])
        t = rep["target"]
        self.assertTrue(t["has_target"])
        self.assertEqual(t["target"], 21_500_000)
        total = rep["facts"]["total"]
        self.assertAlmostEqual(t["diff"], total - 21_500_000, places=6)
        self.assertAlmostEqual(t["rate"], total / 21_500_000, places=9)
        self.assertFalse(t["achieved"])
        self.assertEqual(t["note"], "検証用")

    def test_remaining_pace_does_not_double_count(self):
        """残り必要額 = 目標 − 訪問介護 − 確定実績 − 経過未反映。"""
        rep = self._rep(unrecorded_total="auto",
                        targets=[{"年月": "2026-08", "経営計画目標": "21500000",
                                  "備考": ""}])
        f, p = rep["facts"], rep["target"]["pace"]
        self.assertIsNotNone(p)
        want = (21_500_000 - (f["visit_ins"] + f["care"])
                - f["actual_to_date"] - f["unrecorded_total"])
        self.assertAlmostEqual(p["need_total"], want, places=6)
        self.assertAlmostEqual(p["need_per_day"], want / p["days_remaining"], places=6)
        # 残りは「外来診療日」で割る（暦日でも売上発生日でもない）
        self.assertEqual(p["days_remaining"], f["days_remaining_outpatient"])
        # 3要素の合計が外来3区分の月末見込みに一致する＝二重計上が無い
        self.assertAlmostEqual(
            f["actual_to_date"] + f["unrecorded_total"] + f["remaining_forecast"],
            f["op_now"], delta=2)
        self.assertAlmostEqual(p["current_per_day"],
                               f["remaining_forecast"] / p["days_remaining"], places=6)

    def test_no_pace_without_target(self):
        self.assertIsNone(self._rep(targets=[])["target"]["pace"])

    # ---- 参考水準 ---------------------------------------------------
    def test_four_main_levels(self):
        rep = self._rep(targets=[])
        keys = {r["key"] for r in rep["levels"]["display"]}
        self.assertEqual(keys, {"prev_year", "recent", "top_quartile", "best"})
        self.assertEqual({r["key"] for r in rep["levels"]["main"]},
                         {"prev_year", "recent"})
        self.assertEqual({r["key"] for r in rep["levels"]["sub"]},
                         {"top_quartile", "best"})

    def test_levels_use_outpatient_days_not_clinic_days(self):
        """参考水準の分母は外来診療日数。診療日数は使わない。"""
        rep = self._rep(targets=[])
        f = rep["facts"]
        days = f["days_month_outpatient"]
        vc = f["visit_ins"] + f["care"]
        for r in rep["levels"]["display"]:
            self.assertAlmostEqual(r["outpatient"], r["per_day"] * days, places=6)
            self.assertAlmostEqual(r["total"], r["outpatient"] + vc, places=6)
        py = rep["levels"]["by_key"]["prev_year"]
        pv = (float(PREV_ROW["外来保険売上"]) + float(PREV_ROW["自費診療売上"])
              + float(PREV_ROW["物販売上"]))
        self.assertAlmostEqual(py["per_day"],
                               pv / float(PREV_ROW["外来診療日数"]), places=6)
        self.assertNotAlmostEqual(py["per_day"],
                                  pv / float(PREV_ROW["診療日数"]), places=0)

    def test_level_names_avoid_line_metaphors(self):
        """月によって上下が逆転しても壊れない名前にする。"""
        rep = self._rep(targets=[])
        names = [r["label"] for r in rep["levels"]["display"]]
        for n in names:
            self.assertTrue(n.endswith("水準"), n)
        text = all_text(rep) + " ".join(rep["position"]["lines"])
        for ng in ("防衛ライン", "挑戦ライン"):
            self.assertNotIn(ng, text)

    def test_display_is_sorted_by_amount(self):
        rep = self._rep(targets=[])
        vals = [r["total"] for r in rep["levels"]["display"]]
        self.assertEqual(vals, sorted(vals, reverse=True))

    # ---- 判定の分岐 -------------------------------------------------
    def _verdict(self, target):
        return self._rep(targets=[{"年月": "2026-08", "経営計画目標": str(target),
                                   "備考": ""}])["position"]["verdict"]

    def test_verdict_branches(self):
        rep = self._rep(targets=[])
        by = rep["levels"]["by_key"]
        high = by["top_quartile"]["total"]
        low = by["recent"]["total"]
        total = rep["facts"]["total"]
        self.assertGreater(total, high)          # このfixtureは高い月
        # 目標が着地より上 → 未達だが過去実績から見れば高い
        self.assertEqual(self._verdict(int(total) + 3_000_000), "miss_but_high")
        # 目標が着地より下 → 達成、かつ上位水準も超える
        self.assertEqual(self._verdict(int(low) - 1_000_000), "hit_high")

    def test_miss_and_low_is_reported_as_a_site_gap(self):
        """目標にも参考水準にも届かない月は、現場側のギャップとして扱う。"""
        rep = build(make_roll(insurance=9_000_000, selfpay=1_500_000, product=100_000,
                              insurance_prev=13_393_890, selfpay_prev=8_131_750, product_prev=279_770,
                              thursday_closed=True),
                    targets=[{"年月": "2026-08", "経営計画目標": "21500000",
                              "備考": ""}])
        self.assertEqual(rep["position"]["verdict"], "miss_and_low")
        t = " ".join(rep["position"]["lines"])
        self.assertIn("今月の稼働そのものが過去の通常水準に届いていない", t)


# ======================================================================
class TestDentalPatientValue(unittest.TestCase):
    """患者価値・来院構造のKPI。分子は歯科診療売上（外来3区分＋訪問保険）。

    以前は 外来3区分 ÷ 総来院回数 という式を使っていたが、分母だけが訪問診療を
    含むため 1来院あたりで約 -10.7% 過小に出ていた（2025-08 実測）。この式は廃止した。
    """

    def _rep(self, **kw):
        base = dict(insurance=15_113_808, selfpay=6_010_211, product=316_528,
                    insurance_prev=13_393_890, selfpay_prev=8_131_750,
                    product_prev=279_770, thursday_closed=True)
        base.update(kw)
        return build(make_roll(**base), targets=[])

    # ---- 旧定義（案C）が残っていないこと ----------------------------
    def test_old_formula_is_gone(self):
        """外来3区分 ÷ 総来院回数 / 総患者数 という式を使っていないこと。"""
        f = self._rep()["facts"]
        self.assertNotAlmostEqual(f["per_visit_now"], f["op_now"] / f["visit"], places=2)
        self.assertNotAlmostEqual(f["per_patient_now"], f["op_now"] / f["patients"],
                                  places=2)

    def test_outpatient_visits_per_day_is_not_published(self):
        """外来限定の来院回数が無いので、外来診療日あたり来院回数は出さない。"""
        f = self._rep()["facts"]
        self.assertIsNone(f["visits_per_day_now"])
        self.assertIsNone(f["visits_per_day_prev"])
        self.assertNotIn("visits_per_day", self._rep()["decomposition"]["by_key"])

    # ---- 分子の中身 --------------------------------------------------
    def test_numerator_includes_visit_insurance(self):
        f = self._rep()["facts"]
        self.assertAlmostEqual(f["dental_now"], f["op_now"] + f["visit_ins"], places=6)
        self.assertAlmostEqual(f["per_visit_now"], f["dental_now"] / f["visit"],
                               places=6)
        self.assertAlmostEqual(f["per_patient_now"], f["dental_now"] / f["patients"],
                               places=6)

    def test_numerator_excludes_care(self):
        """介護は分子に入れない（対応する来院回数・患者が存在しないため）。"""
        f = self._rep()["facts"]
        self.assertGreater(f["care"], 0)
        self.assertAlmostEqual(f["dental_now"], f["total"] - f["care"], places=6)
        self.assertNotAlmostEqual(f["per_visit_now"], f["total"] / f["visit"], places=2)
        self.assertNotAlmostEqual(f["per_patient_now"], f["total"] / f["patients"],
                                  places=2)

    def test_prev_year_uses_same_definition(self):
        f = self._rep()["facts"]
        pv = (float(PREV_ROW["外来保険売上"]) + float(PREV_ROW["自費診療売上"])
              + float(PREV_ROW["物販売上"]) + float(PREV_ROW["訪問保険売上"]))
        self.assertAlmostEqual(f["dental_prev"], pv, places=6)
        self.assertAlmostEqual(f["per_visit_prev"], pv / f["visit_prev"], places=6)
        self.assertAlmostEqual(f["per_patient_prev"], pv / f["patients_prev"], places=6)

    # ---- 患者数と来院回数 --------------------------------------------
    def test_visits_and_patients_are_not_the_same_thing(self):
        f = self._rep()["facts"]
        self.assertGreater(f["visit"], f["patients"])
        self.assertGreater(f["visits_per_patient_now"], 1.0)
        self.assertAlmostEqual(f["visits_per_patient_now"],
                               f["visit"] / f["patients"], places=9)

    def test_label_is_unique_patient_visits(self):
        """『1患者あたり来院回数』という名前は使わない。"""
        rep = self._rep()
        self.assertEqual(MR.VISITS_PER_PATIENT_LABEL, "1ユニーク患者あたり来院回数")
        names = [r["label"] for r in rep["decomposition"]["rows"]]
        names += [r["name"] for r in rep["capacity"]["rows"]]
        self.assertIn(MR.VISITS_PER_PATIENT_LABEL, names)
        for n in names:
            self.assertNotEqual(n, "1患者あたり来院回数")
        self.assertNotIn("1患者あたり来院回数", all_text(rep))

    def test_official_labels(self):
        self.assertEqual(MR.PER_VISIT_LABEL, "1来院あたり売上（外来＋訪問）")
        self.assertEqual(MR.PER_PATIENT_LABEL, "1ユニーク患者あたり売上（外来＋訪問）")

    # ---- 分解の恒等式 ------------------------------------------------
    def test_both_decompositions_hold(self):
        f = self._rep()["facts"]
        self.assertAlmostEqual(f["dental_now"],
                               f["visit"] * f["per_visit_now"], places=3)
        self.assertAlmostEqual(f["dental_now"],
                               f["patients"] * f["per_patient_now"], places=3)
        self.assertAlmostEqual(
            f["per_patient_now"],
            f["visits_per_patient_now"] * f["per_visit_now"], places=4)

    def test_outpatient_productivity_is_kept_separate(self):
        """外来生産性は分子も分母も外来のまま、別群として残す。"""
        rep = self._rep()
        f = rep["facts"]
        self.assertAlmostEqual(f["per_day_now"],
                               f["op_now"] / f["days_month_outpatient"], places=6)
        by = rep["decomposition"]["by_key"]
        self.assertIn("per_day", by)
        self.assertIn("dental", by)
        self.assertNotEqual(by["per_day"]["how"], by["dental"]["how"])
        self.assertIn("母集団が違います", rep["decomposition"]["text"])

    # ---- 履歴（前月・直近3か月）--------------------------------------
    def test_history_series_uses_same_definition(self):
        rep = self._rep()
        rows = {r["年月"]: r for r in hist_rows()}
        for x in rep["facts"]["hist"]["op_per_day"]:
            r = rows[x["ym"]]
            want = (r["外来保険売上"] + r["自費診療売上"] + r["物販売上"]
                    + r["訪問保険売上"])
            self.assertAlmostEqual(x["dental"], want, places=6)
            self.assertAlmostEqual(x["per_visit"], want / x["visits"], places=6)
            self.assertAlmostEqual(x["per_patient"], want / x["patients"], places=6)

    def test_prev_month_and_recent3_are_comparable(self):
        """前月・直近3か月も同じ定義で並べられること。"""
        series = self._rep()["facts"]["hist"]["op_per_day"]
        self.assertGreaterEqual(len(series), 12)
        for x in series:
            for k in ("per_visit", "per_patient", "visits_per_patient"):
                self.assertIsNotNone(x[k], f"{x['ym']} {k}")
        last3 = series[-3:]
        self.assertEqual(len(last3), 3)
        self.assertTrue(all(x["per_visit"] > 0 for x in last3))

    def test_data_note_explains_the_population(self):
        notes = " ".join(self._rep()["notes"])
        self.assertIn("歯科診療売上", notes)
        self.assertIn("介護は対応する来院・患者記録がないため含みません", notes)
        self.assertIn("同じ母集団", notes)

    def test_not_used_as_a_target(self):
        rep = self._rep()
        self.assertIsNone(rep["facts"]["target_sales"])
        self.assertFalse(rep["target"]["has_target"])


# ======================================================================
class TestModuleInterface(unittest.TestCase):
    """画面側の呼び出しと build_management_report の引数がずれていないこと。

    本番で
      build_management_report() takes from 1 to 3 positional arguments but 4 were given
    が出た。Streamlit はメインスクリプトだけ実行のたびに読み直し、import 済み
    モジュールは sys.modules に残すため、デプロイ後もプロセスが再起動しないと
    mgmt_report が古いまま残る。呼び出し側と定義側の本数をここで固定する。
    """

    def _app_source(self):
        import os
        app = os.path.join(os.path.dirname(os.path.abspath(__file__)), "streamlit_app.py")
        if not os.path.exists(app):
            self.skipTest("streamlit_app.py が無い")
        return io.open(app, encoding="utf-8").read()

    def test_signature_accepts_four_positional_arguments(self):
        import inspect
        names = list(inspect.signature(MR.build_management_report).parameters)
        self.assertEqual(names[:5],
                         ["roll", "prev_year_row", "prev_forecast_row", "history_rows",
                          "target_rows"])
        MR.build_management_report({}, None, None, [], [])   # 画面と同じ5引数

    def test_streamlit_call_matches_signature(self):
        import inspect
        src = self._app_source()
        marker = "MR.build_management_report("
        i = src.find(marker)
        self.assertGreater(i, 0, "呼び出しが見つからない")
        # 対応する閉じ括弧まで読む
        depth, j = 0, i + len(marker) - 1
        while j < len(src):
            if src[j] == "(":
                depth += 1
            elif src[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        inner = src[i + len(marker):j]
        # トップレベルのカンマだけで割る
        args, depth, cur = [], 0, ""
        for ch in inner:
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            if ch == "," and depth == 0:
                args.append(cur); cur = ""
            else:
                cur += ch
        if cur.strip():
            args.append(cur)
        args = [a.strip() for a in args if a.strip()]
        params = inspect.signature(MR.build_management_report).parameters
        self.assertEqual(len(args), 5, args)
        self.assertLessEqual(len(args), len(params),
                             f"呼び出し{len(args)}引数 > 定義{len(params)}引数")
        # history / 目標を渡すのをやめてエラーを消す、という直し方をしていないこと
        self.assertIn("read_history_rows", inner)
        self.assertIn("read_target_rows", inner)

    def test_app_reloads_the_module(self):
        """Streamlit の sys.modules キャッシュ対策が入っていること。"""
        self.assertIn("importlib.reload(MR)", self._app_source())

    def test_stale_module_would_be_replaced_by_reload(self):
        """古いモジュールが sys.modules に残っていても、reload で現在の定義に戻る。"""
        import sys, types, importlib, inspect
        saved = sys.modules.get("mgmt_report")
        try:
            stale = types.ModuleType("mgmt_report")
            stale.__file__ = MR.__file__
            exec("def build_management_report(roll, prev_year_row=None, "
                 "prev_forecast_row=None, history_rows=None):\n    return {}\n",
                 stale.__dict__)
            sys.modules["mgmt_report"] = stale
            with self.assertRaises(TypeError):
                stale.build_management_report({}, None, None, [], [])
            fresh = importlib.reload(stale)
            self.assertIn("target_rows",
                          inspect.signature(fresh.build_management_report).parameters)
            fresh.build_management_report({}, None, None, [], [])
        finally:
            if saved is not None:
                sys.modules["mgmt_report"] = saved


# ======================================================================
class TestOutpatientValue(unittest.TestCase):
    """純外来の患者価値・生産性（訪問診療を含まない・確定実績のみ）。

    ここで守ること
      1. 分子は外来3区分、分母は訪問診療を含まない来院回数・ユニーク患者数
      2. 前年比較は外来診療日数が一致したときだけ出す
      3. 月末見込みは作らない
      4. 「単価が落ちた」と「人が来ていない」を取り違えない
      5. 何が単価を下げたのかまでは断定しない
    """

    # 2026-08-24 スナップショットの実測値。ここを変えるときは実データで確かめる。
    REAL = dict(obs_total=11_491_330, obs_outp=8_237_160, obs_jihi=3_036_000,
                obs_buppin=218_170, out_days=13,
                obs_prev_total=12_876_640, py_biz_out_days=13,
                pyb_outp=7_106_750, pyb_jihi=5_585_250, pyb_buppin=184_640,
                op_visits=915, op_patients=649,
                pyb_op_visits=798, pyb_op_patients=589)

    def _rep(self, **kw):
        base = dict(self.REAL)
        base.update(kw)
        return build(make_roll(15_113_808, 6_010_211, 316_528,
                               13_393_890, 8_131_750, 279_770, **base))

    def _by_name(self, rep):
        return {r["name"]: r for r in rep["outpatient_value"]["rows"]}

    # ---- 1. 数え方 --------------------------------------------------
    def test_numerator_is_outpatient_three_segments(self):
        """分子は外来保険＋自費＋物販。訪問保険・介護は入れない。"""
        f = self._rep()["facts"]
        self.assertEqual(f["op_sales_now"], self.REAL["obs_total"])
        self.assertAlmostEqual(
            f["op_per_visit_now"],
            self.REAL["obs_total"] / self.REAL["op_visits"], places=6)
        self.assertAlmostEqual(
            f["op_per_patient_now"],
            self.REAL["obs_total"] / self.REAL["op_patients"], places=6)

    def test_denominator_excludes_home_visits(self):
        """分母は訪問を含まない外来来院回数。総来院回数で割っていない。"""
        f = self._rep(visit=1500, visit_prev=1450)["facts"]
        self.assertNotAlmostEqual(f["op_per_visit_now"],
                                  self.REAL["obs_total"] / 1500, places=0)
        # （外来＋訪問）の指標とは別物であることも確かめる
        self.assertNotAlmostEqual(f["op_per_visit_now"], f["per_visit_now"], places=0)

    def test_visits_per_day_uses_outpatient_days(self):
        f = self._rep()["facts"]
        self.assertAlmostEqual(f["op_visits_per_day_now"], 915 / 13, places=6)
        # 売上発生日（14日）で割っていない
        self.assertNotAlmostEqual(f["op_visits_per_day_now"], 915 / 14, places=1)

    def test_visits_per_patient_is_visits_over_patients(self):
        f = self._rep()["facts"]
        self.assertAlmostEqual(f["op_visits_per_patient_now"], 915 / 649, places=6)

    # ---- 2. 2026-08 の正式値 ----------------------------------------
    def test_august_2026_main_three(self):
        """メイン3本の表示値と前年比を固定する。"""
        n = self._by_name(self._rep())
        want = {
            MR.OP_PER_VISIT_LABEL: ("12,559円", "16,136円", -22.2),
            MR.OP_PER_PATIENT_LABEL: ("17,706円", "21,862円", -19.0),
            MR.OP_VISITS_PER_DAY_LABEL: ("70.38回", "61.38回", 14.7),
        }
        for name, (now, prev, rt) in want.items():
            r = n[name]
            self.assertEqual(r["now"], now, name)
            self.assertEqual(r["prev"], prev, name)
            self.assertAlmostEqual(r["rate"], rt, delta=0.05, msg=name)

    def test_august_2026_detail(self):
        """詳細（折りたたみ）側の値と前年比を固定する。"""
        n = self._by_name(self._rep())
        self.assertEqual(n[MR.OP_VISITS_LABEL]["now"], "915回")
        self.assertEqual(n[MR.OP_VISITS_LABEL]["prev"], "798回")
        self.assertAlmostEqual(n[MR.OP_VISITS_LABEL]["rate"], 14.7, delta=0.05)
        self.assertEqual(n[MR.OP_PATIENTS_LABEL]["now"], "649人")
        self.assertEqual(n[MR.OP_PATIENTS_LABEL]["prev"], "589人")
        self.assertAlmostEqual(n[MR.OP_PATIENTS_LABEL]["rate"], 10.2, delta=0.05)
        r = n[MR.OP_VISITS_PER_PATIENT_LABEL]
        self.assertEqual((r["now"], r["prev"]), ("1.41回", "1.35回"))
        self.assertAlmostEqual(r["rate"], 4.1, delta=0.05)
        self.assertEqual(n[MR.OP_SALES_LABEL]["now"], "1,149万円")
        self.assertEqual(n[MR.OP_SALES_LABEL]["prev"], "1,288万円")

    def test_main_and_detail_split_matches_the_spec(self):
        ov = self._rep()["outpatient_value"]
        self.assertEqual([r["name"] for r in ov["main"]],
                         list(MR.OUTPATIENT_KPI_MAIN))
        self.assertEqual([r["name"] for r in ov["detail"]],
                         list(MR.OUTPATIENT_KPI_DETAIL))
        self.assertEqual(len(ov["rows"]), len(set(r["name"] for r in ov["rows"])))

    def test_scope_states_outpatient_days_on_both_sides(self):
        ov = self._rep()["outpatient_value"]
        self.assertEqual(ov["scope"], "確定実績 13外来診療日")
        self.assertEqual(ov["compare_scope"], "前年同じ 13外来診療日と比較")

    # ---- 3. 月末見込みを作らない ------------------------------------
    def test_no_month_end_forecast_anywhere(self):
        """純外来KPIに月末見込みの行・値を作らない。"""
        rep = self._rep()
        ov = rep["outpatient_value"]
        for r in ov["rows"]:
            self.assertNotIn("見込み", r["kind"], r["name"])
            self.assertNotIn("見込み", r["name"])
        self.assertIn("確定実績", ov["kind"])
        # facts 側にも「純外来の月末見込み」を表す名前を作っていない
        for k in rep["facts"]:
            if k.startswith("op_") and k.endswith("_forecast"):
                self.fail(f"純外来の月末見込みキーがある: {k}")

    def test_report_says_no_month_end_forecast(self):
        note = "\n".join(self._rep()["notes"])
        self.assertIn("月末見込みは作っていません", note)

    # ---- 4. 比較を出してよいかの判定 --------------------------------
    def test_no_comparison_when_outpatient_days_differ(self):
        """外来診療日数が一致しない月は率も差も出さない。"""
        ov = self._rep(py_biz_out_days=12)["outpatient_value"]
        self.assertFalse(ov["comparable"])
        self.assertEqual(ov["reason"], "days_mismatch")
        for r in ov["rows"]:
            self.assertEqual(r["prev"], "—", r["name"])
            self.assertEqual(r["diff"], "—", r["name"])
            self.assertIsNone(r["rate"], r["name"])
        self.assertIn("同じ日数まで累計した比較にならない", ov["text"])
        self.assertNotIn("%", ov["text"])

    def test_no_comparison_when_prev_counts_missing(self):
        """前年側の件数が無いスナップショットでは比較を出さない。"""
        ov = self._rep(with_prev_outpatient_counts=False)["outpatient_value"]
        self.assertTrue(ov["available"])
        self.assertFalse(ov["comparable"])
        self.assertEqual(ov["reason"], "no_prev_counts")
        self.assertIn("外来ユニーク患者数が", ov["text"])

    def test_old_snapshot_without_counts_degrades(self):
        """2つのキーが無い古いスナップショットでも落ちず、推定もしない。"""
        rep = self._rep(with_outpatient_counts=False)
        ov = rep["outpatient_value"]
        self.assertFalse(ov["available"])
        self.assertEqual(ov["rows"], [])
        self.assertIn("入っていない", ov["text"])
        f = rep["facts"]
        for k in ("op_per_visit_now", "op_per_patient_now",
                  "op_visits_per_day_now", "op_visits_per_patient_now"):
            self.assertIsNone(f[k], k)

    def test_zero_counts_are_not_treated_as_missing(self):
        """0件は「未取得」ではない。0で割らず、値も捏造しない。"""
        rep = self._rep(op_visits=0, op_patients=0)
        self.assertTrue(rep["outpatient_value"]["available"])
        self.assertIsNone(rep["facts"]["op_per_visit_now"])

    # ---- 5. 経営分析（主因の切り分け）--------------------------------
    def test_unit_price_is_named_as_the_difference(self):
        """量が落ちていないのに単価が落ちている月は、単価を主因として書く。"""
        txt = self._rep()["outpatient_value"]["text"]
        self.assertIn("1回の来院あたりの売上が下がっている", txt)
        self.assertIn("患者数の不足でも、1日あたり来院数の不足でも、"
                      "来院頻度の低下でもなく", txt)

    def test_does_not_blame_a_specific_treatment_mix(self):
        """保険処置構成・自費比率・メンテ比率・診療内容のどれかを主因と断定しない。"""
        txt = self._rep()["outpatient_value"]["text"]
        self.assertIn("この画面のデータでは判別できません", txt)
        for w in ("保険処置の構成", "自費の比率", "メンテナンス", "診療内容"):
            self.assertIn(w, txt)
        for bad in ("自費が減ったため", "メンテナンスが減ったため",
                    "保険処置の構成が変わったため", "が原因です"):
            self.assertNotIn(bad, txt)

    def test_volume_drop_is_named_when_volume_actually_drops(self):
        """来院が落ちている月は、単価ではなく量の方を主因として書く。"""
        txt = self._rep(op_visits=650, op_patients=520,
                        obs_total=11_000_000)["outpatient_value"]["text"]
        self.assertIn("来院の量", txt)
        self.assertNotIn("患者数の不足でも", txt)

    def test_no_decline_claim_when_nothing_declines(self):
        txt = self._rep(obs_total=16_000_000)["outpatient_value"]["text"]
        self.assertIn("前年を下回っておらず", txt)

    def test_direction_words_match_the_signs(self):
        """『下回っていません』と書いた指標が、実際にマイナスでないこと。"""
        ov = self._rep()["outpatient_value"]
        n = {r["name"]: r for r in ov["rows"]}
        if "いずれも前年を下回っていません" in ov["text"]:
            for name in (MR.OP_VISITS_LABEL, MR.OP_PATIENTS_LABEL,
                         MR.OP_VISITS_PER_DAY_LABEL,
                         MR.OP_VISITS_PER_PATIENT_LABEL):
                self.assertGreater(n[name]["rate"], -MR.DENSITY_ALERT * 100, name)

    # ---- 6. 既存KPIと混ぜない ---------------------------------------
    def test_kept_separate_from_the_visit_inclusive_kpi(self):
        """（外来＋訪問）の表に純外来の指標が混ざらない。逆も同じ。"""
        rep = self._rep()
        cap_names = {r["name"] for r in rep["capacity"]["rows"]}
        opv_names = {r["name"] for r in rep["outpatient_value"]["rows"]}
        self.assertEqual(cap_names & opv_names, set())
        for n in opv_names:
            self.assertTrue(n.startswith("外来"), n)

    def test_visit_inclusive_kpi_is_unchanged(self):
        """純外来KPIを足しても、既存の（外来＋訪問）の値は動かない。"""
        with_ = self._rep()["facts"]
        without = self._rep(with_outpatient_counts=False,
                            with_prev_outpatient_counts=False)["facts"]
        for k in ("per_visit_now", "per_visit_prev", "per_patient_now",
                  "per_patient_prev", "visits_per_patient_now",
                  "op_per_day_actual", "op_per_day_prev", "op_diff_total",
                  "total", "yoy", "op_now", "op_prev"):
            self.assertEqual(with_[k], without[k], k)


# ======================================================================
class TestOutpatientValueOnRealSnapshot(unittest.TestCase):
    """配布済みスナップショット 2026-08-24 での実値。

    outputs/ は日次更新のたびに書き換わるので、日付を固定した検証の土台には
    ならない（実際 8/25 の更新で 960/675 に変わった）。配布済みスナップショットは
    コミット済みで動かないため、こちらを正として 8/24 の値を固定する。
    """

    AS_OF = "2026_08_24"

    @classmethod
    def setUpClass(cls):
        import json
        import csv
        here = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(here, "data", "2026_08", "snapshots", cls.AS_OF,
                            "daily_rolling_forecast.json")
        if not os.path.isfile(path):
            raise unittest.SkipTest(f"{cls.AS_OF} のスナップショットが無い")
        with io.open(path, encoding="utf-8") as fh:
            cls.roll = json.load(fh)
        if cls.roll.get("as_of_date") != "2026-08-24":
            raise unittest.SkipTest("as_of が 2026-08-24 ではない")
        hp = os.path.join(here, "data", "history", "monthly_actuals.csv")
        with io.open(hp, encoding="utf-8-sig", newline="") as fh:
            cls.hist = [r for r in csv.DictReader(fh) if r.get("年月")]
        cls.prev = next(r for r in cls.hist if r["年月"] == "2025-08")
        cls.rep = MR.build_management_report(cls.roll, cls.prev, None, cls.hist, None)

    def test_snapshot_carries_the_two_new_keys(self):
        self.assertEqual(self.roll["outpatient_visit_actual_to_date"], 915)
        self.assertEqual(self.roll["outpatient_unique_patients_actual_to_date"], 649)

    def test_prev_year_same_bizdays_carries_the_two_new_keys(self):
        b = self.roll["progress_through_yesterday"]["prev_year_same_bizdays"]
        self.assertEqual(b["outpatient_visit_count"], 798)
        self.assertEqual(b["outpatient_unique_patient_count"], 589)
        # 前年側も当年と同じ外来診療日数まで累計している
        self.assertEqual(b["outpatient_days_count"],
                         self.roll["outpatient_actual_days_count"])

    def test_main_three_match_the_spec(self):
        n = {r["name"]: r for r in self.rep["outpatient_value"]["main"]}
        self.assertEqual((n[MR.OP_PER_VISIT_LABEL]["now"],
                          n[MR.OP_PER_VISIT_LABEL]["prev"]), ("12,559円", "16,136円"))
        self.assertAlmostEqual(n[MR.OP_PER_VISIT_LABEL]["rate"], -22.2, delta=0.05)
        self.assertEqual((n[MR.OP_PER_PATIENT_LABEL]["now"],
                          n[MR.OP_PER_PATIENT_LABEL]["prev"]), ("17,706円", "21,862円"))
        self.assertAlmostEqual(n[MR.OP_PER_PATIENT_LABEL]["rate"], -19.0, delta=0.05)
        self.assertEqual((n[MR.OP_VISITS_PER_DAY_LABEL]["now"],
                          n[MR.OP_VISITS_PER_DAY_LABEL]["prev"]), ("70.38回", "61.38回"))
        self.assertAlmostEqual(n[MR.OP_VISITS_PER_DAY_LABEL]["rate"], 14.7, delta=0.05)

    def test_visits_per_patient_matches_the_spec(self):
        n = {r["name"]: r for r in self.rep["outpatient_value"]["detail"]}
        r = n[MR.OP_VISITS_PER_PATIENT_LABEL]
        self.assertEqual((r["now"], r["prev"]), ("1.41回", "1.35回"))
        self.assertAlmostEqual(r["rate"], 4.1, delta=0.05)

    def test_unique_patients_are_not_a_sum_of_daily_uniques(self):
        """月内ユニークは延べ来院回数より必ず小さい（同じ患者が別の日に来るため）。"""
        self.assertLess(self.roll["outpatient_unique_patients_actual_to_date"],
                        self.roll["outpatient_visit_actual_to_date"])

    def test_numerator_is_the_outpatient_three_segments_of_the_same_period(self):
        cur = self.roll["progress_through_yesterday"]["current"]
        op = cur["insurance_outpatient"] + cur["selfpay"] + cur["product"]
        self.assertEqual(self.rep["facts"]["op_sales_now"], op)

    def test_conclusion_names_unit_price_not_volume(self):
        txt = self.rep["outpatient_value"]["text"]
        self.assertIn("1回の来院あたりの売上が下がっている", txt)
        self.assertIn("この画面のデータでは判別できません", txt)

    def test_forecast_keys_are_untouched(self):
        """純外来の追加で予測値が動いていないこと。"""
        self.assertEqual(self.roll["current_forecast_total"], 21_030_192)


# ======================================================================
class TestOutpatientValueInApp(unittest.TestCase):
    """画面側に純外来の節がつながっていること。"""

    def _app_source(self):
        app = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "streamlit_app.py")
        with io.open(app, encoding="utf-8") as fh:
            return fh.read()

    def test_section_is_rendered(self):
        src = self._app_source()
        self.assertIn("def _render_outpatient_value(rep):", src)
        self.assertIn("_render_outpatient_value(mgmt)", src)

    def test_section_is_labelled_as_excluding_home_visits(self):
        src = self._app_source()
        self.assertIn("外来患者価値・外来生産性", src)
        self.assertIn("訪問診療を含まない・確定実績", src)

    def test_main_and_detail_come_from_the_report(self):
        """メイン／詳細の割り振りはレポート側の群をそのまま使う。"""
        src = self._app_source()
        self.assertIn('ov.get("main", [])', src)
        self.assertIn('ov.get("detail", [])', src)

    def test_app_does_not_recompute_the_kpi(self):
        """画面側で割り算をやり直していないこと（定義を2か所に置かない）。"""
        src = self._app_source()
        start = src.index("def _render_outpatient_value(rep):")
        end = src.index("def _render_actions(rep):")
        body = src[start:end]
        for token in ("outpatient_visit_actual_to_date",
                      "outpatient_unique_patients_actual_to_date"):
            self.assertNotIn(token, body)


# ======================================================================
class TestSummaryLead(unittest.TestCase):
    """SUMMARY の結論文。前年総額比と日数補正後の向きで文型を変える。

    2026-08-25 に「届かない見込みですが…下回っています」という
    逆接が出ていた。前段が後段の向きを見ずに接続詞を決めていたのが原因。
    ここで4ケース＋水準なしを固定する。
    """

    PREV = 21_805_410      # 前年総額 2,181万円
    LV = 20_635_654        # 日数をそろえた前年同月水準 2,064万円

    def lead(self, total, lv=LV, d_days=-1):
        yoy = total - self.PREV
        f = {"total": float(total), "prev_total": float(self.PREV),
             "yoy": float(yoy), "yoy_rate": round(yoy / self.PREV * 100, 1)}
        py_lv = None if lv is None else {"total": float(lv)}
        return MR._yoy_lead(f, py_lv, d_days)

    # ---- A: 総額↓ / 日数補正後↑ → 逆接が成立する唯一のケース ----
    def test_case_a_uses_contrast(self):
        t = self.lead(21_030_192)            # 2026-08-24 の実値
        self.assertIn("ですが、", t)
        self.assertIn("は上回ります。", t)
        self.assertNotIn("下回っており", t)
        self.assertEqual(
            t, "前年総額2,181万円を78万円（-3.6%）下回る見込みですが、"
               "外来診療日は前年より1日少なく、"
               "日数をそろえた前年同月水準2,064万円は上回ります。")

    # ---- B: 総額↓ / 日数補正後↓ → 逆接を使わない ----
    def test_case_b_has_no_contrast(self):
        t = self.lead(20_449_283)            # 2026-08-25 の実値
        self.assertNotIn("ですが", t)
        self.assertNotIn("届かない", t)
        self.assertIn("下回る見込みです。", t)
        self.assertIn("も19万円下回っており", t)

    def test_case_b_forbidden_phrases(self):
        """撤回した言い回しが二度と出ないこと。"""
        t = self.lead(20_449_283)
        for bad in ("届かない見込みですが",
                    "前年同月水準2,064万円は下回っています",
                    "水準2,064万円は下回"):
            self.assertNotIn(bad, t, f"禁止表現が出た: {bad}")

    def test_case_b_exact_text(self):
        self.assertEqual(
            self.lead(20_449_283),
            "前年総額2,181万円を136万円（-6.2%）下回る見込みです。"
            "外来診療日は前年より1日少ないものの、"
            "日数をそろえた前年同月水準2,064万円も19万円下回っており、"
            "日数の違いを考慮しても前年水準には届いていません。")

    # ---- C1: 総額↑ / 日数補正後↑ → 順接 ----
    def test_case_c1_is_plain(self):
        t = self.lead(21_900_000)
        self.assertNotIn("ですが", t)
        self.assertIn("上回る見込みで、", t)
        self.assertIn("も上回ります。", t)

    # ---- C2: 総額↑ / 日数補正後↓ → 逆接 ----
    def test_case_c2_uses_contrast(self):
        t = self.lead(21_900_000, lv=22_000_000, d_days=1)
        self.assertIn("ですが、", t)
        self.assertIn("外来診療日数をそろえて比較すると", t)
        self.assertRegex(t, r"前年同月水準[0-9,]+万円を[0-9,]+万円下回ります。$")
        self.assertNotIn("も上回ります", t)

    # ---- D: 日数をそろえた水準が作れない ----
    def test_case_d_is_single_sentence(self):
        t = self.lead(21_878_649, lv=None)
        self.assertEqual(t, "前年総額2,181万円を7万円（+0.3%）上回る見込みです。")
        self.assertNotIn("日数", t)
        self.assertNotIn("外来診療日", t)

    # ---- 共通の約束 ----
    def test_particle_is_wo_or_mo_not_ha(self):
        """『水準◯◯は下回る』とは書かない（主語がずれて読める）。"""
        for total, lv, dd in ((20_449_283, self.LV, -1),
                              (21_900_000, 22_000_000, 1)):
            t = self.lead(total, lv, dd)
            self.assertNotRegex(t, r"水準[0-9,]+万円は下回")

    def test_never_claims_days_caused_the_gap(self):
        """日数の差を総額差の原因として断定しない。"""
        for total, lv, dd in ((21_030_192, self.LV, -1),
                              (20_449_283, self.LV, -1),
                              (21_900_000, self.LV, -1),
                              (21_900_000, 22_000_000, 1)):
            t = self.lead(total, lv, dd)
            for bad in ("ため", "せい", "による差", "が原因"):
                self.assertNotIn(bad, t, f"因果を断定している: {t}")

    def test_no_days_clause_when_days_are_equal(self):
        t = self.lead(20_449_283, d_days=0)
        self.assertNotIn("外来診療日は前年より", t)
        self.assertIn("も19万円下回っており", t)

    def test_direction_word_matches_the_sign(self):
        for total in (19_000_000, 20_449_283, 21_030_192, 21_900_000, 23_000_000):
            t = self.lead(total)
            if total >= self.PREV:
                self.assertIn("上回る見込み", t)
            else:
                self.assertIn("下回る見込み", t)

    def test_lead_is_used_by_the_report(self):
        """_summary の lead が実際にこの文から始まること。"""
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770))
        f = rep["facts"]
        by = (rep["levels"] or {}).get("by_key") or {}
        want = MR._yoy_lead(f, by.get("prev_year"), f.get("days_outpatient_diff"))
        self.assertTrue(rep["summary"]["lead"].startswith(want), rep["summary"]["lead"])


# ======================================================================
# 予測変更の内訳
# ----------------------------------------------------------------------
# テストは2種類に分ける。混ぜると日次更新のたびにテスト負債になる。
#
#   A. ロジック固定テスト（TestForecastChange）
#        凍結fixtureを入力に、計算・文章・呼び方そのものを固定する。
#        fixture は「この入力ならこの出力になる」という単体テスト用データで、
#        本番の最新スナップショットとは無関係。日次更新に合わせて書き換えない。
#
#   B. 最新スナップショット整合テスト（TestForecastChangeOnLatestSnapshot）
#        本番の最新2世代を実装と同じルールで選び、期待値はスナップショットから
#        独立に計算して突き合わせる。金額・日付を直書きしない。
#        「▲51万円であること」ではなく「実際の差額を正しく▲◯万円と表示して
#        いること」を確かめる。
# ======================================================================
FC_FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "test_fixtures", "forecast_change")


def load_fc_fixture(name):
    """凍結fixture（本番 data/ とは独立。日次更新の影響を受けない）。"""
    import json
    with io.open(os.path.join(FC_FIXTURES, name), encoding="utf-8") as fh:
        return json.load(fh)


def man_candidates(v):
    """万円へ丸めた候補。ちょうど0.5万のときだけ2つ返す。

    丸め方の流儀（銀行丸め・四捨五入）に依存せず「正しく丸められているか」を
    見るための、実装とは独立した計算。
    """
    import math
    n = float(v) / 10000.0
    return sorted({int(math.floor(n + 0.5)), int(math.ceil(n - 0.5))})


def yen_man_candidates(v):
    return [f"{n:,}万円" for n in man_candidates(v)]


def yen_sman_candidates(v):
    out = []
    for n in man_candidates(v):
        out.append(f"▲{abs(n):,}万円" if n < 0 else
                   (f"+{n:,}万円" if n > 0 else "±0万円"))
    return out


def md_label(d):
    """2026-08-25 → 8/25。実装とは独立に組み立てる。"""
    return f"{int(str(d)[5:7])}/{int(str(d)[8:10])}"


# ======================================================================
class TestForecastChange(unittest.TestCase):
    """A. ロジック固定テスト（凍結fixture）。

    入力は test_fixtures/forecast_change/ の2世代で固定する。
    2026-08-24（21,030,192円）→ 2026-08-25 09:11 世代（20,449,283円）という
    実在した組み合わせをそのまま凍結したもので、「2026-08-25 の現在値」という
    意味ではない。日次更新で本番の値が動いてもこのテストは動かない。

    金額が閉じること（残差が丸め誤差だけ）と、
    「原因」と呼んでいないことを固定する。
    """

    @classmethod
    def setUpClass(cls):
        if not os.path.isdir(FC_FIXTURES):
            raise unittest.SkipTest("test_fixtures/forecast_change が無い")
        cls.prev = load_fc_fixture("prev_2026_08_24.json")
        cls.curr = load_fc_fixture("curr_2026_08_25.json")
        cls.fc = MR.build_forecast_change(cls.prev, cls.curr)

    def items(self, fc=None):
        """技術ブリッジの項目。経営画面には出さない内部監査用。"""
        return {i["key"]: i["yen"] for i in (fc or self.fc)["bridge"]["items"]}

    # ---- fixture が意図した組み合わせであること ----
    def test_fixture_is_the_frozen_pair(self):
        """fixture を取り違えたまま緑になることを防ぐ。"""
        self.assertEqual(self.prev["as_of_date"], "2026-08-24")
        self.assertEqual(self.curr["as_of_date"], "2026-08-25")
        self.assertEqual(self.prev["current_forecast_total"], 21_030_192)
        self.assertEqual(self.curr["current_forecast_total"], 20_449_283)

    # ---- 金額が閉じること ----
    def test_bridge_plus_residual_equal_the_diff(self):
        br = self.fc["bridge"]
        self.assertAlmostEqual(sum(i["yen"] for i in br["items"]) + br["residual"],
                               self.fc["diff"], places=6)

    def test_residual_is_only_rounding(self):
        self.assertLess(abs(self.fc["bridge"]["residual"]), 100,
                        f"残差が大きい: {self.fc['bridge']['residual']}")

    def test_diff_matches_the_snapshots(self):
        fc = self.fc
        self.assertEqual(fc["from_total"], self.prev["current_forecast_total"])
        self.assertEqual(fc["to_total"], self.curr["current_forecast_total"])
        self.assertAlmostEqual(fc["diff"], -580_909, places=6)

    def test_segments_sum_to_the_diff(self):
        seg = sum(s["diff"] for s in self.fc["segments"])
        self.assertLess(abs(seg - self.fc["diff"]), 100, f"区分別の合計: {seg}")

    # ---- fixture の実数（凍結入力に対する固定値）----
    def test_fixture_headline(self):
        fc = self.fc
        self.assertEqual(fc["label"], "8/24 → 8/25")
        self.assertEqual(MR.yen_man(fc["from_total"]), "2,103万円")
        self.assertEqual(MR.yen_man(fc["to_total"]), "2,045万円")
        self.assertEqual(MR.yen_sman(fc["diff"]), "▲58万円")
        self.assertEqual(fc["direction"], "下方修正")

    def test_fixture_items(self):
        it = self.items()
        want = {"new_confirmed": 45.3, "remaining_days": -92.8,
                "unrecorded": -19.1, "remaining_rate": 8.5, "visit_care": 0.0}
        for k, v in want.items():
            self.assertAlmostEqual(it[k] / 10000, v, delta=0.05, msg=k)

    def test_fixture_items_rounded_for_display(self):
        it = self.items()
        self.assertEqual(MR.yen_sman(it["new_confirmed"]), "+45万円")
        self.assertEqual(MR.yen_sman(it["remaining_days"]), "▲93万円")
        self.assertEqual(MR.yen_sman(it["unrecorded"]), "▲19万円")
        self.assertEqual(MR.yen_sman(it["remaining_rate"]), "+9万円")
        self.assertEqual(MR.yen_sman(it["visit_care"]), "±0万円")
        self.assertEqual(MR.yen_sman(self.fc["bridge"]["residual"]), "±0万円")

    def test_fixture_segments(self):
        seg = {s["label"]: s["diff"] for s in self.fc["segments"]}
        for lb, v in (("外来保険", -20.1), ("自費", -36.9), ("物販", -1.1),
                      ("訪問保険", 0.0), ("介護", 0.0)):
            self.assertAlmostEqual(seg[lb] / 10000, v, delta=0.05, msg=lb)

    def test_visit_and_care_month_end_forecast_did_not_move(self):
        """訪問保険・介護は確定へ振り替わっただけで月末見込みは動いていない。"""
        for k in ("visit_insurance_forecast", "care_forecast"):
            self.assertEqual(self.prev[k], self.curr[k], k)
        self.assertAlmostEqual(self.items()["visit_care"], 0.0, places=6)

    def test_days_label_names_the_pool_not_the_day(self):
        """『残り予測から外れた日』ではなく『残り予測対象の減少』と呼ぶ。"""
        lb = {i["key"]: i["label"]
              for i in self.fc["bridge"]["items"]}["remaining_days"]
        self.assertEqual(lb, "残り予測対象が1日減少")

    # ---- 呼び方（原因と言わない）----
    def test_never_called_a_cause(self):
        fc = self.fc
        text = " ".join([fc["title"], fc["subtitle"], fc["comment"],
                         fc["headline"], fc["short_note"]]
                        + [x["label"] for x in fc["segments"]])
        self.assertEqual(fc["title"], "予測変更の内訳")
        for bad in ("原因", "主因", "せい", "が理由"):
            self.assertNotIn(bad, text, f"原因として書いている: {bad}")

    def test_bucket_terms_never_reach_the_management_text(self):
        """バケット移動の語が、経営向けの文言に混ざらないこと。"""
        fc = self.fc
        mgmt_text = " ".join([fc["title"], fc["subtitle"], fc["comment"],
                              fc["headline"], fc["short_note"]]
                             + [x["label"] for x in fc["segments"]])
        for bad in ("残り予測対象", "バケット", "経過・売上未反映",
                    "1日あたり水準", "新たに確定した外来実績"):
            self.assertNotIn(bad, mgmt_text, bad)

    def test_bridge_declares_it_is_not_a_business_reason(self):
        br = self.fc["bridge"]
        self.assertIn("内部監査用", br["title"])
        self.assertIn("経営上の理由としては読まないでください", br["caution"])
        self.assertIn("売上の良し悪しを意味しません", br["caution"])
        days = {i["key"]: i for i in br["items"]}["remaining_days"]
        self.assertIn("日付が進めば必ず起きる移動", days["how"])

    def test_comment_does_not_claim_actuals_missed_the_forecast(self):
        c = self.fc["comment"]
        for bad in ("下回ったため", "予想を下回", "見込みを下回った",
                    "実績が想定", "主因"):
            self.assertNotIn(bad, c, f"証明できない因果: {bad}")

    def test_comment_is_segment_based(self):
        """経営向けの文は売上区分だけで組み立てる（バケット移動を入れない）。"""
        c = self.fc["comment"]
        self.assertEqual(
            c, "8/24から8/25にかけて月末着地見込みを58万円下方修正しました。"
               "内訳は、自費見込み▲37万円、外来保険見込み▲20万円、物販見込み▲1万円です。"
               "訪問保険と介護の月末見込みは変わっていません。")
        for bad in ("残り予測対象", "経過・売上未反映", "1日あたり水準", "新たに確定"):
            self.assertNotIn(bad, c, f"経営向けの文にバケット移動が混ざっている: {bad}")

    def test_headline_for_the_first_view(self):
        h = self.fc["headline"]
        self.assertEqual(
            h, "前回8/24予測から▲58万円下方修正。"
               "主な変化は自費見込み▲37万円、外来保険見込み▲20万円です。")
        for bad in ("実績が", "下回ったため", "残り予測対象"):
            self.assertNotIn(bad, h, bad)

    def test_segments_are_sorted_by_impact(self):
        d = [abs(x["diff"]) for x in self.fc["segments"]]
        self.assertEqual(d, sorted(d, reverse=True), self.fc["segments"])

    def test_note_says_the_days_are_not_the_same(self):
        n = self.fc["bridge"]["note"]
        self.assertIn("必ずしも同じ日ではありません", n)
        self.assertIn("予想対実績", n)

    def test_daily_and_month_end_are_not_treated_as_the_same_thing(self):
        """日次の予想対実績と、月末見込みの変更額を同一視しない。"""
        n = self.fc["bridge"]["note"]
        self.assertIn("特定日の『予想対実績』を示すものではありません", n)
        self.assertNotIn("予想対実績", self.fc["comment"])
        self.assertNotIn("予想対実績", self.fc["headline"])

    # ---- 足りないときは出さない ----
    def test_no_previous_snapshot(self):
        fc = MR.build_forecast_change(None, self.curr)
        self.assertFalse(fc["available"])
        self.assertEqual(fc["reason"], "no_previous")
        self.assertEqual(fc["segments"], [])
        self.assertEqual(fc["bridge"]["items"], [])

    def test_no_snapshot_at_all(self):
        fc = MR.build_forecast_change(None, None)
        self.assertFalse(fc["available"])
        self.assertEqual(fc["reason"], "no_snapshot")

    def test_old_snapshot_without_confirmed_detail(self):
        """confirmed_actual_detail を持たない世代では作らない（推定しない）。"""
        import copy
        old = copy.deepcopy(self.prev)
        old["forecast_composition"].pop("confirmed_actual_detail", None)
        fc = MR.build_forecast_change(old, self.curr)
        self.assertFalse(fc["available"])
        self.assertEqual(fc["reason"], "no_confirmed_detail")

    def test_missing_keys_are_not_guessed(self):
        import copy
        old = copy.deepcopy(self.prev)
        old.pop("remaining_forecast_total", None)
        fc = MR.build_forecast_change(old, self.curr)
        self.assertFalse(fc["available"])
        self.assertEqual(fc["reason"], "missing_keys")

    def test_identical_snapshots_show_no_change(self):
        fc = MR.build_forecast_change(self.curr, self.curr)
        self.assertTrue(fc["available"])
        self.assertAlmostEqual(fc["diff"], 0.0, places=6)
        self.assertEqual(fc["direction"], "横ばい")
        for i in fc["bridge"]["items"]:
            self.assertAlmostEqual(i["yen"], 0.0, places=6)

    # ---- 予測値そのものに触れていないこと ----
    def test_does_not_touch_forecast_values(self):
        import copy
        a, b = copy.deepcopy(self.prev), copy.deepcopy(self.curr)
        MR.build_forecast_change(a, b)
        self.assertEqual(a, self.prev)
        self.assertEqual(b, self.curr)


# ======================================================================
class TestForecastChangeOnLatestSnapshot(unittest.TestCase):
    """B. 最新スナップショット整合テスト。

    金額・日付は直書きしない。最新2世代のスナップショットから期待値を
    独立に計算し、実装の出力がそれと一致するかだけを見る。
    日次更新で値が変わってもテストは追随する。
    """

    DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

    @classmethod
    def setUpClass(cls):
        import json
        import re as _re
        if not os.path.isdir(cls.DATA):
            raise unittest.SkipTest("data/ が無い")
        months = sorted(d for d in os.listdir(cls.DATA)
                        if _re.fullmatch(r"\d{4}_\d{2}", d))
        rolls = []
        for m in reversed(months):                 # 新しい月から探す
            sd = os.path.join(cls.DATA, m, "snapshots")
            if not os.path.isdir(sd):
                continue
            got = []
            for n in sorted(os.listdir(sd)):       # 実装と同じ「名前順＝日付順」
                p = os.path.join(sd, n, "daily_rolling_forecast.json")
                if os.path.isfile(p):
                    with io.open(p, encoding="utf-8") as fh:
                        got.append(json.load(fh))
            if len(got) >= 2:
                rolls = got
                break
        if len(rolls) < 2:
            raise unittest.SkipTest("比較できるスナップショットが2世代そろっていない")
        cls.rolls = rolls
        cls.prev, cls.curr = rolls[-2], rolls[-1]
        cls.fc = MR.build_forecast_change(cls.prev, cls.curr)
        if not cls.fc.get("available"):
            raise unittest.SkipTest(f"内訳を作れない世代: {cls.fc.get('reason')}")

    # ---- どの2世代を見ているか ----
    def test_uses_the_latest_two_snapshots(self):
        self.assertEqual(self.fc["from_as_of"], self.prev["as_of_date"])
        self.assertEqual(self.fc["to_as_of"], self.curr["as_of_date"])
        self.assertLess(self.fc["from_as_of"], self.fc["to_as_of"])

    def test_label_is_built_from_the_snapshot_dates(self):
        """『8/24 → 8/25』を直書きせず、スナップショットの日付から組み立てる。"""
        want = (md_label(self.prev["as_of_date"]) + " → "
                + md_label(self.curr["as_of_date"]))
        self.assertEqual(self.fc["label"], want)

    # ---- 金額はスナップショットから独立計算 ----
    def test_totals_come_from_the_snapshots(self):
        self.assertEqual(self.fc["from_total"], self.prev["current_forecast_total"])
        self.assertEqual(self.fc["to_total"], self.curr["current_forecast_total"])

    def test_diff_is_the_difference_of_the_two_totals(self):
        want = (self.curr["current_forecast_total"]
                - self.prev["current_forecast_total"])
        self.assertAlmostEqual(self.fc["diff"], want, places=6)

    def test_direction_follows_the_sign_of_the_diff(self):
        d = self.fc["diff"]
        want = "下方修正" if d < 0 else ("上方修正" if d > 0 else "横ばい")
        self.assertEqual(self.fc["direction"], want)

    def test_each_segment_is_the_component_difference(self):
        got = {s["key"]: s for s in self.fc["segments"]}
        for key, label in MR.FC_SEGMENTS:
            want = self.curr[key] - self.prev[key]
            self.assertIn(key, got, key)
            self.assertEqual(got[key]["label"], label, key)
            self.assertAlmostEqual(got[key]["diff"], want, places=6, msg=key)
            self.assertAlmostEqual(got[key]["from"], self.prev[key], places=6)
            self.assertAlmostEqual(got[key]["to"], self.curr[key], places=6)

    def test_segments_sum_to_the_diff(self):
        seg = sum(s["diff"] for s in self.fc["segments"])
        self.assertLess(abs(seg - self.fc["diff"]), 100, f"区分別の合計: {seg}")

    def test_segments_are_sorted_by_impact(self):
        d = [abs(x["diff"]) for x in self.fc["segments"]]
        self.assertEqual(d, sorted(d, reverse=True))

    def test_new_confirmed_is_the_confirmed_detail_difference(self):
        """新たに確定した外来実績＝確定内訳（外来保険・自費・物販）の増分。"""
        want = sum(self.curr["forecast_composition"]["confirmed_actual_detail"][k]
                   - self.prev["forecast_composition"]["confirmed_actual_detail"][k]
                   for k in MR.FC_OP_KEYS)
        it = {i["key"]: i["yen"] for i in self.fc["bridge"]["items"]}
        self.assertAlmostEqual(it["new_confirmed"], want, places=6)

    def test_days_and_rate_split_reproduces_the_remaining_change(self):
        """日数の項＋水準の項＝残り予測の変化。実装とは別に組み直して確かめる。"""
        n0 = self.prev["remaining_days_count"]
        n1 = self.curr["remaining_days_count"]
        v0 = float(self.prev["remaining_forecast_total"])
        v1 = float(self.curr["remaining_forecast_total"])
        days_want = (v0 / n0 if n0 else 0.0) * (n1 - n0)
        it = {i["key"]: i["yen"] for i in self.fc["bridge"]["items"]}
        self.assertAlmostEqual(it["remaining_days"], days_want, places=6)
        self.assertAlmostEqual(it["remaining_days"] + it["remaining_rate"],
                               v1 - v0, places=6)

    def test_bridge_plus_residual_equal_the_diff(self):
        br = self.fc["bridge"]
        self.assertAlmostEqual(sum(i["yen"] for i in br["items"]) + br["residual"],
                               self.fc["diff"], places=6)

    def test_residual_is_only_rounding(self):
        self.assertLess(abs(self.fc["bridge"]["residual"]), 100,
                        f"残差が大きい: {self.fc['bridge']['residual']}")

    def test_closes_for_every_consecutive_transition(self):
        """最新2世代だけでなく、その月の全ての連続する2世代で閉じること。"""
        checked = 0
        for a, b in zip(self.rolls, self.rolls[1:]):
            fc = MR.build_forecast_change(a, b)
            if not fc["available"]:
                continue                      # 導入前の世代は対象外（推定しない）
            checked += 1
            self.assertAlmostEqual(
                fc["diff"], b["current_forecast_total"] - a["current_forecast_total"],
                places=6, msg=fc["label"])
            self.assertLess(abs(fc["bridge"]["residual"]), 100,
                            f"{fc['label']} の残差: {fc['bridge']['residual']}")
        self.assertGreaterEqual(checked, 1, "検査できた遷移が無い")

    # ---- 表示の丸め ----
    def test_displayed_amounts_are_correctly_rounded(self):
        """実装の丸め関数ではなく、元データから独立に丸めた候補と突き合わせる。"""
        self.assertIn(MR.yen_man(self.fc["from_total"]),
                      yen_man_candidates(self.prev["current_forecast_total"]))
        self.assertIn(MR.yen_man(self.fc["to_total"]),
                      yen_man_candidates(self.curr["current_forecast_total"]))
        self.assertIn(MR.yen_sman(self.fc["diff"]),
                      yen_sman_candidates(self.curr["current_forecast_total"]
                                          - self.prev["current_forecast_total"]))

    def test_headline_shows_the_rounded_diff_of_the_snapshots(self):
        """『▲◯万円』の◯が、実際のスナップショット間の差から来ていること。"""
        h = self.fc["headline"]
        d = self.curr["current_forecast_total"] - self.prev["current_forecast_total"]
        self.assertTrue(any(s.lstrip("+") in h for s in yen_sman_candidates(d)),
                        f"差額が見出しに出ていない: {h}")
        self.assertIn(md_label(self.prev["as_of_date"]), h)
        self.assertIn(self.fc["direction"], h)

    def test_comment_shows_the_rounded_diff_and_the_moving_segments(self):
        c = self.fc["comment"]
        d = self.curr["current_forecast_total"] - self.prev["current_forecast_total"]
        self.assertTrue(any(str(abs(n)) in c for n in man_candidates(d)),
                        f"差額がコメントに出ていない: {c}")
        for s in self.fc["segments"]:
            if round(abs(s["diff"]) / 10000) == 0:
                continue                       # 万円未満は文に出さない
            self.assertIn(MR.FC_SEG_IN_TEXT[s["label"]], c, s["label"])

    # ---- 呼び方は最新データでも変わらない ----
    def test_never_called_a_cause_on_the_latest_data(self):
        fc = self.fc
        text = " ".join([fc["title"], fc["subtitle"], fc["comment"],
                         fc["headline"], fc["short_note"]])
        for bad in ("原因", "主因", "せい", "が理由"):
            self.assertNotIn(bad, text, bad)

    def test_does_not_touch_forecast_values(self):
        import copy
        a, b = copy.deepcopy(self.prev), copy.deepcopy(self.curr)
        MR.build_forecast_change(a, b)
        self.assertEqual(a, self.prev)
        self.assertEqual(b, self.curr)


# ======================================================================
class TestForecastChangeInApp(unittest.TestCase):
    """画面側に予測変更ブロックがつながっていること。"""

    def _src(self):
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "streamlit_app.py")
        with io.open(p, encoding="utf-8") as fh:
            return fh.read()

    def _fc_body(self):
        src = self._src()
        return src[src.index("def _render_forecast_change(fc, month, snaps, i):"):
                   src.index("def _render_forecast_change_history(")]

    def test_block_is_rendered_under_the_chart(self):
        src = self._src()
        self.assertIn("def _render_forecast_change(fc, month, snaps, i):", src)
        self.assertIn("_render_forecast_change(_fc, month, _fc_snaps, _fc_i)", src)
        # グラフ（凡例）の直後に呼ばれていること
        self.assertLess(src.index("mfc-clegend"),
                        src.index("    _render_forecast_change(_fc, month,"))

    def test_history_is_in_an_expander(self):
        src = self._src()
        self.assertIn("過去の予測変更を見る", src)
        self.assertIn("def _render_forecast_change_history(", src)

    def test_bridge_is_in_its_own_expander(self):
        """バケット移動は内部監査用の折りたたみへ隔離する。"""
        src = self._src()
        self.assertIn("def _render_forecast_change_bridge(fc):", src)
        # 常時表示の本体からはバケットの語が消えていること
        body = self._fc_body()
        for bad in ("残り予測対象", "経過・売上未反映", "1日あたり水準",
                    "新たに確定した外来実績", "説明できない残差"):
            self.assertNotIn(bad, body, f"常時表示にバケット移動が残っている: {bad}")

    def test_main_view_is_segment_based(self):
        src = self._src()
        self.assertIn("def _fc_segment_table(fc):", src)
        self.assertIn('_fc_segment_table(fc)', self._fc_body())

    def test_headline_is_added_to_the_first_view(self):
        src = self._src()
        self.assertIn("_fc['headline']", src)
        # 今日の結論のブロック内で使われていること
        self.assertLess(src.index("今日の結論と論点") - 2000,
                        src.index("_fc['headline']"))

    def test_app_does_not_recompute_the_breakdown(self):
        """内訳の計算は mgmt_report 側だけ（定義を2か所に置かない）。"""
        src = self._src()
        s = src.index("def _render_forecast_change(fc, month, snaps, i):")
        e = src.index("def _render_actions(rep):")
        body = src[s:e]
        for token in ("remaining_forecast_total", "elapsed_unrecorded_total",
                      "confirmed_actual_detail", "remaining_days_count"):
            self.assertNotIn(token, body, token)

    def test_app_does_not_say_cause(self):
        src = self._src()
        s = src.index("def _render_forecast_change(fc, month, snaps, i):")
        e = src.index("def _render_actions(rep):")
        body = src[s:e]
        for bad in ("下方修正の主因", "原因は", "主因"):
            self.assertNotIn(bad, body, bad)


# ======================================================================
class TestDailyBreakdownInSnapshot(unittest.TestCase):
    """スナップショットに入れた日別内訳が、既存の合計と1円もずれないこと。

    日別を足し戻して月末予測にならないなら、画面に出す意味がない。
    ここは丸め前の値で検算する。
    """

    @classmethod
    def setUpClass(cls):
        import json
        here = os.path.dirname(os.path.abspath(__file__))
        p = os.path.join(os.path.dirname(here), "outputs",
                         "daily_rolling_forecast.json")
        if not os.path.isfile(p):
            raise unittest.SkipTest("outputs/daily_rolling_forecast.json が無い")
        with io.open(p, encoding="utf-8") as fh:
            cls.roll = json.load(fh)
        if cls.roll.get("daily_expected") is None:
            raise unittest.SkipTest("daily_expected を持たない世代")

    def _sum(self, rows, key):
        return sum(r[key] for r in rows)

    def _exp(self, status):
        return [r for r in self.roll["daily_expected"] if r["status"] == status]

    # ---- 4. 日別実績の突合（必須テスト）----
    def test_daily_actual_sums_to_the_existing_total_to_the_yen(self):
        """日別actualの月内合計＝既存の確定外来3区分。1円単位で一致すること。"""
        got = self._sum(self.roll["daily_actual"], "total")
        self.assertEqual(round(got), self.roll["actual_to_date_total"])
        self.assertLess(abs(got - self.roll["actual_to_date_total"]), 1e-6,
                        f"1円未満のずれも許さない: {got}")

    def test_daily_actual_segments_sum_to_the_confirmed_detail(self):
        conf = self.roll["forecast_composition"]["confirmed_actual_detail"]
        for key, comp in (("outpatient_insurance", "gairai"),
                          ("selfpay", "jihi"), ("product", "buppin")):
            got = self._sum(self.roll["daily_actual"], key)
            self.assertEqual(round(got), conf[comp], key)

    def test_daily_actual_row_total_is_the_sum_of_three(self):
        for r in self.roll["daily_actual"]:
            self.assertAlmostEqual(
                r["total"],
                r["outpatient_insurance"] + r["selfpay"] + r["product"],
                places=6, msg=r["date"])

    def test_daily_actual_stops_at_actual_data_through(self):
        last = max(r["date"] for r in self.roll["daily_actual"])
        self.assertLessEqual(last, self.roll["actual_data_through"])

    # ---- 1. 未丸め合計が既存キーと一致 ----
    def test_remaining_sums_to_remaining_forecast_total(self):
        got = self._sum(self._exp("remaining"), "total")
        self.assertEqual(round(got), self.roll["remaining_forecast_total"])
        # 丸め前の差は yen() の丸め分（1円未満）だけ
        self.assertLess(abs(got - self.roll["remaining_forecast_total"]), 1.0)

    def test_elapsed_sums_to_elapsed_unrecorded_total(self):
        got = self._sum(self._exp("elapsed_unrecorded"), "total")
        self.assertEqual(round(got), self.roll["elapsed_unrecorded_total"])
        self.assertLess(abs(got - self.roll["elapsed_unrecorded_total"]), 1.0)

    def test_values_are_not_pre_rounded(self):
        """丸めてから足すと残差が出るので、保存側は丸めない。"""
        vals = [r["total"] for r in self.roll["daily_expected"]]
        self.assertTrue(any(abs(v - round(v)) > 1e-9 for v in vals),
                        "日別予測が整数に丸められている（合計がずれる原因）")

    def test_expected_row_total_is_the_sum_of_three(self):
        for r in self.roll["daily_expected"]:
            self.assertAlmostEqual(
                r["total"],
                r["outpatient_insurance"] + r["selfpay"] + r["product"],
                places=6, msg=r["date"])

    # ---- 2. status の意味 ----
    def test_remaining_is_always_after_as_of(self):
        for r in self._exp("remaining"):
            self.assertGreater(r["date"], self.roll["as_of_date"], r["date"])

    def test_elapsed_is_never_after_as_of(self):
        for r in self._exp("elapsed_unrecorded"):
            self.assertLessEqual(r["date"], self.roll["as_of_date"], r["date"])

    def test_only_two_statuses(self):
        """status はこの2つ以外を作らない。

        休診日が正しく除外された月は elapsed_unrecorded が0件になる（それが正常）。
        両方そろっていることを要求すると、データが健全な月ほど落ちる。
        """
        got = {r["status"] for r in self.roll["daily_expected"]}
        self.assertTrue(got <= {"remaining", "elapsed_unrecorded"}, got)
        self.assertTrue(got, "daily_expected が空")

    # ---- 9. 公開範囲 ----
    def test_rows_carry_no_patient_information(self):
        allowed_exp = {"date", "status", "outpatient_insurance", "selfpay",
                       "product", "total"}
        allowed_act = allowed_exp - {"status"}
        for r in self.roll["daily_expected"]:
            self.assertEqual(set(r), allowed_exp, r)
        for r in self.roll["daily_actual"]:
            self.assertEqual(set(r), allowed_act, r)

    def test_no_visit_or_care_in_daily_rows(self):
        """訪問保険・介護は日別モデルを持たないので入れない。"""
        for r in self.roll["daily_expected"] + self.roll["daily_actual"]:
            for k in r:
                self.assertNotIn(k, ("visit_insurance", "homon", "care", "kaigo"))


# ======================================================================
class TestDailyVsExpected(unittest.TestCase):
    """事前予測 vs 実績。基準時点の取り方を固定する。"""

    def roll(self, as_of, expected=None, actual=None):
        r = {"as_of_date": as_of, "target_month": "2026-08"}
        if expected is not None:
            r["daily_expected"] = expected
        if actual is not None:
            r["daily_actual"] = actual
        return r

    def exp(self, date, status, gi, jh, bp):
        return {"date": date, "status": status, "outpatient_insurance": gi,
                "selfpay": jh, "product": bp, "total": gi + jh + bp}

    def act(self, date, gi, jh, bp):
        return {"date": date, "outpatient_insurance": gi, "selfpay": jh,
                "product": bp, "total": gi + jh + bp}

    # ---- 基準時点の選び方 ----
    def test_uses_the_last_snapshot_where_the_day_was_remaining(self):
        """Dがremainingだった最後のsnapshot＝as_ofが最大のものを使う。"""
        snaps = [
            self.roll("2026-08-23", [self.exp("2026-08-26", "remaining",
                                              100, 100, 10)]),
            self.roll("2026-08-25", [self.exp("2026-08-26", "remaining",
                                              500, 300, 20)]),
            self.roll("2026-08-27", actual=[self.act("2026-08-26", 400, 200, 30)]),
        ]
        r = MR.build_daily_vs_expected(snaps)
        self.assertTrue(r["available"])
        d = r["latest"]
        self.assertEqual(d["expected_from"], "2026-08-25")
        seg = {s["key"]: s for s in d["segments"]}
        self.assertEqual(seg["outpatient_insurance"]["expected"], 500)
        self.assertEqual(seg["outpatient_insurance"]["actual"], 400)
        self.assertEqual(seg["outpatient_insurance"]["diff"], -100)

    def test_elapsed_unrecorded_is_never_used_as_the_prior_forecast(self):
        """診療日が終わった後の見込みは事前予測にしない。"""
        snaps = [
            self.roll("2026-08-25", [self.exp("2026-08-26", "remaining",
                                              500, 300, 20)]),
            # 8/26 が終わったあとの実績反映待ちの見込み（使ってはいけない）
            self.roll("2026-08-26", [self.exp("2026-08-26", "elapsed_unrecorded",
                                              410, 210, 31)]),
            self.roll("2026-08-27", actual=[self.act("2026-08-26", 400, 200, 30)]),
        ]
        r = MR.build_daily_vs_expected(snaps)
        d = r["latest"]
        self.assertEqual(d["expected_from"], "2026-08-25")
        seg = {s["key"]: s for s in d["segments"]}
        self.assertEqual(seg["total"]["expected"], 820)      # 500+300+20
        self.assertNotEqual(seg["total"]["expected"], 651)   # elapsed のほうではない

    def test_no_history_is_not_fabricated(self):
        """当時保存が無い日は行を作らない（曜日平均で作り直さない）。"""
        snaps = [self.roll("2026-08-27",
                           actual=[self.act("2026-08-26", 400, 200, 30)])]
        r = MR.build_daily_vs_expected(snaps)
        self.assertFalse(r["available"])
        self.assertEqual(r["reason"], "no_expected_history")
        self.assertEqual(r["days"], [])
        self.assertIn("2026-08-26", r["no_history_dates"])

    def test_days_without_actual_are_not_shown(self):
        """まだ確定していない日は予想対実績にしない。"""
        snaps = [
            self.roll("2026-08-25", [self.exp("2026-08-31", "remaining",
                                              500, 300, 20)]),
            self.roll("2026-08-27", actual=[]),
        ]
        r = MR.build_daily_vs_expected(snaps)
        self.assertFalse(r["available"])
        self.assertEqual(r["reason"], "no_daily_actual")

    def test_old_snapshots_without_the_keys_do_not_crash(self):
        snaps = [{"as_of_date": "2026-08-21"}, {"as_of_date": "2026-08-22"}]
        r = MR.build_daily_vs_expected(snaps)
        self.assertFalse(r["available"])
        self.assertEqual(r["reason"], "no_daily_actual")

    def test_empty_input(self):
        r = MR.build_daily_vs_expected([])
        self.assertFalse(r["available"])
        self.assertEqual(r["reason"], "no_snapshot")

    # ---- 表示内容 ----
    def test_segments_and_total(self):
        snaps = [
            self.roll("2026-08-25", [self.exp("2026-08-26", "remaining",
                                              550_000, 300_000, 11_000)]),
            self.roll("2026-08-27",
                      actual=[self.act("2026-08-26", 512_000, 118_000, 9_800)]),
        ]
        d = MR.build_daily_vs_expected(snaps)["latest"]
        self.assertEqual([s["label"] for s in d["segments"]],
                         ["外来保険", "自費", "物販", "合計"])
        seg = {s["label"]: s for s in d["segments"]}
        self.assertEqual(seg["自費"]["diff"], -182_000)
        self.assertEqual(seg["合計"]["expected"], 861_000)
        self.assertEqual(seg["合計"]["actual"], 639_800)
        self.assertEqual(d["diff"], 639_800 - 861_000)

    def test_headline_may_say_above_or_below_expectation(self):
        """正式な比較ができたときだけ『予想を下回った』と言ってよい。"""
        snaps = [
            self.roll("2026-08-25", [self.exp("2026-08-26", "remaining",
                                              550_000, 300_000, 11_000)]),
            self.roll("2026-08-27",
                      actual=[self.act("2026-08-26", 512_000, 118_000, 9_800)]),
        ]
        h = MR.build_daily_vs_expected(snaps)["headline"]
        self.assertIn("8/26", h)
        self.assertIn("事前予測を", h)
        self.assertIn("下回りました", h)
        self.assertIn("自費", h)

    def test_headline_says_above_when_actual_is_higher(self):
        snaps = [
            self.roll("2026-08-25", [self.exp("2026-08-26", "remaining",
                                              400_000, 100_000, 5_000)]),
            self.roll("2026-08-27",
                      actual=[self.act("2026-08-26", 512_000, 118_000, 9_800)]),
        ]
        self.assertIn("上回りました",
                      MR.build_daily_vs_expected(snaps)["headline"])

    def test_most_recent_day_comes_first(self):
        snaps = [
            self.roll("2026-08-24", [self.exp("2026-08-25", "remaining",
                                              100, 100, 10)]),
            self.roll("2026-08-25", [self.exp("2026-08-26", "remaining",
                                              200, 200, 20)]),
            self.roll("2026-08-27", actual=[self.act("2026-08-25", 90, 90, 9),
                                            self.act("2026-08-26", 180, 180, 18)]),
        ]
        r = MR.build_daily_vs_expected(snaps)
        self.assertEqual([d["date"] for d in r["days"]],
                         ["2026-08-26", "2026-08-25"])

    # ---- 6. 月末予測変更と混同しない ----
    def test_is_a_separate_result_from_the_forecast_change(self):
        """予想対実績と、月末見込みの変更額を同じキーに入れない。"""
        self.assertTrue(hasattr(MR, "build_daily_vs_expected"))
        self.assertTrue(hasattr(MR, "build_forecast_change"))
        snaps = [
            self.roll("2026-08-25", [self.exp("2026-08-26", "remaining",
                                              500, 300, 20)]),
            self.roll("2026-08-27", actual=[self.act("2026-08-26", 400, 200, 30)]),
        ]
        r = MR.build_daily_vs_expected(snaps)
        # 予測変更（4.6）側のキーを持ち込まない
        for k in ("items", "bridge", "comment", "from_total", "to_total"):
            self.assertNotIn(k, r, f"予測変更側のキーが混ざっている: {k}")
        # 逆に、予測変更側は日別の比較キーを持たない
        fc = MR.build_forecast_change(
            {"as_of_date": "2026-08-24"}, {"as_of_date": "2026-08-25"})
        for k in ("days", "latest", "no_history_dates"):
            self.assertNotIn(k, fc, f"予想対実績側のキーが混ざっている: {k}")

    def test_note_separates_it_from_the_month_end_change(self):
        self.assertIn("月末着地見込みの変更額は別のもの", MR.DVE_NOTE)
        self.assertIn("elapsed_unrecorded", MR.DVE_NOTE)
        self.assertIn("残り予測に入っていた最後のスナップショット", MR.DVE_NOTE)


# ======================================================================
class TestDailyVsExpectedInApp(unittest.TestCase):
    """画面側に予想対実績がつながっていること。"""

    def _src(self):
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "streamlit_app.py")
        with io.open(p, encoding="utf-8") as fh:
            return fh.read()

    def test_block_exists_and_is_separate(self):
        src = self._src()
        self.assertIn("def _render_daily_vs_expected(dve):", src)
        self.assertIn("_render_daily_vs_expected(_dve)", src)
        # 予測変更ブロックの直後（別ブロック）に置かれていること
        self.assertLess(src.index("_render_forecast_change(_fc, month,"),
                        src.index("_render_daily_vs_expected(_dve)"))

    def test_headline_only_when_available(self):
        src = self._src()
        self.assertIn("if _dve:", src)
        self.assertIn("_dve['headline']", src)

    def test_app_does_not_recompute_the_comparison(self):
        src = self._src()
        s = src.index("def _render_daily_vs_expected(dve):")
        e = src.index("def _render_actions(rep):")
        body = src[s:e]
        for token in ("daily_expected", "daily_actual", "elapsed_unrecorded"):
            self.assertNotIn(token, body, token)


if __name__ == "__main__":
    unittest.main(verbosity=2)
