import json
import os
import unittest
from unittest.mock import patch

from app import app


class BackendTests(unittest.TestCase):
    def setUp(self):
        app.testing = True
        self.client = app.test_client()

    def test_home_and_health(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/health").json["status"], "ok")

    def test_requires_fictional_confirmation(self):
        r = self.client.post("/api/generate", json={"fictional": False})
        self.assertEqual(r.status_code, 400)

    def test_invalid_profile(self):
        r = self.client.post("/api/generate", json={
            "fictional": True, "profile": {}, "jd_title": "Engineer",
            "jd_text": "Python and SQL"})
        self.assertEqual(r.status_code, 400)

    def test_missing_api_key(self):
        payload = {"fictional": True, "profile": {
            "name": "Example", "experience": [{"role": "Analyst"}]},
            "jd_title": "Engineer", "jd_text": "Python"}
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(self.client.post("/api/generate", json=payload).status_code, 503)

    def test_unknown_export_token(self):
        self.assertEqual(self.client.get("/api/download/pdf/not-a-token").status_code, 404)
        self.assertEqual(self.client.get("/api/download/txt/not-a-token").status_code, 400)


if __name__ == "__main__":
    unittest.main()
