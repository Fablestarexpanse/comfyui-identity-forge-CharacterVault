"""IdentityForgeVaultSave node — persist a generated character to the vault.

Wire the image, prompt_text, prompt_json from Identity Forge and the seed
value that drove the generation into this node. Each save is filed under its
seed number so every entry is unique and you always know which seed produced it.

When **Enabled** the node saves to disk on every queue run.
When **Disabled** it passes all inputs through untouched without writing
anything — useful when you find a character you like and want to keep
generating without overwriting the saved entry.

The vault lives at::

    {ComfyUI output directory}/Characters/{seed}/
        image.png
        character.json
        prompt.txt

The engine half (:func:`save_character`) is a pure function, testable without
ComfyUI.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    import folder_paths as _fp
    _VAULT_DIR: Path = Path(_fp.get_output_directory()) / "Characters"
except ImportError:  # pragma: no cover
    _VAULT_DIR = Path(__file__).resolve().parents[2] / "Characters"

try:
    from comfy_api.latest import io  # type: ignore[import-not-found]
    _COMFY_AVAILABLE: bool = True
except ImportError:  # pragma: no cover
    _COMFY_AVAILABLE = False

_ENABLED  = "Enabled"
_DISABLED = "Disabled"


# ---------------------------------------------------------------------------
# Engine (pure, no ComfyUI dependency)
# ---------------------------------------------------------------------------

def save_character(
    image_tensor: Any,
    prompt_json: str,
    prompt_text: str,
    seed: int,
    vault_dir: Path | None = None,
) -> tuple[Any, str, str]:
    """Save image, JSON and prose for *seed* to the vault; return all three unchanged.

    The vault subfolder is named after *seed* so it is unique per generation
    and instantly identifies which seed produced the character.

    Parameters
    ----------
    image_tensor:
        ComfyUI IMAGE tensor — shape ``(B, H, W, C)``, float32 in ``[0, 1]``.
        Only the first frame (``[0]``) is saved.
    prompt_json:
        The ``prompt_json`` string from Identity Forge.
    prompt_text:
        The ``prompt_text`` prose from Identity Forge.
    seed:
        The generation seed. Used as the folder name.
    vault_dir:
        Override the vault root (used by tests).

    Returns
    -------
    (image_tensor, prompt_json, prompt_text) unchanged.
    """
    import numpy as np
    from PIL import Image

    folder_name = str(seed)
    root = vault_dir if vault_dir is not None else _VAULT_DIR
    char_dir = root / folder_name

    os.makedirs(char_dir, exist_ok=True)

    img_path  = char_dir / "image.png"
    json_path = char_dir / "character.json"
    text_path = char_dir / "prompt.txt"

    if img_path.exists():
        print(f"[IdentityForgeVaultSave] Overwriting seed {seed}.")
    else:
        print(f"[IdentityForgeVaultSave] Saving seed {seed}.")

    try:
        img_np = (image_tensor[0].cpu().numpy() * 255).astype(np.uint8)
        pil_img = Image.fromarray(img_np)
        if pil_img.mode == "RGBA":
            pil_img = pil_img.convert("RGB")
        pil_img.save(img_path)
    except Exception as exc:
        raise RuntimeError(
            f"[IdentityForgeVaultSave] Failed to save image for seed {seed}: {exc}"
        ) from exc

    try:
        json_path.write_text(prompt_json, encoding="utf-8")
        text_path.write_text(prompt_text, encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(
            f"[IdentityForgeVaultSave] Failed to write files for seed {seed}: {exc}"
        ) from exc

    print(f"[IdentityForgeVaultSave] Saved to: {char_dir}")
    return image_tensor, prompt_json, prompt_text


# ---------------------------------------------------------------------------
# ComfyUI node (only defined when the API is present)
# ---------------------------------------------------------------------------

if _COMFY_AVAILABLE:

    class IdentityForgeVaultSave(io.ComfyNode):  # type: ignore[misc, valid-type]
        """Save a generated character to the vault, named by its seed."""

        @classmethod
        def define_schema(cls) -> "io.Schema":
            return io.Schema(
                node_id="IdentityForgeVaultSave",
                display_name="Identity Forge Vault Save",
                category="conditioning/character",
                description=(
                    "Save the generated image, prompt_text and prompt_json to the "
                    "Characters vault, filed under the seed number so every entry is "
                    "unique and traceable. Set to Disabled to keep running without "
                    "overwriting the saved character."
                ),
                inputs=[
                    io.Combo.Input(
                        "enabled",
                        options=[_ENABLED, _DISABLED],
                        default=_ENABLED,
                        tooltip=(
                            "Enabled: save on every run. "
                            "Disabled: pass inputs through without writing anything — "
                            "useful when you want to keep generating after locking a "
                            "character you like."
                        ),
                    ),
                    io.Image.Input(
                        "image",
                        tooltip="Connect to the image output of your VAEDecode node.",
                    ),
                    io.String.Input(
                        "prompt_text",
                        force_input=True,
                        tooltip="Connect to the prompt_text output of Identity Forge.",
                    ),
                    io.String.Input(
                        "prompt_json",
                        force_input=True,
                        tooltip="Connect to the prompt_json output of Identity Forge.",
                    ),
                    io.Int.Input(
                        "seed",
                        force_input=True,
                        tooltip=(
                            "Wire from Identity Forge's 'seed' output. "
                            "The seed becomes the folder name in the vault so each "
                            "character is unique and traceable."
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
            enabled     = kwargs.get("enabled", _ENABLED)
            image       = kwargs["image"]
            prompt_text = kwargs.get("prompt_text", "")
            prompt_json = kwargs.get("prompt_json", "{}")
            seed        = int(kwargs.get("seed", 0))

            if enabled == _DISABLED:
                return io.NodeOutput(image, prompt_text, prompt_json)

            try:
                image_out, json_out, text_out = save_character(
                    image, prompt_json, prompt_text, seed
                )
            except (ValueError, RuntimeError) as exc:
                print(f"[IdentityForgeVaultSave] {exc}")
                image_out, json_out, text_out = image, prompt_json, prompt_text

            return io.NodeOutput(image_out, text_out, json_out)
