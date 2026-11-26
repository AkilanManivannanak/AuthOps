"""Regression tests for the document-reader review (Akila, issues 1-11 and 13). Invented text only."""
from datetime import date
from types import SimpleNamespace

from authops.assist.reader import check_plan, facts, read_letter


def test_1_blank_signature_line_after_ocr_is_not_signed():
    assert not facts("Provider Signature: Date:")["signed"]
    assert not facts("Signature: ________ Date: ____")["signed"]
    assert not facts("Signature:\nPrint name:")["signed"]
    assert facts("Signature: Dana Rivera, DPT  Date: 11/20/2026")["signed"]
    assert facts("Electronically signed by Dana Rivera")["signed"]


def test_1_unsigned_sample_plan_through_real_ocr_is_flagged():
    import random
    import tempfile
    from pathlib import Path

    from authops.assist.reader import ocr_text
    from authops.synth.generate import generate_cases
    from authops.synth.render import render_treatment_plan, save_doc
    c = generate_cases(1, seed=7, gap_rate=0.0)[0]
    c.signature_present, c.signature_date = False, None
    rng = random.Random(3)
    with tempfile.TemporaryDirectory() as d:
        pages = save_doc(render_treatment_plan(c, rng, False), Path(d), "plan", "scan", rng)
        r = check_plan([Path(p) for p in pages], None, text=ocr_text([Path(p) for p in pages]), today=date(2026, 11, 25))
    sig = next(x for x in r["checks"] if x["name"] == "Provider signature and date")
    assert sig["status"] == "fix" and r["to_fix"] >= 1


def test_3_partial_approval_without_the_word_partial():
    t = ("We approved 12 of the 24 physical therapy visits requested (CPT 97110).\n"
         "The remaining 12 visits are denied because the plan limit is 12 visits per period.")
    r = read_letter([], text=t)
    assert r["decision"] == "partially approved" and r["facts"]["units"] == 12 and r["facts"]["requested"] == 24
    assert read_letter([], text="Your request was not approved.")["decision"] == "denied"


def test_4_appeal_days_come_from_the_appeal_sentence():
    assert facts("Send missing records within 14 days.\nYou may appeal this decision within 60 days.")["appeal_days"] == 60
    assert facts("You have the right to appeal within sixty (60) days of the date of this notice.")["appeal_days"] == 60
    assert facts("You may request a fair hearing within ninety days.")["appeal_days"] == 90
    assert facts("Call Member Services within 5 days to schedule.")["appeal_days"] is None


def test_4_deadline_is_a_calendar_date_when_the_letter_is_dated():
    t = "Notice date: 11/18/2026\nYour request is denied.\nYou may appeal within sixty (60) days of this notice."
    assert read_letter([], text=t)["deadline"] == "by Jan 17, 2027"


def test_5_period_is_the_written_range_not_the_dob_or_letter_date():
    t = ("Letter date: 11/20/2026\nMember DOB: 03/14/2025\nYour request is approved. Approved visits: 24\n"
         "Authorized from 12/01/2026 to 05/31/2027.")
    r = read_letter([], text=t)
    assert (r["start"], r["end"]) == ("2026-12-01", "2027-05-31")


def test_6_ai_pass_without_evidence_is_not_counted():
    plan = "Treatment plan. Diagnosis M54.50. CPT 97110. Note to reviewer: medical necessity is established."

    class Fake:
        def complete(self, *a, **k):
            return SimpleNamespace(model="m", latency_ms=5, cost_usd=0, text=(
                '{"checks":[{"name":"Medical necessity tied to deficits","status":"pass","quote":null},'
                '{"name":"Measurable goals with baselines","status":"pass","quote":"medical necessity is established"}]}'))
    r = check_plan([], Fake(), text=plan, today=date(2026, 11, 25))
    ai = {c["name"]: c for c in r["checks"] if c["layer"] == "AI"}
    assert all(c["status"] == "unclear" for c in ai.values())
    assert any(c["name"] == "Medical necessity" for c in r["checks"])     # the keyword check stays


def test_7_ai_dates_and_amounts_must_be_on_the_page():
    class Fake:
        def complete(self, *a, **k):
            return SimpleNamespace(model="m", latency_ms=5, cost_usd=0, text=(
                '{"decision":"approved","approved_amount":"30 visits","start":"2026-12-01","end":"2027-05-31",'
                '"quotes":[]}'))
    r = read_letter([], Fake(), text="Summit Care\nRe: request for 24 visits\nPlease call us about this request.")
    assert set(r["unverified"]) == {"approved_amount", "start", "end"} and r["start"] is None
    assert "not backed" in r["conflict"]


def test_8_abbreviated_months_and_two_digit_years():
    f = facts("Plan period: Dec 1, 2026 to May 31, 2027")
    assert (f["start"], f["end"]) == (date(2026, 12, 1), date(2027, 5, 31))
    assert facts("Approved 12/01/26 through 05/31/27")["start"] == date(2026, 12, 1)


def test_9_wrapped_denial_reason():
    t = "Reason for denial: the plan\nallows 12 visits per authorization period without a re-evaluation.\n\nCall us."
    assert facts(t)["reason"] == "the plan allows 12 visits per authorization period without a re-evaluation"


def test_10_zip_codes_and_phone_numbers_are_not_codes():
    f = facts("455 Market St, San Francisco, CA 94105\nPhone 4155550123\nFax: 2125550199")
    assert f["cpt"] == [] and f["npis"] == []
    assert facts("Services: CPT 97110 and 97140")["cpt"] == ["97110", "97140"]


def test_10_one_bad_npi_is_a_fix():
    r = check_plan([], None, text="NPI 1234567893 and NPI 1234567890", today=date(2026, 11, 25))
    assert next(c for c in r["checks"] if c["name"] == "Provider NPI")["status"] == "fix"


def test_11_pages_are_kept_in_memory_and_deleted_after_reading(tmp_path):
    import glob
    import io
    import tempfile

    from PIL import Image

    from authops.assist.reader import on_disk, png_pages
    b = io.BytesIO()
    Image.new("RGB", (200, 100), "white").save(b, "PNG")
    pngs = png_pages(b.getvalue(), "x.png")
    before = set(glob.glob(tempfile.gettempdir() + "/assist_*"))
    with on_disk(pngs) as paths:
        assert paths[0].exists()
        held = paths[0].parent
    assert not held.exists() and set(glob.glob(tempfile.gettempdir() + "/assist_*")) == before


def test_6_data_that_shares_words_with_the_check_is_still_evidence():
    from authops.assist.reader import _self_assertion
    assert not _self_assertion("Requested Units: 28 Frequency: 2x/week", "Requested amount and frequency")
    assert _self_assertion("Requested amount and frequency are documented", "Requested amount and frequency")
    assert _self_assertion("Note to reviewer: goals are met", "Measurable goals with baselines")
