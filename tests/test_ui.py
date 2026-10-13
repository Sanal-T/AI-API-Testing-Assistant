import asyncio
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from app.main import app, global_exception_handler, home


class BrowserInterfaceTests(unittest.TestCase):
    def test_root_serves_workflow_ui_and_api_routes_are_registered(self):
        html = home()

        self.assertIn("Parse and generate tests", html)
        self.assertIn("Run selected tests", html)
        self.assertIn("Download JSON", html)
        self.assertIn("request_headers", html)
        self.assertIn("request_query_params", html)
        self.assertIn("/upload", app.openapi()["paths"])
        self.assertIn("/run", app.openapi()["paths"])
        self.assertIn("/generate/ai", app.openapi()["paths"])
        self.assertIn("/workflows/generate", app.openapi()["paths"])
        self.assertIn("/workflows/run", app.openapi()["paths"])

    def test_remote_api_access_requires_a_bearer_token(self):
        client = TestClient(app, client=("198.51.100.10", 50000))
        report = {"summary": {"total_tests": 0, "counts": {}}}
        with patch.dict("os.environ", {"API_ACCESS_TOKEN": ""}):
            blocked = client.post("/export/markdown", json={"report": report})
        self.assertEqual(blocked.status_code, 403)

        with patch.dict("os.environ", {"API_ACCESS_TOKEN": "test-secret"}):
            unauthorized = client.post("/export/markdown", json={"report": report})
            authorized = client.post(
                "/export/markdown",
                json={"report": report},
                headers={"Authorization": "Bearer test-secret"},
            )
        self.assertEqual(unauthorized.status_code, 401)
        self.assertEqual(authorized.status_code, 200)

    def test_global_exception_handler_captures_error_and_returns_500(self):
        mock_request = MagicMock()
        mock_request.method = "POST"
        mock_request.url.path = "/crash"
        response = asyncio.run(global_exception_handler(mock_request, RuntimeError("Database connection lost")))

        self.assertEqual(response.status_code, 500)
        self.assertIn("internal server error", response.body.decode().lower())


if __name__ == "__main__":
    unittest.main()
