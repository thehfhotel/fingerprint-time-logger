"""The Employee Management grant checkboxes mirror APP_CATALOG by hand.

WHY THIS TEST EXISTS
--------------------
``static/v2/employees.html`` renders the app-grant checkboxes from a JS
``APP_CATALOG`` constant it carries itself — NOT from the ``catalog`` field
``/api/private/admin/employees`` already returns. So an app present in the
Python catalog but missing from that JS copy cannot be ticked or un-ticked in
the UI at all, however valid the grant is server-side.

That is not hypothetical: ``reimbursement`` was added to the Python catalog in
2026-07 and never mirrored, so for a month no admin could grant or revoke it
from this page even though every employee gets it at onboarding. Nothing
failed, nothing logged — the checkbox simply was not there. Found 2026-08-17
while adding ``housekeeping_admin``, which would have drifted the same way.

The honest fix is for the page to fetch the catalog it already receives; until
someone does that, this test is the thing that makes the copy honest.
"""

import os
import re

from app.services.app_catalog import APP_CATALOG

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
EMPLOYEES_HTML = os.path.join(_REPO_ROOT, "static", "v2", "employees.html")

# `{ app_id: "x", name: "y" }` — the exact shape the page writes.
_ENTRY = re.compile(r'\{\s*app_id:\s*"([^"]+)"\s*,\s*name:\s*"([^"]*)"\s*\}')


def _js_catalog():
    """The JS APP_CATALOG as [(app_id, name)], in the order the page lists it."""
    with open(EMPLOYEES_HTML, encoding="utf-8") as handle:
        html = handle.read()

    start = html.index("const APP_CATALOG = [")
    end = html.index("];", start)
    return _ENTRY.findall(html[start:end])


class TestAppCatalogMirror:
    def test_the_page_still_declares_a_catalog_to_mirror(self):
        # Guards the test itself: if the page is rewritten to fetch the catalog
        # from the API (the real fix), this fails and should be DELETED along
        # with the JS constant — not quietly patched to keep passing.
        assert _js_catalog(), (
            "No JS APP_CATALOG entries parsed from employees.html. Either the "
            "shape changed, or the page now fetches the catalog — in which "
            "case delete this test."
        )

    def test_every_catalog_app_is_tickable_in_the_ui(self):
        missing = [app_id for app_id, _ in APP_CATALOG if app_id not in dict(_js_catalog())]
        assert not missing, (
            f"In APP_CATALOG but not in employees.html, so no admin can grant "
            f"or revoke them: {missing}"
        )

    def test_the_ui_offers_nothing_the_server_would_reject(self):
        # The other direction: a checkbox for an app_id the catalog does not
        # know would be offered and then refused on save.
        extra = [app_id for app_id, _ in _js_catalog() if app_id not in dict(APP_CATALOG)]
        assert not extra, f"Offered by employees.html but not in APP_CATALOG: {extra}"

    def test_names_and_order_match(self):
        # Order is what the admin reads down; names are what they read. Both
        # drifting silently is the same class of bug as a missing entry.
        assert _js_catalog() == [(app_id, name) for app_id, name in APP_CATALOG]
