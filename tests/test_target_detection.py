"""Phase 2: the application under test found from Jira / Confluence - websites, API endpoints, OpenAPI specs, APKs,
Android packages, iOS bundles and repositories, each with where it came from and the engine that tests it; Jira,
Confluence and documentation addresses are never taken for the application."""
from backend.atlassian import jira, workflow
from backend.atlassian.models import Connection
from tests.atlassian_mock import T0, story
from tests.test_requirements_execution import api  # noqa: F401


def test_values_are_classified_by_what_they_are_and_documentation_is_never_a_target():
    t = workflow.targets_in_text(
        "Test on https://staging.shop.example/login - API https://api.shop.example/v1/orders, spec "
        "https://shop.example/openapi.json; docs https://docs.shop.example/a; https://acme.atlassian.net/browse/QPL-1 "
        "https://www.youtube.com/watch?v=x https://shop.example/logo.png", {"acme.atlassian.net"})
    assert [(x["value"], x["kind"]) for x in t] == [("https://staging.shop.example/", "web"),
                                                   ("https://api.shop.example/v1/orders", "api"),
                                                   ("https://shop.example/openapi.json", "openapi")]


def test_mobile_ids_need_their_own_words_and_repositories_need_an_application_field():
    t = workflow.targets_in_text("Android package: com.acme.shop ; iOS bundle id com.acme.shopios", set())
    assert [(x["value"], x["kind"]) for x in t] == [("com.acme.shop", "android_package"),
                                                   ("com.acme.shopios", "ios_bundle")]
    assert workflow.targets_in_text("We use com.google.analytics for tracking", set()) == []
    assert workflow.targets_in_text("see https://github.com/acme/app", set()) == []  # (a link in prose: docs)
    assert workflow.targets_in_text("https://github.com/acme/app/tree/main", set(), explicit=True) == [
        {"value": "https://github.com/acme/app", "kind": "repository"}]
    assert workflow.targets_in_text("https://files.example/app-debug.apk", set()) == [
        {"value": "https://files.example/app-debug.apk", "kind": "android_apk"}]


def test_a_story_without_application_fields_keeps_its_content_hash():
    conn = Connection(id="c", tenant_id="t", product="jira", site_url="https://acme.atlassian.net",
                      email="qa@example.com", token_ref="JIRA_READ_API_TOKEN")
    issue = story("QPL-9", "A story", T0, "Some text")
    before = jira.normalize(issue, conn)["source"].content_hash
    after = jira.normalize(issue, conn, target_fields={"customfield_10050": "Test Environment"})
    assert after["source"].content_hash == before and "app_fields" not in after["story"]
    issue["fields"]["customfield_10050"] = "https://staging.shop.example/"
    with_value = jira.normalize(issue, conn, target_fields={"customfield_10050": "Test Environment"})
    assert with_value["story"]["app_fields"] == {"Test Environment": "https://staging.shop.example/"}
    assert with_value["source"].content_hash != before


def test_a_jira_application_field_is_read_on_import_and_offered_as_a_target(api):
    from backend import requirements_api as rapi
    api.mock.fields.append({"id": "customfield_10050", "name": "Test Environment", "custom": True})
    api.mock.fields.append({"id": "customfield_10051", "name": "Story Points", "custom": True})
    api.mock.issues["QPL-2"]["fields"]["customfield_10050"] = "https://staging.shop.example/ (Android package " \
                                                              "com.acme.shop)"
    api.mock.issues["QPL-2"]["fields"]["customfield_10051"] = 5
    rapi.JOBS.wait(api.client.post("/api/requirements/connections/jira-main/imports", headers=api.H,
                                   json={"mode": "items", "keys": "QPL-2"}).json()["id"])
    r = api.client.get("/api/requirements/targets/resolve?requirements=QPL-2", headers=api.H).json()
    by = {c["url"]: c for c in r["candidates"]}
    assert by["https://staging.shop.example/"]["kind"] == "web"
    assert by["https://staging.shop.example/"]["sources"][0].startswith("Jira field 'Test Environment' of QPL-2")
    assert by["com.acme.shop"]["kind"] == "android_package" and "Appium" in by["com.acme.shop"]["engine"]
    assert not by["https://staging.shop.example/"]["authorized"]  # (found, not yet confirmed by a person)
    assert all("atlassian" not in u for u in by)
