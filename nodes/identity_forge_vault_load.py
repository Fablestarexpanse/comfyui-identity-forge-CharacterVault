"""IdentityForgeVaultLoad node — reload a saved character from the vault.

Select a character that was previously saved with
:class:`~nodes.identity_forge_vault_save.IdentityForgeVaultSave`.  The node
outputs:

* ``character_json`` — the stored ``prompt_json``, ready to wire directly into
  an Identity Forge node's ``archetype_json`` input.  Every field is locked to
  its saved value, so the same character is reproduced exactly.
* ``image`` — the reference render that was saved alongside the JSON.

Wire ``character_json`` → ``archetype_json`` on Identity Forge, then queue
with a fixed seed to get a pixel-identical result, or with a randomised seed
to re-generate the same *character* with a new *image* (same face / outfit,
fresh composition and lighting randomisation from any still-unlocked fields).

Click **Refresh** in the ComfyUI node editor after saving new characters to
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
    _VAULT_DIR: Path = Path(_fp.get_output_directory()) / "character_vault"
except ImportError:  # pragma: no cover — standalone/test context
    _VAULT_DIR = Path(__file__).resolve().parents[2] / "vault"

try:
    from comfy_api.latest import io  # type: ignore[import-not-found]
    _COMFY_AVAILABLE: bool = True
except ImportError:  # pragma: no cover — exercised only outside ComfyUI
    _COMFY_AVAILABLE = False


#: Shown in the dropdown when the vault is empty or cannot be read.
_NONE_SENTINEL = "(no characters saved)"


# ---------------------------------------------------------------------------
# Engine (pure, no ComfyUI dependency)
# ---------------------------------------------------------------------------

def _black_image_tensor() -> Any:
    """Return a 1×1 black RGB float32 tensor with shape ``(1, 1, 1, 3)``.

    Used as a safe no-op image when no character is selected or the saved
    image cannot be read.
    """
    import torch
    return torch.zeros((1, 1, 1, 3), dtype=torch.float32)


def _get_vault_names(vault_dir: Path | None = None) -> list[str]:
    """Return a sorted list of saved character names from the vault directory.

    A valid character entry is a subdirectory of *vault_dir* that contains
    both ``image.png`` and ``character.json``.  Returns
    ``[_NONE_SENTINEL]`` when the vault is empty, does not yet exist, or
    cannot be read.

    This function is passed (without calling it) as the ``options`` callable
    for :class:`io.Combo.Input` so ComfyUI calls it on each frontend refresh.
    It must be defined at module level (not as a lambda) for picklability.
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
) -> tuple[Any, str]:
    """Load the image and JSON for *character_name* from the vault.

    Parameters
    ----------
    character_name:
        The name as it appears in the dropdown (i.e. the folder name on disk).
        Passing :data:`_NONE_SENTINEL` returns the fallback immediately.
    vault_dir:
        Override the vault root (used by tests).

    Returns
    -------
    (image_tensor, character_json)
        ``image_tensor`` has shape ``(1, H, W, 3)``, float32 in ``[0, 1]``.
        ``character_json`` is the raw string from ``character.json``, ready
        to wire into an Identity Forge node's ``archetype_json`` input.

        Falls back to ``(_black_image_tensor(), "{}")`` on sentinel, missing
        files, or any read error.  If the JSON loads but the image is corrupt,
        returns the JSON with a black placeholder image so the character data
        is not lost.
    """
    import numpy as np
    import torch
    from PIL import Image

    if character_name == _NONE_SENTINEL:
        return _black_image_tensor(), "{}"

    root = vault_dir if vault_dir is not None else _VAULT_DIR
    char_dir = root / character_name

    # Load JSON first (primary purpose of this node).
    json_path = char_dir / "character.json"
    try:
        character_json = json_path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as exc:
        print(f"[IdentityForgeVaultLoad] Could not read character.json for "
              f"'{character_name}': {exc}")
        return _black_image_tensor(), "{}"

    # Load image (best-effort; missing image doesn't discard the JSON).
    img_path = char_dir / "image.png"
    try:
        pil_img = Image.open(img_path).convert("RGB")
        img_np = np.array(pil_img, dtype=np.float32) / 255.0
        image_tensor = torch.from_numpy(img_np).unsqueeze(0)  # (1, H, W, 3)
    except Exception as exc:
        print(f"[IdentityForgeVaultLoad] Could not read image.png for "
              f"'{character_name}': {exc}")
        image_tensor = _black_image_tensor()

    return image_tensor, character_json


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
                    "input to reproduce the character exactly — every field is locked to "
                    "its saved value. Click Refresh in the node editor to pick up "
                    "characters saved during this session."
                ),
                inputs=[
                    io.Combo.Input(
                        "character",
                        options=_get_vault_names,
                        default=_NONE_SENTINEL,
                        tooltip=(
                            "Select a saved character. Click Refresh in the ComfyUI node "
                            "editor to update this list after saving new characters."
                        ),
                    ),
                ],
                outputs=[
                    io.String.Output(display_name="character_json"),
                    io.Image.Output(display_name="image"),
                ],
            )

        @classmethod
        def execute(cls, **kwargs: Any) -> "io.NodeOutput":
            character_name = kwargs.get("character", _NONE_SENTINEL)
            image_tensor, character_json = load_character(character_name)
            return io.NodeOutput(character_json, image_tensor)
