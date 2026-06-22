"""IdentityForgeVaultSave node — persist a generated character to the vault.

After Identity Forge produces a character you want to keep, wire its
``prompt_text``, ``prompt_json`` outputs and the decoded image into this node.
It saves all three to a named folder inside the Characters vault and passes
everything through unchanged so the rest of your workflow continues
uninterrupted.

Saved characters can be reloaded later via :class:`IdentityForgeVaultLoad`.

The vault lives at::

    {ComfyUI output directory}/Characters/{character name}/
        image.png
        character.json
        prompt.txt

The engine half (:func:`save_character`) is a pure function, testable without
ComfyUI.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

# Resolve the vault root at import time. folder_paths is the ComfyUI API;
# fall back to a sibling "Characters" directory when running standalone.
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


# ---------------------------------------------------------------------------
# Engine (pure, no ComfyUI dependency)
# ---------------------------------------------------------------------------

def _sanitize_name(name: str) -> str:
    """Return a filesystem-safe version of *name*.

    Strips characters that are illegal on Windows/macOS/Linux
    (``< > : " / \\ | ? *`` and ASCII control chars), collapses runs of
    whitespace to a single space, and strips leading/trailing whitespace.

    Raises :class:`ValueError` if the sanitized result is empty.
    """
    # Exclude \x09 (tab), \x0a (LF), \x0d (CR) from the control-char strip so
    # they survive to the whitespace-collapse step and become spaces.
    safe = re.sub(r'[<>:"/\\|?*\x00-\x08\x0b\x0c\x0e-\x1f]', "", name)
    safe = re.sub(r"\s+", " ", safe).strip()
    if not safe:
        raise ValueError(
            f"Character name {name!r} contains only illegal characters and "
            "cannot be used as a folder name."
        )
    return safe


def save_character(
    image_tensor: Any,
    prompt_json: str,
    prompt_text: str,
    character_name: str,
    vault_dir: Path | None = None,
) -> tuple[Any, str, str]:
    """Save image, JSON and prose text to the vault; return all three unchanged.

    Creates inside ``{vault_dir}/{safe_name}/``:
    - ``image.png``     — the rendered character image
    - ``character.json`` — the full field JSON (feeds back as archetype_json)
    - ``prompt.txt``    — the natural-language prose for reference

    Parameters
    ----------
    image_tensor:
        ComfyUI IMAGE tensor — shape ``(B, H, W, C)``, float32 in ``[0, 1]``.
        Only the first frame (``[0]``) is saved.
    prompt_json:
        The ``prompt_json`` string from an Identity Forge node.
    prompt_text:
        The ``prompt_text`` prose string from an Identity Forge node.
    character_name:
        Human-readable label for this character; used as the vault subfolder
        name after sanitization.
    vault_dir:
        Override the vault root (used by tests).

    Returns
    -------
    (image_tensor, prompt_json, prompt_text)
        The inputs, unchanged, for downstream workflow nodes.
    """
    import numpy as np
    from PIL import Image

    safe_name = _sanitize_name(character_name)
    root = vault_dir if vault_dir is not None else _VAULT_DIR
    char_dir = root / safe_name

    os.makedirs(char_dir, exist_ok=True)

    img_path  = char_dir / "image.png"
    json_path = char_dir / "character.json"
    text_path = char_dir / "prompt.txt"

    if img_path.exists():
        print(f"[IdentityForgeVaultSave] Overwriting existing character '{safe_name}'.")
    else:
        print(f"[IdentityForgeVaultSave] Saving new character '{safe_name}'.")

    # Convert tensor frame → uint8 numpy → PIL → PNG.
    try:
        img_np = (image_tensor[0].cpu().numpy() * 255).astype(np.uint8)
        pil_img = Image.fromarray(img_np)
        if pil_img.mode == "RGBA":
            pil_img = pil_img.convert("RGB")
        pil_img.save(img_path)
    except Exception as exc:
        raise RuntimeError(
            f"[IdentityForgeVaultSave] Failed to save image for '{safe_name}': {exc}"
        ) from exc

    try:
        json_path.write_text(prompt_json, encoding="utf-8")
        text_path.write_text(prompt_text, encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(
            f"[IdentityForgeVaultSave] Failed to write files for '{safe_name}': {exc}"
        ) from exc

    print(f"[IdentityForgeVaultSave] Saved to: {char_dir}")
    return image_tensor, prompt_json, prompt_text


# ---------------------------------------------------------------------------
# ComfyUI node (only defined when the API is present)
# ---------------------------------------------------------------------------

if _COMFY_AVAILABLE:

    class IdentityForgeVaultSave(io.ComfyNode):  # type: ignore[misc, valid-type]
        """Save a generated character image, JSON and prompt text to the vault."""

        @classmethod
        def define_schema(cls) -> "io.Schema":
            return io.Schema(
                node_id="IdentityForgeVaultSave",
                display_name="Identity Forge Vault Save",
                category="conditioning/character",
                description=(
                    "Save the generated image, prompt_json and prompt_text from an "
                    "Identity Forge node to the Characters vault on disk. All outputs "
                    "pass through unchanged so this node sits inline in your workflow. "
                    "Reload saved characters with Identity Forge Vault Load."
                ),
                inputs=[
                    io.Image.Input(
                        "image",
                        tooltip="Connect to the image output of your VAEDecode node.",
                    ),
                    io.String.Input(
                        "prompt_text",
                        force_input=True,
                        tooltip="Connect to the prompt_text output of an Identity Forge node.",
                    ),
                    io.String.Input(
                        "prompt_json",
                        force_input=True,
                        tooltip=(
                            "Connect to the prompt_json output of an Identity Forge node. "
                            "This JSON is saved verbatim and fed back as archetype_json "
                            "when the character is reloaded, locking every field exactly."
                        ),
                    ),
                    io.String.Input(
                        "character_name",
                        default="My Character",
                        tooltip=(
                            "Name for this character in the vault. Saving with the same "
                            "name overwrites the previous entry."
                        ),
                    ),
                ],
                outputs=[
                    io.Image.Output(display_name="image"),
                    io.String.Output(display_name="prompt_text"),
                    io.String.Output(display_name="prompt_json"),
                ],
            )

        @classmethod
        def execute(cls, **kwargs: Any) -> "io.NodeOutput":
            image        = kwargs["image"]
            prompt_text  = kwargs.get("prompt_text", "")
            prompt_json  = kwargs.get("prompt_json", "{}")
            character_name = kwargs.get("character_name", "My Character").strip() or "My Character"

            try:
                image_out, json_out, text_out = save_character(
                    image, prompt_json, prompt_text, character_name
                )
            except (ValueError, RuntimeError) as exc:
                print(f"[IdentityForgeVaultSave] {exc}")
                image_out, json_out, text_out = image, prompt_json, prompt_text

            return io.NodeOutput(image_out, text_out, json_out)
