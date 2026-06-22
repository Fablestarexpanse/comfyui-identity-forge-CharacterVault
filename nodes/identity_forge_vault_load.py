"""IdentityForgeVaultLoad node — reload a saved character from the vault.

Select a character saved with :class:`~nodes.identity_forge_vault_save.IdentityForgeVaultSave`.
Outputs:

* ``character_json`` — wire to an Identity Forge node's ``archetype_json`` to
  reproduce the character exactly (every field locked to its saved value).
* ``image`` — the reference render saved alongside the JSON.
* ``prompt_text`` — the natural-language prose saved alongside the JSON.

Click **↺ Refresh Character List** on the node after saving new characters to
update the dropdown without restarting ComfyUI.

The engine halves (:func:`_get_vault_names`, :func:`load_character`) are pure
functions, testable without ComfyUI.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# Resolve the vault root at import time.
try:
    import folder_paths as _fp
    _VAULT_DIR: Path = Path(_fp.get_output_directory()) / "Characters"
except ImportError:  # pragma: no cover — standalone/test context
    _VAULT_DIR = Path(__file__).resolve().parents[2] / "Characters"

try:
    from comfy_api.latest import io  # type: ignore[import-not-found]
    _COMFY_AVAILABLE: bool = True
except ImportError:  # pragma: no cover — exercised only outside ComfyUI
    _COMFY_AVAILABLE = False


#: Shown in the dropdown when the vault is empty or cannot be read.
_NONE_SENTINEL = "(no characters saved)"
_ENABLED  = "Enabled"
_DISABLED = "Disabled"


# ---------------------------------------------------------------------------
# Engine (pure, no ComfyUI dependency)
# ---------------------------------------------------------------------------

def _black_image_tensor() -> Any:
    """Return a 1×1 black RGB float32 tensor with shape ``(1, 1, 1, 3)``."""
    import torch
    return torch.zeros((1, 1, 1, 3), dtype=torch.float32)


def _get_vault_names(vault_dir: Path | None = None) -> list[str]:
    """Return a sorted list of saved character names from the vault directory.

    A valid entry is a subdirectory containing both ``image.png`` and
    ``character.json``.  Returns ``[_NONE_SENTINEL]`` when empty or on error.
    """
    root = vault_dir if vault_dir is not None else _VAULT_DIR
    try:
        if not root.is_dir():
            return [_NONE_SENTINEL]
        names = [
            entry.name
            for entry in os.scandir(root)
            if entry.is_dir()
            and (Path(entry.path) / "image.png").exists()
            and (Path(entry.path) / "character.json").exists()
        ]
        return sorted(names, key=str.casefold) if names else [_NONE_SENTINEL]
    except OSError:
        return [_NONE_SENTINEL]


def load_character(
    character_name: str,
    vault_dir: Path | None = None,
) -> tuple[Any, str, str]:
    """Load image, JSON and prompt text for *character_name* from the vault.

    Returns
    -------
    (image_tensor, character_json, prompt_text)
        Falls back gracefully: sentinel → black tensor + empty strings;
        missing image → black tensor but JSON/text still returned;
        missing prompt.txt (older saves) → empty string for prompt_text.
    """
    import numpy as np
    import torch
    from PIL import Image

    if character_name == _NONE_SENTINEL:
        return _black_image_tensor(), "{}", ""

    root = vault_dir if vault_dir is not None else _VAULT_DIR
    char_dir = root / character_name

    # Load JSON first (primary purpose of this node).
    json_path = char_dir / "character.json"
    try:
        character_json = json_path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as exc:
        print(f"[IdentityForgeVaultLoad] Could not read character.json for "
              f"'{character_name}': {exc}")
        return _black_image_tensor(), "{}", ""

    # Load prompt text (best-effort; older saves may not have it).
    text_path = char_dir / "prompt.txt"
    try:
        prompt_text = text_path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        prompt_text = ""

    # Load image (best-effort; missing image doesn't discard the JSON/text).
    img_path = char_dir / "image.png"
    try:
        pil_img = Image.open(img_path).convert("RGB")
        img_np = np.array(pil_img, dtype=np.float32) / 255.0
        image_tensor = torch.from_numpy(img_np).unsqueeze(0)  # (1, H, W, 3)
    except Exception as exc:
        print(f"[IdentityForgeVaultLoad] Could not read image.png for "
              f"'{character_name}': {exc}")
        image_tensor = _black_image_tensor()

    return image_tensor, character_json, prompt_text


# ---------------------------------------------------------------------------
# ComfyUI node (only defined when the API is present)
# ---------------------------------------------------------------------------

if _COMFY_AVAILABLE:

    class IdentityForgeVaultLoad(io.ComfyNode):  # type: ignore[misc, valid-type]
        """Load a saved character from the vault to seed an Identity Forge node."""

        @classmethod
        def define_schema(cls) -> "io.Schema":
            return io.Schema(
                node_id="IdentityForgeVaultLoad",
                display_name="Identity Forge Vault Load",
                category="conditioning/character",
                description=(
                    "Load a character saved by Identity Forge Vault Save. Wire "
                    "'character_json' into an Identity Forge node's 'archetype_json' "
                    "input to reproduce the character exactly. Use the Refresh button "
                    "on the node to pick up characters saved in this session."
                ),
                inputs=[
                    io.Combo.Input(
                        "enabled",
                        options=[_ENABLED, _DISABLED],
                        default=_ENABLED,
                        tooltip=(
                            "Enabled: load the selected character and lock its fields. "
                            "Disabled: output empty values so Identity Forge randomizes freely."
                        ),
                    ),
                    io.Combo.Input(
                        "character",
                        options=_get_vault_names(),
                        default=_NONE_SENTINEL,
                        tooltip="Select a saved character. Use the Refresh button to update this list.",
                    ),
                ],
                outputs=[
                    io.String.Output(display_name="character_json"),
                    io.Image.Output(display_name="image"),
                    io.String.Output(display_name="prompt_text"),
                ],
            )

        @classmethod
        def execute(cls, **kwargs: Any) -> "io.NodeOutput":
            if kwargs.get("enabled", _ENABLED) == _DISABLED:
                return io.NodeOutput("{}", _black_image_tensor(), "")

            character_name = kwargs.get("character", _NONE_SENTINEL)
            image_tensor, character_json, prompt_text = load_character(character_name)
            return io.NodeOutput(character_json, image_tensor, prompt_text)
