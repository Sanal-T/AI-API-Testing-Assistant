import asyncio
import unittest
from unittest.mock import MagicMock

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

    def test_global_exception_handler_captures_error_and_returns_500(self):
        mock_request = MagicMock()
        mock_request.method = "POST"
        mock_request.url.path = "/crash"
        response = asyncio.run(global_exception_handler(mock_request, RuntimeError("Database connection lost")))

        self.assertEqual(response.status_code, 500)
        self.assertIn("internal server error", response.body.decode().lower())


if __name__ == "__main__":
    unittest.main()
