"""IdentityForgeVaultSave node — persist a generated character to the vault.

Wire the image, prompt_text, prompt_json and seed output from Identity Forge
into this node. Each save is filed under the seed number by default, so every
entry is unique and you always know which seed produced it.

**Important — why the seed widget looks different after running:**
Identity Forge has ``control_after_generate = "randomize"`` on its seed widget.
ComfyUI updates that widget to the *next* random seed immediately after each
run. The seed OUTPUT (which this node reads) is the seed that was *actually
used* — the folder name will always match it. Wire the ``saved_as`` output to
a Note or display node if you want to confirm the value.

When **Enabled** the node saves to disk on every queue run.
When **Disabled** it passes all inputs through untouched without writing
anything — useful when you want to keep generating after locking a character.

Optional **custom_name**: if filled in, the folder is named with that instead
of the seed number, letting you give characters memorable labels.

The vault lives at::

    {ComfyUI output directory}/Characters/{folder_name}/
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

def _sanitize_name(name: str) -> str:
    """Return a filesystem-safe version of *name*.

    Strips characters that are illegal on Windows (``< > : " / \\ | ? *`` and
    ASCII control chars), collapses runs of whitespace to a single space, and
    strips leading/trailing whitespace.  Raises :class:`ValueError` if the
    sanitized result is empty.
    """
    safe = re.sub(r'[<>:"/\\|?*\x00-\x08\x0b\x0c\x0e-\x1f]', "", name)
    safe = re.sub(r"\s+", " ", safe).strip()
    if not safe:
        raise ValueError(
            f"Name {name!r} contains only illegal characters and cannot be "
            "used as a folder name."
        )
    return safe


def save_character(
    image_tensor: Any,
    prompt_json: str,
    prompt_text: str,
    folder_name: str,
    vault_dir: Path | None = None,
) -> tuple[Any, str, str]:
    """Save image, JSON and prose text to the vault; return all three unchanged.

    Creates inside ``{vault_dir}/{folder_name}/``:
    - ``image.png``      — the rendered character image
    - ``character.json`` — the full field JSON (feeds back as archetype_json)
    - ``prompt.txt``     — the natural-language prose for reference

    Parameters
    ----------
    image_tensor:
        ComfyUI IMAGE tensor — shape ``(B, H, W, C)``, float32 in ``[0, 1]``.
        Only the first frame (``[0]``) is saved.
    prompt_json:
        The ``prompt_json`` string from Identity Forge.
    prompt_text:
        The ``prompt_text`` prose from Identity Forge.
    folder_name:
        The vault subfolder name — either the seed as a string or a sanitized
        custom name.
    vault_dir:
        Override the vault root (used by tests).

    Returns
    -------
    (image_tensor, prompt_json, prompt_text) unchanged.
    """
    import numpy as np
    from PIL import Image

    root = vault_dir if vault_dir is not None else _VAULT_DIR
    char_dir = root / folder_name

    os.makedirs(char_dir, exist_ok=True)

    img_path  = char_dir / "image.png"
    json_path = char_dir / "character.json"
    text_path = char_dir / "prompt.txt"

    if img_path.exists():
        print(f"[IdentityForgeVaultSave] Overwriting '{folder_name}'.")
    else:
        print(f"[IdentityForgeVaultSave] Saving '{folder_name}'.")

    try:
        img_np = (image_tensor[0].cpu().numpy() * 255).astype(np.uint8)
        pil_img = Image.fromarray(img_np)
        if pil_img.mode == "RGBA":
            pil_img = pil_img.convert("RGB")
        pil_img.save(img_path)
    except Exception as exc:
        raise RuntimeError(
            f"[IdentityForgeVaultSave] Failed to save image for '{folder_name}': {exc}"
        ) from exc

    try:
        json_path.write_text(prompt_json, encoding="utf-8")
        text_path.write_text(prompt_text, encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(
            f"[IdentityForgeVaultSave] Failed to write files for '{folder_name}': {exc}"
        ) from exc

    print(f"[IdentityForgeVaultSave] Saved to: {char_dir}")
    return image_tensor, prompt_json, prompt_text


# ---------------------------------------------------------------------------
# ComfyUI node (only defined when the API is present)
# ---------------------------------------------------------------------------

if _COMFY_AVAILABLE:

    class IdentityForgeVaultSave(io.ComfyNode):  # type: ignore[misc, valid-type]
        """Save a generated character to the vault."""

        @classmethod
        def define_schema(cls) -> "io.Schema":
            return io.Schema(
                node_id="IdentityForgeVaultSave",
                display_name="Identity Forge Vault Save",
                category="conditioning/character",
                description=(
                    "Save the generated image, prompt_text and prompt_json to the "
                    "Characters vault. By default the folder is named after the seed "
                    "(wire Identity Forge's 'seed' output here). Fill in custom_name "
                    "to use a memorable label instead. The 'saved_as' output shows "
                    "exactly which folder was written so you can verify the seed."
                ),
                inputs=[
                    io.Combo.Input(
                        "enabled",
                        options=[_ENABLED, _DISABLED],
                        default=_ENABLED,
                        tooltip=(
                            "Enabled: save on every run. "
                            "Disabled: pass inputs through without writing — useful "
                            "when you want to keep generating after finding a keeper."
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
                            "This is the seed that was ACTUALLY used — Identity Forge's "
                            "seed widget shows the NEXT seed after running, so the widget "
                            "and this value will differ. The folder is named after this "
                            "value unless custom_name is set."
                        ),
                    ),
                    io.String.Input(
                        "custom_name",
                        default="",
                        tooltip=(
                            "Optional. If filled in, the vault folder uses this name "
                            "instead of the seed number. Leave blank to use the seed."
                        ),
                    ),
                ],
                outputs=[
                    io.Image.Output(display_name="image"),
                    io.String.Output(display_name="prompt_text"),
                    io.String.Output(display_name="prompt_json"),
                    io.String.Output(display_name="saved_as"),
                ],
            )

        @classmethod
        def execute(cls, **kwargs: Any) -> "io.NodeOutput":
            enabled     = kwargs.get("enabled", _ENABLED)
            image       = kwargs["image"]
            prompt_text = kwargs.get("prompt_text", "")
            prompt_json = kwargs.get("prompt_json", "{}")
            seed        = int(kwargs.get("seed", 0))
            custom_name = (kwargs.get("custom_name") or "").strip()

            # Derive folder name: sanitized custom name wins over seed.
            if custom_name:
                try:
                    folder_name = _sanitize_name(custom_name)
                except ValueError:
                    print(
                        f"[IdentityForgeVaultSave] custom_name {custom_name!r} is "
                        f"invalid; falling back to seed {seed}."
                    )
                    folder_name = str(seed)
            else:
                folder_name = str(seed)

            if enabled == _DISABLED:
                return io.NodeOutput(image, prompt_text, prompt_json, folder_name)

            try:
                image_out, json_out, text_out = save_character(
                    image, prompt_json, prompt_text, folder_name
                )
            except (ValueError, RuntimeError) as exc:
                print(f"[IdentityForgeVaultSave] {exc}")
                image_out, json_out, text_out = image, prompt_json, prompt_text

            return io.NodeOutput(image_out, text_out, json_out, folder_name)
