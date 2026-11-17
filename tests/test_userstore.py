from authops.ops.userstore import UserStore, cohen_kappa, pairwise_kappa, sus_score


def test_sus_bounds():
    assert sus_score([5, 1] * 5) == 100
    assert sus_score([1, 5] * 5) == 0
    assert sus_score([3] * 10) == 50


def test_kappa():
    assert cohen_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == 1.0
    assert cohen_kappa(["a", "a", "b", "b"], ["a", "b", "a", "b"]) == 0.0
    labels = [{"tester_id": t, "item_id": f"i{k}", "field": "f", "verdict": "correct" if k % 3 else "wrong"}
              for t in ("x", "y") for k in range(6)]
    assert pairwise_kappa(labels) == {"pairs": 1, "mean_kappa": 1.0}


def test_store_roundtrip(tmp_path):
    s = UserStore(f"sqlite:///{tmp_path / 'u.db'}")
    tid = s.register("Ada", "ML / AI engineer", "2-3")
    assert tid == s.register(" ada ", "x", "y")  # same person, same id
    sid = s.start_session(tid)
    s.event(sid, tid, "Document Lab", "view")
    s.qa_label(tester_id=tid, item_id="i1", field="member_id", verdict="correct", comment="",
               auto_verdict="correct", seconds_on_item=12.0)
    c = s.counts()
    assert c["testers"] == 1 and c["events"] == 1 and c["qa_labels"] == 1
    assert not s.persistent
