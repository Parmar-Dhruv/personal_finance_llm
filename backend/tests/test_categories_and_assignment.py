def test_system_categories_seeded_and_visible_to_all(alice, bob):
    names = {c["name"] for c in alice.get("/categories").json() if c["is_system"]}
    assert names == {"Food", "Transportation", "Shopping", "Utilities", "Entertainment",
                     "Healthcare", "Travel", "Rent", "Salary", "Business expenses"}
    assert {c["id"] for c in alice.get("/categories").json()} == {c["id"] for c in bob.get("/categories").json()}


def test_user_categories_are_private(alice, bob):
    alice.category("Hobbies")
    assert "Hobbies" not in {c["name"] for c in bob.get("/categories").json()}


def test_duplicate_and_shadowing_rejected(alice, bob):
    alice.category("Hobbies")
    assert alice.post("/categories", json={"name": "hobbies"}).status_code == 409      # case-insensitive
    assert alice.post("/categories", json={"name": "  Hobbies "}).status_code == 409   # whitespace-trimmed
    assert alice.post("/categories", json={"name": "food"}).status_code == 409         # shadows a system category
    assert bob.post("/categories", json={"name": "Hobbies"}).status_code == 201        # other user is fine


def test_same_name_allowed_under_different_parents(alice):
    p1, p2 = alice.category("P1"), alice.category("P2")
    alice.category("Sub", p1)
    alice.category("Sub", p2)
    assert alice.post("/categories", json={"name": "Sub", "parent_id": p1}).status_code == 409


def test_blank_and_oversized_names(alice):
    assert alice.post("/categories", json={"name": "   "}).status_code == 422
    assert alice.post("/categories", json={"name": ""}).status_code == 422
    assert alice.post("/categories", json={"name": "x" * 101}).status_code == 422


def test_parent_must_be_visible_and_depth_capped(alice, bob):
    bobs = bob.category("Bobs")
    assert alice.post("/categories", json={"name": "X", "parent_id": bobs}).status_code == 404
    assert alice.post("/categories", json={"name": "X", "parent_id": "00000000-0000-0000-0000-000000000000"}).status_code == 404
    l1 = alice.category("L1"); l2 = alice.category("L2", l1); l3 = alice.category("L3", l2)
    assert alice.post("/categories", json={"name": "L4", "parent_id": l3}).status_code == 422


def test_user_can_nest_under_system_category(alice):
    food = next(c["id"] for c in alice.get("/categories").json() if c["name"] == "Food")
    sub = alice.category("Takeaway", food)
    assert sub


def test_assign_and_clear_category(alice, add_txn):
    acct = alice.account()
    t = add_txn(alice, acct, "2026-08-01", "10.00")
    food = next(c["id"] for c in alice.get("/categories").json() if c["name"] == "Food")
    r = alice.patch(f"/transactions/{t}", json={"category_id": food})
    assert r.status_code == 200 and r.json()["category_id"] == food
    # empty body is a no-op, not a clear
    assert alice.patch(f"/transactions/{t}", json={}).json()["category_id"] == food
    # explicit null clears
    assert alice.patch(f"/transactions/{t}", json={"category_id": None}).json()["category_id"] is None


def test_assignment_isolation(alice, bob, add_txn):
    t = add_txn(alice, alice.account(), "2026-08-01", "10.00")
    bobs_cat = bob.category("Mine")
    assert bob.patch(f"/transactions/{t}", json={"category_id": bobs_cat}).status_code == 404   # not his txn
    assert alice.patch(f"/transactions/{t}", json={"category_id": bobs_cat}).status_code == 404  # not her category
    assert alice.patch(f"/transactions/{t}", json={"category_id": "nope"}).status_code == 422


def test_assignment_flows_into_analytics(alice, add_txn):
    acct = alice.account()
    t = add_txn(alice, acct, "2026-08-01", "100.00")
    before = alice.get("/analytics/categories").json()[0]["rows"]
    assert [r["label"] for r in before] == ["Uncategorized"]
    alice.patch(f"/transactions/{t}", json={"category_id": alice.category("Gadgets")})
    after = alice.get("/analytics/categories").json()[0]["rows"]
    assert [r["label"] for r in after] == ["Gadgets"]
