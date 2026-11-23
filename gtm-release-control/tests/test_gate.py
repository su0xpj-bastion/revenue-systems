from check_gate import PullRequestEvidence, evaluate, last_label_actor, latest_approvers

BOT = "gtm-release-classifier[bot]"
APPROVERS = {"finance-lead", "revops-lead"}


def evidence(lane, approvers=(), signoff=None, author="dev", label_actor=BOT):
    return PullRequestEvidence(
        author=author,
        lane_labels=[f"lane:{lane}"],
        lane_label_actor=label_actor,
        approvers=set(approvers),
        signoff_actor=signoff,
    )


def test_agentic_needs_no_human():
    ok, problems = evaluate(evidence("agentic"), APPROVERS)
    assert ok, problems


def test_ai_assisted_needs_non_author_review():
    assert not evaluate(evidence("ai_assisted"), APPROVERS)[0]
    assert not evaluate(evidence("ai_assisted", approvers=["dev"]), APPROVERS)[0]
    assert evaluate(evidence("ai_assisted", approvers=["reviewer"]), APPROVERS)[0]


def test_human_in_loop_needs_review_and_business_signoff():
    ok, problems = evaluate(evidence("human_in_loop", approvers=["reviewer"]), APPROVERS)
    assert not ok and any("business sign-off" in p for p in problems)

    ok, problems = evaluate(
        evidence("human_in_loop", approvers=["reviewer"], signoff="finance-lead"), APPROVERS
    )
    assert ok, problems


def test_signoff_from_non_approver_rejected():
    ok, problems = evaluate(
        evidence("human_in_loop", approvers=["reviewer"], signoff="random-dev"), APPROVERS
    )
    assert not ok and any("not a business approver" in p for p in problems)


def test_author_cannot_sign_off_own_change():
    ok, problems = evaluate(
        evidence("human_in_loop", approvers=["reviewer"], signoff="finance-lead", author="finance-lead"),
        APPROVERS,
    )
    assert not ok and any("own change" in p for p in problems)


def test_signer_cannot_be_only_code_reviewer():
    ok, problems = evaluate(
        evidence("human_in_loop", approvers=["finance-lead"], signoff="finance-lead"), APPROVERS
    )
    assert not ok and any("only code reviewer" in p for p in problems)


def test_lane_label_must_come_from_classifier():
    ok, problems = evaluate(evidence("agentic", label_actor="dev"), APPROVERS)
    assert not ok and any("not the classifier" in p for p in problems)


def test_exactly_one_lane_label():
    e = PullRequestEvidence("dev", ["lane:agentic", "lane:human_in_loop"], BOT, set(), None)
    assert not evaluate(e, APPROVERS)[0]
    e = PullRequestEvidence("dev", [], None, set(), None)
    assert not evaluate(e, APPROVERS)[0]


def test_latest_review_state_wins():
    reviews = [
        {"author": {"login": "a"}, "state": "APPROVED"},
        {"author": {"login": "a"}, "state": "CHANGES_REQUESTED"},
        {"author": {"login": "b"}, "state": "CHANGES_REQUESTED"},
        {"author": {"login": "b"}, "state": "COMMENTED"},
        {"author": {"login": "b"}, "state": "APPROVED"},
    ]
    assert latest_approvers(reviews) == {"b"}


def test_label_actor_resets_on_unlabel():
    events = [
        {"event": "labeled", "label": {"name": "signoff:business"}, "actor": {"login": "finance-lead"}},
        {"event": "unlabeled", "label": {"name": "signoff:business"}, "actor": {"login": "dev"}},
        {"event": "labeled", "label": {"name": "signoff:business"}, "actor": {"login": "dev"}},
    ]
    assert last_label_actor(events, lambda n: n == "signoff:business") == "dev"
