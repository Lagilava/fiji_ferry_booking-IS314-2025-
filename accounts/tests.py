"""Tests for the accounts app: registration, login, and soft email verification.

Email is sent to Django's in-memory backend so we can assert on it.
"""
from django.core import mail
from django.test import TestCase, Client, override_settings
from django.urls import reverse

from accounts.models import User


def client(**extra):
    # ALLOWED_HOSTS excludes 'testserver'.
    return Client(HTTP_HOST="localhost", **extra)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class RegistrationTests(TestCase):
    def _register(self, c, **over):
        data = {
            "first_name": "Test", "last_name": "User",
            "username": "tester", "email": "tester@example.com",
            "password1": "Str0ng-pass!23", "password2": "Str0ng-pass!23",
        }
        data.update(over)
        return c.post(reverse("accounts:register"), data)

    def test_registration_creates_unverified_user_and_sends_email(self):
        c = client()
        resp = self._register(c)
        self.assertIn(resp.status_code, (302, 200))
        user = User.objects.get(email="tester@example.com")
        self.assertFalse(user.is_verified)          # soft: not verified yet
        self.assertTrue(c.session.get("_auth_user_id"))  # but logged in
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("confirm", mail.outbox[0].subject.lower())

    def test_verify_email_link_marks_verified(self):
        c = client()
        self._register(c)
        user = User.objects.get(email="tester@example.com")
        url = reverse("accounts:verify_email", args=[user.email_verification_token])
        resp = c.get(url)
        self.assertEqual(resp.status_code, 302)
        user.refresh_from_db()
        self.assertTrue(user.is_verified)

    def test_bad_verification_token_is_handled(self):
        import uuid
        resp = client().get(reverse("accounts:verify_email", args=[uuid.uuid4()]))
        self.assertEqual(resp.status_code, 302)  # redirected, no crash


class LoginTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="login@example.com", username="loginuser", password="pw12345!")

    def test_login_with_email(self):
        c = client()
        resp = c.post(reverse("accounts:login"),
                      {"identifier": "login@example.com", "password": "pw12345!"})
        self.assertIn(resp.status_code, (302, 200))
        self.assertTrue(c.session.get("_auth_user_id"))

    def test_login_wrong_password_fails(self):
        c = client()
        c.post(reverse("accounts:login"),
               {"identifier": "login@example.com", "password": "wrong"})
        self.assertFalse(c.session.get("_auth_user_id"))
