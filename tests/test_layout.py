"""Responsive layout shell: sidebar is a drawer below md, a fixed column from md up."""


class TestMobileDrawer:
    def _page(self, client):
        r = client.get("/employees/")
        assert r.status_code == 200
        return r.text

    def test_sidebar_is_fixed_drawer_on_phones_and_static_on_desktop(self, client):
        page = self._page(client)
        aside = page.split('<aside id="sidebar"', 1)[1].split(">", 1)[0]
        for cls in ("fixed", "inset-y-0", "z-40", "md:static", "md:w-56"):
            assert cls in aside, cls

    def test_drawer_controls_present(self, client):
        page = self._page(client)
        assert 'id="nav-open"' in page and 'aria-controls="sidebar"' in page
        assert 'aria-expanded="false"' in page
        assert 'id="nav-close"' in page
        assert 'id="nav-backdrop"' in page

    def test_drawer_css_hides_sidebar_below_md(self, client):
        page = self._page(client)
        assert "@media (max-width: 767.98px)" in page
        assert "body.nav-open #sidebar" in page

    def test_drawer_does_not_depend_on_alpine(self, client):
        # The CSP has no 'unsafe-eval', so Alpine expressions cannot run; the
        # drawer is driven by a plain inline script instead.
        page = self._page(client)
        assert "navOpen" not in page
        assert 'getElementById("nav-open")' in page

    def test_content_padding_shrinks_on_phones(self, client):
        page = self._page(client)
        assert 'class="flex-1 overflow-auto p-4 md:p-6"' in page

    def test_htmx_partial_has_no_layout(self, client):
        r = client.get("/employees/", headers={"HX-Request": "true"})
        assert "nav-open" not in r.text and "<aside" not in r.text

    def test_login_page_has_side_margins(self, client):
        assert 'class="w-full max-w-sm px-4"' in client.get("/auth/login").text


# ── Front-end scripts must work under the app's CSP ─────────────────────────

import pathlib
import re

ALPINE_DIRECTIVE = re.compile(r'\b(x-data|x-show|x-cloak|x-model|x-init|x-text|x-bind|x-on)\b|\s@[a-z]+=|\s:[a-z-]+="')


class TestScriptsUnderCsp:
    def test_htmx_pinned_to_exact_file_with_matching_sri(self, client):
        page = client.get("/employees/").text
        # The bare package URL redirects, and its old integrity hash never matched.
        assert ('src="https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js" '
                'integrity="sha384-ujb1lZYygJmzgSwoxRggbCHcjc0rB2XoQrxeTUQyRjrOnlCoYta87iKBWq3EsdM2"') in page

    def test_alpine_not_loaded(self, client):
        assert "alpinejs" not in client.get("/employees/").text

    def test_csp_still_forbids_eval(self, client):
        csp = client.get("/auth/login").headers["content-security-policy"]
        assert "unsafe-eval" not in csp

    def test_no_alpine_directives_left_in_templates(self):
        offenders = []
        for path in pathlib.Path("templates").rglob("*.html"):
            for n, line in enumerate(path.read_text().splitlines(), 1):
                if ALPINE_DIRECTIVE.search(line):
                    offenders.append(f"{path}:{n}: {line.strip()}")
        assert not offenders, offenders

    def test_hidden_attribute_beats_display_utilities(self, client):
        assert "[hidden] { display: none !important; }" in client.get("/employees/").text


class TestToggleTargetsExist:
    """Every data-toggle / data-dismiss must point at an element on the same page."""

    def _assert_targets(self, html):
        targets = re.findall(r'data-(?:toggle|dismiss)="#([\w-]+)"', html)
        assert targets, "page has no toggles; test is not exercising anything"
        for t in targets:
            assert f'id="{t}"' in html, t

    def test_company_detail(self, client, company):
        self._assert_targets(client.get(f"/companies/{company.id}").text)

    def test_employee_profile(self, client, db, salaried_employee, benefit_plan):
        from datetime import date
        from models.benefit import EmployeeBenefitEnrollment
        db.add(EmployeeBenefitEnrollment(employee_id=salaried_employee.id,
                                         benefit_plan_id=benefit_plan.id, effective_date=date(2026, 1, 1)))
        db.commit()
        html = client.get(f"/employees/{salaried_employee.id}").text
        self._assert_targets(html)
        assert 'id="end-enrollment-' in html and 'hidden method="POST"' in html

    def test_paycheck_detail_void_panel_starts_hidden(self, client, db, company, salaried_employee, pay_period):
        client.post(f"/payroll/{pay_period.id}/calculate")
        from models.payroll import Paycheck
        pc = db.query(Paycheck).first()
        html = client.get(f"/payroll/paychecks/{pc.id}").text
        self._assert_targets(html)
        assert 'id="void-panel" hidden' in html

    def test_flash_is_dismissible(self, client, salaried_employee):
        html = client.get(f"/employees/{salaried_employee.id}?flash=updated").text
        assert 'id="flash"' in html and 'data-dismiss="#flash"' in html
        self._assert_targets(html)


class TestTimesheetAutosave:
    def test_row_posts_all_of_its_own_inputs_only(self, client, db, company, hourly_employee, pay_period):
        html = client.get(f"/payroll/{pay_period.id}/timesheets").text
        row = html.split(f'id="ts-row-{hourly_employee.id}"', 1)[1].split(">", 1)[0]
        # "find input" matched only the first input (the CSRF token), so hours posted as 0.
        assert f'hx-include="#ts-row-{hourly_employee.id} input"' in row
        # "from:input" listened to every input on the page, re-posting every row.
        assert 'hx-trigger="change delay:800ms"' in row


class TestTablesScrollOnPhones:
    def test_no_table_is_clipped_by_an_overflow_hidden_card(self):
        # A table wider than a phone inside an overflow-hidden card is cut off
        # and unreachable; the card must scroll (overflow-x-auto) instead.
        offenders = []
        for path in pathlib.Path("templates").rglob("*.html"):
            lines = path.read_text().splitlines()
            for n, line in enumerate(lines[1:], 2):
                if "<table" in line and "overflow-hidden" in lines[n - 2]:
                    offenders.append(f"{path}:{n - 1}")
        assert not offenders, offenders


class TestPhoneColumns:
    """Columns hidden below sm must be hidden in every row, or cells shift under the wrong header."""

    def _assert_rows_line_up(self, html):
        table = html.split('<table', 1)[1].split('</table>', 1)[0]
        shapes = set()
        for row in table.split('<tr')[1:]:
            cells = re.findall(r'<t[hd][\s>][^>]*', row)
            if len(cells) == 1:  # a full-width row (void reason, empty state)
                continue
            span = sum(int(m.group(1)) if (m := re.search(r'colspan="(\d+)"', c)) else 1 for c in cells)
            shapes.add((span, row.count('hidden sm:table-cell')))
        assert shapes, "need a header and a body row"
        # Phone users can always bring the hidden columns back.
        assert '<button type="button" data-all-cols' in html
        assert len(shapes) == 1, shapes
        assert shapes.pop()[1] > 0, "no phone-hidden columns; test is not exercising anything"

    def test_employee_list(self, client, salaried_employee):
        self._assert_rows_line_up(client.get("/employees/").text)

    def test_pay_runs(self, client, pay_period):
        self._assert_rows_line_up(client.get("/payroll/").text)

    def test_pay_period_paychecks_including_totals(self, client, salaried_employee, pay_period):
        client.post(f"/payroll/{pay_period.id}/calculate")
        html = client.get(f"/payroll/{pay_period.id}").text
        assert "<tfoot" in html
        self._assert_rows_line_up(html)

    def test_users(self, client, db):
        from models.user import User
        db.add(User(username="pat", hashed_password="x", role="preparer"))
        db.commit()
        self._assert_rows_line_up(client.get("/users/").text)


def test_show_all_columns_rule_overrides_hidden(client):
    assert "body.show-all-cols .hidden.sm\\:table-cell { display: table-cell; }" in client.get("/employees/").text


class TestPhoneInputs:
    def test_fields_are_16px_on_phones_so_ios_does_not_zoom(self, client):
        assert "input, select, textarea { font-size: 16px !important; }" in client.get("/employees/").text

    def test_timesheet_inputs_bring_up_decimal_keypad(self, client, hourly_employee, pay_period):
        html = client.get(f"/payroll/{pay_period.id}/timesheets").text
        assert html.count('inputmode="decimal"') == 6
