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

from nodes.identity_forge_vault_save import save_character
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
    """Return a duck-typed 'tensor' whose [0].cpu().numpy() yields an HxWx3 float32 array."""
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

    arr = _np.ones((1, h, w, 3), dtype=_np.float32) * 0.5
    return _FakeTensor(arr)


def _make_vault_entry(
    vault_dir: Path, name: str, json_str: str = "{}", text_str: str = ""
) -> None:
    """Create a valid vault entry (image.png, character.json, prompt.txt)."""
    import numpy as _np
    from PIL import Image

    char_dir = vault_dir / name
    char_dir.mkdir(parents=True, exist_ok=True)
    img = Image.fromarray(_np.full((2, 2, 3), 200, dtype=_np.uint8))
    img.save(char_dir / "image.png")
    (char_dir / "character.json").write_text(json_str, encoding="utf-8")
    (char_dir / "prompt.txt").write_text(text_str, encoding="utf-8")


# ---------------------------------------------------------------------------
# _get_vault_names tests
# ---------------------------------------------------------------------------

class GetVaultNamesTests(unittest.TestCase):
    def test_nonexistent_dir_returns_sentinel(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "no_such_vault"
            self.assertEqual(_get_vault_names(vault_dir=missing), [_NONE_SENTINEL])

    @unittest.skipUnless(HAS_NUMPY, "numpy required")
    def test_empty_dir_returns_sentinel(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            vault.mkdir()
            self.assertEqual(_get_vault_names(vault_dir=vault), [_NONE_SENTINEL])

    @unittest.skipUnless(HAS_NUMPY, "numpy required")
    def test_partial_dir_excluded(self):
        """A subdirectory missing character.json should not appear."""
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            vault.mkdir()
            partial = vault / "GhostChar"
            partial.mkdir()
            from PIL import Image
            Image.fromarray(np.zeros((1, 1, 3), dtype=np.uint8)).save(partial / "image.png")
            self.assertEqual(_get_vault_names(vault_dir=vault), [_NONE_SENTINEL])

    @unittest.skipUnless(HAS_NUMPY, "numpy required")
    def test_names_sorted_case_insensitive(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            vault.mkdir()
            for name in ("Zara", "ana", "Mira"):
                _make_vault_entry(vault, name)
            self.assertEqual(_get_vault_names(vault_dir=vault), ["ana", "Mira", "Zara"])

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
    def test_creates_all_three_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            save_character(_make_fake_tensor(), '{"test": true}', "A woman.", seed=42, vault_dir=vault)
            self.assertTrue((vault / "42" / "image.png").exists())
            self.assertTrue((vault / "42" / "character.json").exists())
            self.assertTrue((vault / "42" / "prompt.txt").exists())

    def test_folder_named_by_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            save_character(_make_fake_tensor(), "{}", "", seed=99999, vault_dir=vault)
            self.assertTrue((vault / "99999").is_dir())

    def test_json_stored_verbatim(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            payload = json.dumps({"_meta": {"gender": "Female"}, "Demographics": {"age": "30"}})
            save_character(_make_fake_tensor(), payload, "", seed=1, vault_dir=vault)
            stored = (vault / "1" / "character.json").read_text(encoding="utf-8")
            self.assertEqual(stored, payload)

    def test_prompt_text_stored(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            prose = "A tall Finnish woman with auburn hair."
            save_character(_make_fake_tensor(), "{}", prose, seed=7, vault_dir=vault)
            stored = (vault / "7" / "prompt.txt").read_text(encoding="utf-8")
            self.assertEqual(stored, prose)

    def test_overwrites_same_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            save_character(_make_fake_tensor(), '{"version": 1}', "v1", seed=5, vault_dir=vault)
            save_character(_make_fake_tensor(), '{"version": 2}', "v2", seed=5, vault_dir=vault)
            stored_json = (vault / "5" / "character.json").read_text(encoding="utf-8")
            stored_text = (vault / "5" / "prompt.txt").read_text(encoding="utf-8")
            self.assertIn('"version": 2', stored_json)
            self.assertEqual(stored_text, "v2")

    def test_different_seeds_create_separate_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            save_character(_make_fake_tensor(), "{}", "", seed=10, vault_dir=vault)
            save_character(_make_fake_tensor(), "{}", "", seed=20, vault_dir=vault)
            self.assertTrue((vault / "10").is_dir())
            self.assertTrue((vault / "20").is_dir())

    def test_returns_inputs_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            tensor = _make_fake_tensor()
            json_str = '{"a": 1}'
            text_str = "A person."
            out_tensor, out_json, out_text = save_character(
                tensor, json_str, text_str, seed=3, vault_dir=vault
            )
            self.assertIs(out_tensor, tensor)
            self.assertEqual(out_json, json_str)
            self.assertEqual(out_text, text_str)


# ---------------------------------------------------------------------------
# load_character tests
# ---------------------------------------------------------------------------

class LoadCharacterTests(unittest.TestCase):
    def test_sentinel_returns_empty_strings(self):
        _, character_json, prompt_text = load_character(_NONE_SENTINEL)
        self.assertEqual(character_json, "{}")
        self.assertEqual(prompt_text, "")

    @unittest.skipUnless(HAS_TORCH, "torch required")
    def test_sentinel_returns_black_tensor(self):
        image_tensor, _, _ = load_character(_NONE_SENTINEL)
        self.assertEqual(image_tensor.shape, (1, 1, 1, 3))
        self.assertEqual(image_tensor.sum().item(), 0.0)

    @unittest.skipUnless(HAS_NUMPY, "numpy required")
    def test_missing_character_returns_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "empty_vault"
            vault.mkdir()
            _, character_json, prompt_text = load_character("DoesNotExist", vault_dir=vault)
            self.assertEqual(character_json, "{}")
            self.assertEqual(prompt_text, "")

    @unittest.skipUnless(HAS_NUMPY, "numpy required")
    def test_round_trip_json_and_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            payload = json.dumps({"_meta": {"gender": "Female"}, "Demographics": {"age": "28"}})
            prose = "A 28-year-old Japanese woman."
            save_character(_make_fake_tensor(), payload, prose, seed=42, vault_dir=vault)

            _, loaded_json, loaded_text = load_character("42", vault_dir=vault)
            self.assertEqual(loaded_json, payload)
            self.assertEqual(loaded_text, prose)

    @unittest.skipUnless(HAS_NUMPY and HAS_TORCH, "numpy and torch required")
    def test_round_trip_image_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            save_character(_make_fake_tensor(h=8, w=6), "{}", "", seed=1, vault_dir=vault)
            image_tensor, _, _ = load_character("1", vault_dir=vault)
            self.assertEqual(image_tensor.shape[0], 1)
            self.assertEqual(image_tensor.shape[3], 3)
            self.assertGreater(image_tensor.shape[1], 0)
            self.assertGreater(image_tensor.shape[2], 0)

    @unittest.skipUnless(HAS_NUMPY, "numpy required")
    def test_missing_prompt_txt_returns_empty_string(self):
        """Older saves without prompt.txt should load cleanly with empty prompt_text."""
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            _make_vault_entry(vault, "OldSave", json_str='{"old": true}')
            (vault / "OldSave" / "prompt.txt").unlink()  # simulate old save

            _, loaded_json, prompt_text = load_character("OldSave", vault_dir=vault)
            self.assertEqual(loaded_json, '{"old": true}')
            self.assertEqual(prompt_text, "")

    @unittest.skipUnless(HAS_NUMPY, "numpy required")
    def test_image_missing_still_returns_json_and_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            vault = Path(tmp) / "vault"
            _make_vault_entry(vault, "Orphan", json_str='{"rescued": true}', text_str="Rescued.")
            (vault / "Orphan" / "image.png").unlink()

            _, loaded_json, loaded_text = load_character("Orphan", vault_dir=vault)
            self.assertEqual(loaded_json, '{"rescued": true}')
            self.assertEqual(loaded_text, "Rescued.")


if __name__ == "__main__":
    unittest.main()
