"""Unit tests for the Character Vault engine functions.

Pure-stdlib ``unittest`` so it runs without ComfyUI installed:

    python -m unittest discover -s tests -v

Image tests require ``numpy`` and ``Pillow``.  Tests that load the saved image
back into a tensor additionally require ``torch``; they are skipped gracefully
when torch is absent.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nodes.identity_forge_vault_save import _sanitize_name, save_character
from nodes.identity_forge_vault_load import (
    _NONE_SENTINEL, _get_vault_names, load_character,
)

# Optional heavy dependencies ------------------------------------------------
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    import torch
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_tensor(h: int = 4, w: int = 4) -> object:
    """Return a duck-typed 'tensor' whose [0].cpu().numpy() yields an HxWx3 float32 array.

    save_character does: (image_tensor[0].cpu().numpy() * 255).astype(uint8)
    So [0] must also have .cpu() and .numpy(), and numpy() must return float32 [0, 1].

    Used to test save_character without requiring torch.
    """
    import numpy as _np

    class _FakeTensor:
        def __init__(self, arr: "_np.ndarray") -> None:
            self._arr = arr

        def __getitem__(self, idx: int) -> "_FakeTensor":
            return _FakeTensor(self._arr[idx])

        def cpu(self) -> "_FakeTensor":
            return self

        def numpy(self) -> "_np.ndarray":
            return self._arr

    arr = _np.ones((1, h, w, 3), dtype=_np.float32) * 0.5  # mid-grey, float32 [0, 1]
    return _FakeTensor(arr)


def _make_vault_entry(vault_dir: Path, name: str, json_str: str = "{}") -> None:
    """Create a valid vault entry (both image.png and character.json) in *vault_dir*."""
    import numpy as _np
    from PIL import Image

    char_dir = vault_dir / name
    char_dir.mkdir(parents=True, exist_ok=True)
    # 2×2 red PNG
    img = Image.fromarray(_np.full((2, 2, 3), 200, dtype=_np.uint8))
    img.save(char_dir / "image.png")
    (char_dir / "character.json").write_text(json_str, encoding="utf-8")


# ---------------------------------------------------------------------------
# _sanitize_name tests
# ---------------------------------------------------------------------------

class SanitizeNameTests(unittest.TestCase):
    def test_clean_name_unchanged(self):
        self.assertEqual(_sanitize_name("Aria Storm"), "Aria Storm")

    def test_strips_illegal_windows_chars(self):
        result = _sanitize_name('My:Char<ac/ter">|?*')
        self.assertNotIn(":", result)
        self.assertNotIn("<", result)
        self.assertNotIn("/", result)
        self.assertNotIn('"', result)
        self.assertNotIn(">", result)
        self.assertNotIn("|", result)
        self.assertNotIn("?", result)
        self.assertNotIn("*", result)

    def test_strips_control_chars(self):
        result = _sanitize_name("Good\x00Name\x1f")
        self.assertNotIn("\x00", result)
        self.assertNotIn("\x1f", result)
        self.assertEqual(result, "GoodName")

    def test_collapses_whitespace(self):
        self.assertEqual(_sanitize_name("Two  Spaces"), "Two Spaces")
        self.assertEqual(_sanitize_name("Tab\there"), "Tab here")

    def test_strips_leading_trailing_whitespace(self):
        self.assertEqual(_sanitize_name("  padded  "), "padded")

    def test_empty_after_sanitize_raises(self):
        with self.assertRaises(ValueError):
            _sanitize_name("???")

    def test_fully_empty_raises(self):
        with self.assertRaises(ValueError):
            _sanitize_name("")

    def test_only_spaces_raises(self):
        with self.assertRaises(ValueError):
            _sanitize_name("   ")


# ---------------------------------------------------------------------------
# _get_vault_names tests
# ---------------------------------------------------------------------------

class GetVaultNamesTests(unittest.TestCase):
    def test_nonexistent_dir_returns_sentinel(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "no_such_vault"
            result = _get_vault_names(vault_dir=missing)
            self.assertEqual(result, [_NONE_SENTINEL])

    @unittest.skipUnless(HAS_NUMPY, "numpy required")
    def test_empty_dir_returns_sentinel(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            vault.mkdir()
            result = _get_vault_names(vault_dir=vault)
            self.assertEqual(result, [_NONE_SENTINEL])

    @unittest.skipUnless(HAS_NUMPY, "numpy required")
    def test_partial_dir_excluded(self):
        """A subdirectory missing character.json should not appear in the list."""
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            vault.mkdir()
            # Only image, no JSON
            partial = vault / "GhostChar"
            partial.mkdir()
            from PIL import Image
            import numpy as np
            Image.fromarray(np.zeros((1, 1, 3), dtype=np.uint8)).save(partial / "image.png")

            result = _get_vault_names(vault_dir=vault)
            self.assertEqual(result, [_NONE_SENTINEL])

    @unittest.skipUnless(HAS_NUMPY, "numpy required")
    def test_names_sorted_case_insensitive(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            vault.mkdir()
            for name in ("Zara", "ana", "Mira"):
                _make_vault_entry(vault, name)

            result = _get_vault_names(vault_dir=vault)
            self.assertEqual(result, ["ana", "Mira", "Zara"])

    @unittest.skipUnless(HAS_NUMPY, "numpy required")
    def test_returns_all_valid_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            vault.mkdir()
            for name in ("Alice", "Bob"):
                _make_vault_entry(vault, name)

            result = _get_vault_names(vault_dir=vault)
            self.assertIn("Alice", result)
            self.assertIn("Bob", result)
            self.assertEqual(len(result), 2)


# ---------------------------------------------------------------------------
# save_character tests
# ---------------------------------------------------------------------------

@unittest.skipUnless(HAS_NUMPY, "numpy and Pillow required")
class SaveCharacterTests(unittest.TestCase):
    def test_creates_both_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            tensor = _make_fake_tensor()
            save_character(tensor, '{"test": true}', "TestChar", vault_dir=vault)

            self.assertTrue((vault / "TestChar" / "image.png").exists())
            self.assertTrue((vault / "TestChar" / "character.json").exists())

    def test_json_stored_verbatim(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            payload = json.dumps({"_meta": {"gender": "Female"}, "Demographics": {"age": "30"}})
            save_character(_make_fake_tensor(), payload, "VerbatimTest", vault_dir=vault)

            stored = (vault / "VerbatimTest" / "character.json").read_text(encoding="utf-8")
            self.assertEqual(stored, payload)

    def test_overwrites_existing_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            save_character(_make_fake_tensor(), '{"version": 1}', "OW", vault_dir=vault)
            save_character(_make_fake_tensor(), '{"version": 2}', "OW", vault_dir=vault)

            stored = (vault / "OW" / "character.json").read_text(encoding="utf-8")
            self.assertIn('"version": 2', stored)

    def test_returns_inputs_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            tensor = _make_fake_tensor()
            json_str = '{"a": 1}'
            out_tensor, out_json = save_character(tensor, json_str, "PassThrough", vault_dir=vault)

            self.assertIs(out_tensor, tensor)
            self.assertEqual(out_json, json_str)

    def test_sanitizes_name_before_saving(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            save_character(_make_fake_tensor(), "{}", "My:Invalid<Name>", vault_dir=vault)
            # Should have created a sanitized folder, not a raw one
            self.assertFalse((vault / "My:Invalid<Name>").exists())
            # And sanitized folder must exist
            self.assertTrue(len(list(vault.iterdir())) == 1)

    def test_invalid_name_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            with self.assertRaises(ValueError):
                save_character(_make_fake_tensor(), "{}", "???", vault_dir=vault)


# ---------------------------------------------------------------------------
# load_character tests
# ---------------------------------------------------------------------------

class LoadCharacterTests(unittest.TestCase):
    def test_sentinel_returns_empty_json(self):
        _, character_json = load_character(_NONE_SENTINEL)
        self.assertEqual(character_json, "{}")

    @unittest.skipUnless(HAS_TORCH, "torch required")
    def test_sentinel_returns_black_tensor(self):
        image_tensor, _ = load_character(_NONE_SENTINEL)
        self.assertEqual(image_tensor.shape, (1, 1, 1, 3))
        self.assertEqual(image_tensor.sum().item(), 0.0)

    @unittest.skipUnless(HAS_NUMPY, "numpy required")
    def test_missing_character_returns_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "empty_vault"
            vault.mkdir()
            image_tensor, character_json = load_character("DoesNotExist", vault_dir=vault)
            self.assertEqual(character_json, "{}")

    @unittest.skipUnless(HAS_NUMPY, "numpy required")
    def test_round_trip_json(self):
        """Save a character then load it; the JSON must survive intact."""
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            payload = json.dumps({
                "_meta": {"gender": "Female"},
                "Demographics": {"age": "28", "ethnicity": "Japanese"},
            }, indent=2)
            save_character(_make_fake_tensor(), payload, "RoundTrip", vault_dir=vault)

            _, loaded_json = load_character("RoundTrip", vault_dir=vault)
            self.assertEqual(loaded_json, payload)

    @unittest.skipUnless(HAS_NUMPY and HAS_TORCH, "numpy and torch required")
    def test_round_trip_image_shape(self):
        """Loaded image tensor must have the expected shape."""
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            save_character(_make_fake_tensor(h=8, w=6), "{}", "ShapeTest", vault_dir=vault)

            image_tensor, _ = load_character("ShapeTest", vault_dir=vault)
            # (1, H, W, 3) — batch dim added by load_character
            self.assertEqual(image_tensor.shape[0], 1)   # batch
            self.assertEqual(image_tensor.shape[3], 3)   # channels
            self.assertGreater(image_tensor.shape[1], 0)  # height
            self.assertGreater(image_tensor.shape[2], 0)  # width

    @unittest.skipUnless(HAS_NUMPY, "numpy required")
    def test_image_missing_still_returns_json(self):
        """If image.png is deleted, load_character should still return the JSON."""
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            payload = '{"rescued": true}'
            _make_vault_entry(vault, "Orphan", json_str=payload)
            # Remove the image after creating the entry
            (vault / "Orphan" / "image.png").unlink()

            _, loaded_json = load_character("Orphan", vault_dir=vault)
            self.assertEqual(loaded_json, payload)


if __name__ == "__main__":
    unittest.main()
