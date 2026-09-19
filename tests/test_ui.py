import unittest

from app.main import app, home


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


if __name__ == "__main__":
    unittest.main()
