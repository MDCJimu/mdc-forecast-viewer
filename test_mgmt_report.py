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
              care_revision="2026-06",
              obs_days=13, obs_total=10_912_740, obs_outp=7_727_810,
              obs_jihi=2_981_000, obs_buppin=203_930,
              obs_prev_total=11_878_440, obs_prev_rate=-8.1,
              pyd_days=15, pyd_outp=7_264_860, pyd_jihi=5_585_250, pyd_buppin=185_990):
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
        "progress_through_yesterday": {
            "current_cutoff": "2026-08-21", "prev_year_cutoff": "2025-08-21",
            "current": {"total": obs_total, "insurance_outpatient": obs_outp,
                        "selfpay": obs_jihi, "product": obs_buppin,
                        "clinic_days": obs_days},
            "prev_year_same_day": {"total": 13_036_100, "insurance_outpatient": pyd_outp,
                                   "selfpay": pyd_jihi, "product": pyd_buppin,
                                   "clinic_days": pyd_days},
            "prev_year_same_bizdays": {"total": obs_prev_total, "clinic_days": obs_days,
                                       "diff_vs_current": obs_total - obs_prev_total,
                                       "rate": obs_prev_rate},
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


def hist_rows(selfpay=None, per_day_trend=None):
    """直近12か月の月次実績。年月・区分・診療日数だけを持つ最小形。"""
    base = [
        ("2025-08", 21805410, 13393890, 8131750, 279770, 23),
        ("2025-09", 19752670, 13693510, 5869820, 189340, 24),
        ("2025-10", 18072000, 14510000, 3320000, 242000, 26),
        ("2025-11", 20380000, 13930000, 6250000, 190000, 23),
        ("2025-12", 19320000, 14920000, 4140000, 260000, 24),
        ("2026-01", 20460000, 14070000, 6150000, 250000, 23),
        ("2026-02", 20560000, 12490000, 7780000, 290000, 22),
        ("2026-03", 23230000, 14580000, 8300000, 350000, 25),
        ("2026-04", 22700000, 13220000, 9250000, 220000, 26),
        ("2026-05", 19080000, 13420000, 5460000, 200000, 24),
        ("2026-06", 20221040, 14963140, 5019300, 238600, 26),
        ("2026-07", 20303270, 14481250, 5577000, 245020, 27),
    ]
    rows = []
    for i, (ym, tot, hok, jih, bup, days) in enumerate(base):
        if selfpay is not None:
            jih = selfpay[i]
        if per_day_trend is not None:
            tot, days = per_day_trend[i]
        rows.append({"年月": ym, "月間総売上": tot, "保険診療売上": hok,
                     "自費診療売上": jih, "物販売上": bup, "診療日数": days,
                     "外来保険売上": hok - 1_400_000 - 600_000,
                     "訪問保険売上": 1_400_000, "介護売上": 600_000})
    return rows


PREV_ROW = {
    "年月": "2025-08", "診療日数": "23", "月間総売上": "21805410",
    "保険診療売上": "13393890", "自費診療売上": "8131750", "物販売上": "279770",
    "外来保険売上": "11057460", "訪問保険売上": "1359740", "介護売上": "976690",
    "総患者数": "891", "総来院回数": "1439", "初診件数": "37",
}

PREV_FC = {"as_of_date": "2026-08-21", "current_forecast_total": "21878649",
           "insurance_forecast": "15132014", "selfpay_forecast": "6429462"}


def build(roll, prev_row=PREV_ROW, prev_fc=PREV_FC, hist=None):
    return MR.build_management_report(roll, prev_row, prev_fc,
                                      hist_rows() if hist is None else hist)


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

    def test_absorption_only_when_observed_total_holds(self):
        """吸収したと言えるのは、実測の総額が前年に負けていないときだけ。"""
        # 実測が前年割れ（-8.1%）→ 外来保険が伸びていても「吸収」とは言わない
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770,
                              baseline=22_386_557))
        self.assertFalse(rep["structure"]["absorbed"])
        self.assertIn("観測されている範囲では", rep["structure"]["text"])
        self.assertIn("吸収できているとまでは言えません", rep["structure"]["text"])
        # 実測が前年並み以上 → 吸収できている
        ok = build(make_roll(15_113_808, 6_010_211, 316_528,
                             13_393_890, 8_131_750, 279_770,
                             baseline=22_386_557,
                             obs_prev_total=10_000_000, obs_prev_rate=9.1))
        self.assertTrue(ok["structure"]["absorbed"])
        self.assertIn("埋められている状態です", ok["structure"]["text"])

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
        # 実データでは、金額の大きい自費(関連差額212万)より
        # 金額の小さい必要ペース(着地リスク57万)が上に来る
        names = action_headlines(rep)
        self.assertLess(next(i for i, h in enumerate(names) if "必要なペース" in h),
                        next(i for i, h in enumerate(names) if "水準で確認" in h))

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
        self.assertEqual(top["confidence"], 1)     # 実測から言える
        self.assertIn("必要なペース", top["headline"])
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
        self.assertIn("今月の外来診療予定日は", rep["capacity"]["text"])
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
                    or "今月の外来診療予定日は" in sent
                    or "前年の日数は" in sent
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
            if k.startswith("今月の内訳"):
                # 前年と比較しない情報行。差も前年も出さない。
                self.assertEqual(r["prev"], "—", r["name"])
                self.assertEqual(r["diff"], "—", r["name"])
                continue
            self.assertTrue(k.startswith("実績") or k.startswith("月末見込み"), r["name"])
            self.assertIn("前年", k, r["name"])
        kinds = {r["name"]: r["kind"] for r in rep["capacity"]["rows"]}
        self.assertTrue(kinds.get("キャンセル率", "").startswith("実績"))
        self.assertTrue(kinds.get("来院回数", "").startswith("月末見込み"))

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
        self.assertTrue(t.startswith("実績で見ると"), t[:30])
        self.assertIn("-8.1%", t)
        self.assertIn("月末見込みでは", t)
        # 見込みが上振れ前提を含むことを明示する
        self.assertIn("前提を含んだ数字", t)
        self.assertIn("実績がこの水準に達しているわけではありません", t)

    def test_observed_rows_are_labelled(self):
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770))
        kinds = {r["name"]: r["kind"] for r in rep["capacity"]["rows"]}
        # どの前年と比べた数字なのかが、区分の表記だけで読めること
        self.assertEqual(kinds["外来診療日あたり売上（実績・外来保険＋自費＋物販）"],
                         "実績／前年は同じ日数まで累計")
        self.assertEqual(kinds["うち自費（実績・1日あたり）"],
                         "実績／前年は暦の同じ日まで累計")
        self.assertEqual(kinds["外来診療日あたり売上（外来保険＋自費＋物販）"],
                         "月末見込み／前年は月末実績")

    def test_structure_never_calls_forecast_observed(self):
        """予測値を「実際には」と書かない（A-3）。"""
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770,
                              baseline=22_386_557))
        t = rep["structure"]["text"]
        self.assertNotIn("実際には", t)
        self.assertIn("観測されている範囲では", t)


# ======================================================================
class TestProductivityTrend(unittest.TestCase):
    """A-6: 1診療日あたり生産性の連続トレンド。"""

    DOWN = [(21805410, 23), (19752670, 24), (18072000, 26), (20380000, 23),
            (19320000, 24), (20460000, 23), (20560000, 22), (23230000, 25),
            (22700000, 26), (19080000, 24), (20221040, 26), (20303270, 27)]

    def test_trend_is_suppressed_while_thursday_is_closed(self):
        """木曜休診中は分母の中身が変わるため、トレンド判定を出さない。"""
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770,
                              thursday_closed=True),
                    hist=hist_rows(per_day_trend=self.DOWN))
        tr = rep["trend"]
        self.assertTrue(tr["suppressed"])
        self.assertIn("判定を出していません", tr["text"])
        self.assertIn("訪問・介護だけ売上が立つ木曜", tr["text"])
        # 抑止中は打ち手も作らない
        self.assertFalse(any("生産性" in a["headline"]
                             for a in rep["next_month_actions"]))
        # 本番に出ていた文言が復活していないこと
        self.assertNotIn("6か月続けて低下", all_text(rep))
        self.assertNotIn("6か月続けて低下", tr["text"])

    def test_detects_decline_when_basis_is_stable(self):
        """木曜休診が無い月なら、同じ数え方のままなので判定を出す。"""
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770,
                              thursday_closed=False),
                    hist=hist_rows(per_day_trend=self.DOWN))
        tr = rep["trend"]
        self.assertIsNotNone(tr)
        self.assertFalse(tr.get("suppressed"))
        self.assertEqual(tr["direction"], -1)
        self.assertIn("売上発生日あたりの総売上", tr["text"])
        self.assertIn(f"{tr['months']}か月続けて低下", tr["text"])
        self.assertTrue(any("生産性" in a["headline"]
                            for a in rep["next_month_actions"]))

    def test_no_trend_when_not_monotonic(self):
        flat = [(20000000, 25)] * 12
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770,
                              thursday_closed=False),
                    hist=hist_rows(per_day_trend=flat))
        self.assertIsNone(rep["trend"])

    def test_no_trend_without_history(self):
        rep = build(make_roll(15_113_808, 6_010_211, 316_528,
                              13_393_890, 8_131_750, 279_770,
                              thursday_closed=False), hist=[])
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
        self.assertAlmostEqual(f["per_day_now"], want / f["days_month"], places=6)
        # 訪問＋介護を足した額では割っていない
        allrev = want + roll["visit_insurance_forecast"] + roll["care_forecast"]
        self.assertNotAlmostEqual(f["per_day_now"], allrev / f["days_month"], places=0)
        self.assertEqual(f["per_day_basis_now"], MR.BASIS_OUTPATIENT)

    def test_total_revenue_is_never_divided_by_outpatient_days(self):
        """全売上 ÷ 外来診療日数 という混ざった値を作らない。"""
        roll = make_roll(15_113_808, 6_010_211, 316_528,
                         13_393_890, 8_131_750, 279_770)
        rep = build(roll)
        f = rep["facts"]
        bad = f["total"] / f["days_month"]          # 21,440,548 ÷ 22 = 97.5万
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
        self.assertEqual(f["per_day_basis_prev"], MR.BASIS_REVENUE_DAY)
        self.assertEqual(MR.HIST_DAYS_BASIS, MR.BASIS_REVENUE_DAY)

    def test_basis_gap_is_stated_when_thursday_is_closed(self):
        """分母の数え方が違うことを黙って比べない。"""
        rep = self._rep(thursday_closed=True)
        self.assertTrue(rep["facts"]["per_day_basis_gap"])
        t = rep["capacity"]["text"]
        self.assertIn("売上が発生した日", t)
        self.assertIn("外来診療の予定日", t)
        self.assertIn("日数そのものの前年差は出していません", t)
        self.assertIn("この違いを含んだ概算", t)

    def test_no_basis_note_when_thursday_is_open(self):
        rep = self._rep(thursday_closed=False)
        self.assertFalse(rep["facts"]["per_day_basis_gap"])
        self.assertNotIn("日数そのものの前年差は出していません", rep["capacity"]["text"])

    def test_no_year_over_year_day_count_difference(self):
        """数え方が違う日数どうしを引き算して表示しない。"""
        rep = self._rep(thursday_closed=True)
        self.assertIsNone(rep["facts"]["days_diff"])
        txt = all_text(rep) + rep["capacity"]["text"]
        for bad in ("前年同月23日に対し", "診療日数そのものは前年より",
                    "前年と同じです。内訳は"):
            self.assertNotIn(bad, txt)
        # 表の日数行にも前年・差を入れない
        row = next(r for r in rep["capacity"]["rows"] if "外来診療予定日" in r["name"])
        self.assertEqual(row["prev"], "—")
        self.assertEqual(row["diff"], "—")
        self.assertIn("比較しない", row["kind"])
        # 今月の日数そのものは出す
        self.assertIn("今月の外来診療予定日は22日です", rep["capacity"]["text"])

    def test_indicator_names_are_distinct(self):
        """2つの指標を同じ名前で並べない。"""
        rep = self._rep()
        names = [r["name"] for r in rep["capacity"]["rows"]]
        self.assertEqual(len(names), len(set(names)))
        for n in names:
            self.assertNotEqual(n, "1診療日あたり売上")
        self.assertIn("外来診療日あたり売上（外来保険＋自費＋物販）", names)

    def test_august_report_has_no_six_month_decline(self):
        """本番に出ていた「6か月続けて低下」が現在の2026年8月レポートに出ない。"""
        rep = self._rep(thursday_closed=True)
        text = all_text(rep) + (rep["trend"] or {}).get("text", "")
        for bad in ("6か月続けて低下", "6か月続けて上昇", "か月続けて低下しています（02月"):
            self.assertNotIn(bad, text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
