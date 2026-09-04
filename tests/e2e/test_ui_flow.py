"""Browser-driven end-to-end test of the create -> shorten -> click flow.

Points the shortener at the app's own /demo/target page instead of a real
external site so the test suite has no dependency on the public internet
and can't be flaky because some third-party site is slow or down.
"""


def test_create_and_follow_short_link(page, live_server) -> None:
    target_url = f"{live_server}/demo/target"

    page.goto(live_server + "/")
    page.fill("#original_url", target_url)
    page.click("button[type=submit]")

    result = page.locator("#result")
    result.wait_for(state="visible")

    short_link = page.locator("#short-link")
    short_href = short_link.get_attribute("href")
    assert short_href.startswith(live_server)

    page.goto(short_href)
    heading = page.locator("#demo-target-heading")
    heading.wait_for(state="visible")
    assert heading.inner_text() == "You made it!"


def test_analytics_link_leads_to_analytics_json(page, live_server) -> None:
    target_url = f"{live_server}/demo/target"

    page.goto(live_server + "/")
    page.fill("#original_url", target_url)
    page.click("button[type=submit]")
    page.locator("#result").wait_for(state="visible")

    analytics_href = page.locator("#analytics-link").get_attribute("href")
    assert analytics_href.endswith("/analytics")

    page.goto(live_server + analytics_href)
    assert '"total_clicks"' in page.locator("body").inner_text()


def test_invalid_url_shows_inline_error(page, live_server) -> None:
    page.goto(live_server + "/")
    # Switch the field to type=text so the browser's own <input type=url>
    # validation doesn't block submission before it reaches our API, since
    # this test is checking *our* server-side error handling.
    page.evaluate("document.getElementById('original_url').setAttribute('type', 'text')")
    page.fill("#original_url", "not-a-valid-url")
    page.click("button[type=submit]")

    error = page.locator("#error")
    error.wait_for(state="visible")
    assert page.locator("#result").is_hidden()
