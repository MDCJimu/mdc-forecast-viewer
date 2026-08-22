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
              care_revision="2026-06"):
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
        "actual_to_date_total": actual_to_date,
        "remaining_forecast_total": remaining_forecast,
        "reservation_visible_remaining_as_of": 452,
        "reservation_projected_final_remaining": 496,
        "resec_data_status": "反映済み",
        "actual_data_through": "2026-08-21",
        "care_component": {"care_revision_month": care_revision,
                           "care_data_insufficient": True},
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


PREV_ROW = {
    "年月": "2025-08", "診療日数": "23", "月間総売上": "21805410",
    "保険診療売上": "13393890", "自費診療売上": "8131750", "物販売上": "279770",
    "外来保険売上": "11057460", "訪問保険売上": "1359740", "介護売上": "976690",
    "総患者数": "891", "総来院回数": "1439", "初診件数": "37",
}

PREV_FC = {"as_of_date": "2026-08-21", "current_forecast_total": "21878649",
           "insurance_forecast": "15132014", "selfpay_forecast": "6429462"}


def build(roll, prev_row=PREV_ROW, prev_fc=PREV_FC):
    return MR.build_management_report(roll, prev_row, prev_fc)


def all_text(rep):
    """画面に出る文章をすべて連結して返す（禁止語・矛盾のチェック用）。"""
    parts = list(rep["conclusion"])
    parts.append(rep["cause"]["text"])
    parts.append(rep["capacity"]["text"])
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
        self.assertIn("主因", t)
        self.assertIn("+172万円", t)     # 保険は上回っていると明示される
        self.assertIn("▲212万円", t)
        # 稼働が落ちているとは書かない（来院・患者・初診はすべて前年超のため）
        self.assertNotIn("稼働そのものが弱まって", all_text(rep))
        # 件数はすべて月末見込み。実績確定値のように書かない。
        self.assertIn("月末見込みでは", " ".join(rep["conclusion"]))
        self.assertEqual(action_headlines(rep)[0][:2], "自費")

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

    def test_absorption_is_mentioned_when_density_is_up(self):
        """保険↑・1日あたり↑なら「他の曜日で吸収できている可能性」まで書く。"""
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770,
                              baseline=22_386_557))
        self.assertTrue(rep["structure"]["absorbed"])
        self.assertIn("吸収できている可能性", rep["structure"]["text"])

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
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770))
        t = rep["selfpay"]["text"]
        self.assertIn("すでに計上されている自費", t)
        self.assertIn("月末までに見込んでいる残り", t)
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
        for i in range(len(rep["actions"]) - 1):
            a, b = rep["actions"][i], rep["actions"][i + 1]
            if a["tier"] == b["tier"]:
                self.assertGreaterEqual(a["impact"], b["impact"])

    def test_biggest_contributor_comes_first(self):
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770))
        self.assertEqual(rep["actions"][0]["tier"], MR.T_DRIVER)
        self.assertIn("自費", rep["actions"][0]["headline"])

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

    def test_low_priority_action_is_dropped_when_bigger_issues_exist(self):
        """細かい問題を5件並べず、経営インパクトの大きいものを残す。"""
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770,
                              cancel_rate=19.0, cancel_rate_prev=15.7))
        self.assertEqual(len(rep["actions"]), MR.MAX_ACTIONS)
        self.assertTrue(all(a["tier"] <= MR.T_STRUCTURE for a in rep["actions"]))
        self.assertFalse(any("キャンセル率の上昇" in h for h in action_headlines(rep)))


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
        self.assertIn("21日", rep["capacity"]["text"])

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
        self.assertIn("診療日数を前年と比べられるデータがありません",
                      rep["capacity"]["text"])
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
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770))
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
            if any(k in sent for k in ("来院回数", "1診療日あたり", "1来院あたり", "診療日数")):
                self.assertTrue(any(k in sent for k in ("見込み", "計算です", "実績のある日数")),
                                f"予測値が断定形: {sent}")
        # 結論でも件数は見込みと分かる形
        concl = " ".join(rep["conclusion"])
        if "来院回数" in concl:
            self.assertIn("月末見込みでは", concl)
        # 稼働表：今月側が見込みか実績かを行ごとに持っている
        for r in rep["capacity"]["rows"]:
            self.assertIn(r.get("kind"), ("見込み", "実績"), r["name"])
        kinds = {r["name"]: r["kind"] for r in rep["capacity"]["rows"]}
        self.assertEqual(kinds.get("キャンセル率"), "実績")
        self.assertEqual(kinds.get("来院回数"), "見込み")

    def test_percent_sign_matches_amount_sign(self):
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770))
        for r in rep["cause"]["rows"]:
            if r["diff"] < 0:
                self.assertLess(r["rate"], 0, r["name"])
            elif r["diff"] > 0:
                self.assertGreater(r["rate"], 0, r["name"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
