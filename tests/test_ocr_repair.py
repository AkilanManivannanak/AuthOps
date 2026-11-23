from authops.docintel.extract import (
    clean_name, repair_auth_number, repair_icd10, repair_member_id, repair_npi,
)


def test_npi_found_by_checksum_when_label_is_garbled():
    npi, read, _ = repair_npi(["Rendering Provider: Sam { Pl: 1948757491"])
    assert npi == "1948757491" and read == "1948757491"


def test_npi_abstains_when_two_valid_candidates_compete():
    assert repair_npi(["Provider 1948757491", "Provider 1147104974"])[0] is None


def test_member_id_by_payor_prefix_format():
    assert repair_member_id(["er 1D: H8L78754679"])[0] == "HBL78754679"
    assert repair_member_id(["Subscriber !0. KCM30936048"])[0] == "KCM30936048"


def test_icd10_structure_repair_keeps_real_content_errors():
    assert repair_icd10("F84.0, F845")[0] == ["F84.0", "F84.5"]
    assert repair_icd10("M17.11, M54 50")[0] == ["M17.11", "M54.50"]
    assert repair_icd10("$83.511A")[0] == ["S83.511A"]
    assert repair_icd10("F43.19, F32.1")[0] == ["F32.1", "F43.10"]   # 9<->0 digit swap snapped
    assert repair_icd10("FBA.0")[0] == ["F8A.0"]                     # letter stays, validator flags it


def test_auth_number_shapes():
    assert repair_auth_number("RS0023191")[0] == "R50023191"
    assert repair_auth_number("QTY .. cee ees W8MIAZAIGM")[0] == "W8MIAZAIGM"
    assert repair_auth_number("3OUMGYOVV3")[1] < 0.55               # O/0 ambiguity -> human check


def test_name_cleanup():
    assert clean_name("0.0.0... FUJIMOTO, CALEB") == "Caleb Fujimoto"
    assert clean_name("Owen Haddad |") == "Owen Haddad"


def test_rollout_stats():
    from authops.ops.stats import bootstrap_diff, fisher_exact, mcnemar_exact, wilson
    lo, hi = wilson(8, 8)
    assert 0.67 < lo < 0.69 and hi == 1.0
    assert round(fisher_exact(8, 0, 2, 6), 4) == 0.007          # overlay guard on vs off
    assert mcnemar_exact(0, 6) < 0.05 and mcnemar_exact(3, 3) == 1.0
    d, lo, hi = bootstrap_diff([1, 1, 1, 0], [0, 1, 0, 0], groups=["a", "a", "b", "b"])
    assert d == 0.5 and lo <= d <= hi
