from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from config import urls_landing, urls_pos
from core.middleware import ActiveBranchMiddleware


class DummyUser:
    def __init__(self, *, is_authenticated=True, is_superuser=False, profile=None):
        self.is_authenticated = is_authenticated
        self.is_superuser = is_superuser
        self.profile = profile


class RootUrlConfSplitTests(SimpleTestCase):
    def test_pos_urlconf_contains_internal_routes(self):
        routes = [str(pattern.pattern) for pattern in urls_pos.urlpatterns]
        self.assertIn("admin/", routes)
        self.assertIn("accounts/", routes)
        self.assertIn("pos/", routes)

    def test_landing_urlconf_is_landing_only(self):
        routes = [str(pattern.pattern) for pattern in urls_landing.urlpatterns]
        self.assertEqual(routes, [""])


class ActiveBranchMiddlewareTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @override_settings(POS_MODE=False, ROOT_URLCONF="config.urls_landing")
    def test_landing_mode_skips_active_branch_enforcement(self):
        middleware = ActiveBranchMiddleware(lambda request: HttpResponse("ok"))
        request = self.factory.get("/")
        request.user = DummyUser(is_authenticated=True, is_superuser=True)
        request.session = {}

        response = middleware(request)

        self.assertEqual(response.status_code, 200)

    @override_settings(POS_MODE=True, ROOT_URLCONF="config.urls_landing")
    def test_missing_select_branch_route_does_not_crash(self):
        middleware = ActiveBranchMiddleware(lambda request: HttpResponse("ok"))
        request = self.factory.get("/")
        request.user = DummyUser(is_authenticated=True, is_superuser=True)
        request.session = {}

        response = middleware(request)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(hasattr(request, "active_branch"))
        self.assertIsNone(request.active_branch)
