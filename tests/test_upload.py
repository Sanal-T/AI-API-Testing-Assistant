import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from app.api import upload as upload_module


class UploadProcessingTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.upload_dir = Path(self.temp_dir.name)
        self.upload_dir_patch = patch.object(upload_module, "UPLOAD_DIR", self.upload_dir)
        self.upload_dir_patch.start()

    def tearDown(self):
        self.upload_dir_patch.stop()
        self.temp_dir.cleanup()

    def test_upload_uses_server_filename_and_returns_generated_tests(self):
        spec = {
            "openapi": "3.0.3",
            "info": {"title": "Test API", "version": "1.0"},
            "paths": {"/health": {"get": {"responses": {"200": {"description": "ok"}}}}},
        }
        endpoints = upload_module.process_spec_upload("../../unsafe.yaml", json.dumps(spec).encode())

        saved_files = list(self.upload_dir.iterdir())
        self.assertEqual(len(endpoints), 1)
        self.assertEqual(len(endpoints[0]["test_cases"]), 1)
        self.assertEqual(len(saved_files), 1)
        self.assertEqual(saved_files[0].parent, self.upload_dir)
        self.assertNotEqual(saved_files[0].name, "unsafe.yaml")

    def test_invalid_openapi_document_returns_400_and_is_removed(self):
        with self.assertRaises(HTTPException) as raised:
            upload_module.process_spec_upload("invalid.json", b'{"paths": {}}')

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(list(self.upload_dir.iterdir()), [])

    def test_oversized_file_returns_413_without_writing_it(self):
        with self.assertRaises(HTTPException) as raised:
            upload_module.process_spec_upload(
                "large.json",
                b" " * (upload_module.MAX_UPLOAD_SIZE + 1),
            )

        self.assertEqual(raised.exception.status_code, 413)
        self.assertEqual(list(self.upload_dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
