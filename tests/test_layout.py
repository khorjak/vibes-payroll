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
