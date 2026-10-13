import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from web.cloudflare_state import create_state_archive, restore_state_archive


class CloudflareStateArchiveTests(unittest.TestCase):
    def test_round_trip_persists_app_data_but_excludes_credentials_and_logs(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "data/users/sherry").mkdir(parents=True)
            (root / "data/articles/sherry").mkdir(parents=True)
            (root / "data/uploads/sherry").mkdir(parents=True)
            (root / "data/style_lib").mkdir(parents=True)
            (root / "data/other").mkdir(parents=True)
            (root / "config").mkdir()
            (root / "data/db.sqlite").write_bytes(b"shared database")
            (root / "data/users/sherry/content.sqlite").write_bytes(b"user database")
            (root / "data/articles/sherry/draft.md").write_text("draft", encoding="utf-8")
            (root / "data/uploads/sherry/photo.png").write_bytes(b"image")
            (root / "data/style_lib/example.md").write_text("style", encoding="utf-8")
            (root / "data/other/local-only.txt").write_text("keep", encoding="utf-8")
            (root / "config/users.json").write_text('{"users":{}}', encoding="utf-8")
            (root / "config/models.json").write_text('{"api_key":"do-not-copy"}', encoding="utf-8")
            (root / ".env").write_text("OPENAI_API_KEY=do-not-copy", encoding="utf-8")
            (root / "data/server.log").write_text("do-not-copy", encoding="utf-8")

            archive = create_state_archive(root)
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
                names = set(tar.getnames())
            self.assertIn("data/users/sherry/content.sqlite", names)
            self.assertIn("data/articles/sherry/draft.md", names)
            self.assertIn("data/uploads/sherry/photo.png", names)
            self.assertIn("data/style_lib/example.md", names)
            self.assertIn("config/users.json", names)
            self.assertFalse(any("models.json" in name or name.endswith(".log") for name in names))

            (root / "data/users/sherry/content.sqlite").unlink()
            (root / "data/articles/sherry/draft.md").unlink()
            restore_state_archive(archive, root)
            self.assertEqual((root / "data/users/sherry/content.sqlite").read_bytes(), b"user database")
            self.assertEqual((root / "data/articles/sherry/draft.md").read_text(encoding="utf-8"), "draft")
            self.assertEqual((root / "data/style_lib/example.md").read_text(encoding="utf-8"), "style")
            self.assertEqual((root / "data/other/local-only.txt").read_text(encoding="utf-8"), "keep")
            self.assertEqual((root / "config/users.json").read_text(encoding="utf-8"), '{"users":{}}')

    def test_rejects_path_traversal_before_changing_state(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "data").mkdir()
            sentinel = root / "data" / "keep.txt"
            sentinel.write_text("preserve", encoding="utf-8")
            contents = io.BytesIO()
            with tarfile.open(fileobj=contents, mode="w:gz") as tar:
                info = tarfile.TarInfo("data/../../outside.txt")
                body = b"bad"
                info.size = len(body)
                tar.addfile(info, io.BytesIO(body))
            with self.assertRaises(ValueError):
                restore_state_archive(contents.getvalue(), root)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")


if __name__ == "__main__":
    unittest.main()
