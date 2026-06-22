"""comfyui-identity-forge — V3 custom node pack entrypoint.

Exposes six nodes:

* ``IdentityForge`` — a 70+ field character description randomizer with a
  constraint engine and dual prose/JSON output.
* ``IdentityForgeArchetype`` — themed presets that seed IdentityForge.
* ``IdentityForgeCosplayer`` — fictional-character cosplay presets that seed
  IdentityForge (a random person cosplaying a chosen character).
* ``IdentityForgeModifier`` — prepends custom descriptors to individual fields /
  groups (e.g. "sci-fi" shoes) for per-element stylistic tilts.
* ``IdentityForgeVaultSave`` — saves a generated image + character JSON to the
  vault on disk and passes both through unchanged.
* ``IdentityForgeVaultLoad`` — reloads a saved character from the vault and
  outputs its JSON (for ``archetype_json``) and reference image.

Discovery uses the ComfyUI V3 ``comfy_entrypoint`` mechanism. Frontend widgets
live in ``./js`` and are served via ``WEB_DIRECTORY``.
"""
from comfy_api.latest import ComfyExtension, io

# ---------------------------------------------------------------------------
# Vault image preview route — serves saved character PNGs so the JS frontend
# can show an inline preview inside the node without running the workflow.
# ---------------------------------------------------------------------------
def _register_vault_routes() -> None:
    """Register vault HTTP routes on the ComfyUI PromptServer.

    Wrapped in a function so any failure is fully isolated — a broken route
    must never prevent the node pack from loading.

    Routes registered:
    - GET /identity_forge/vault/preview/{character_name}  → serves image.png
    - GET /identity_forge/vault/characters                → JSON list of names
    """
    try:
        import os as _os
        from pathlib import Path
        from aiohttp import web
        from server import PromptServer  # type: ignore[import-not-found]

        try:
            import folder_paths as _fp
            _vault_dir: Path = Path(_fp.get_output_directory()) / "Characters"
        except Exception:
            _vault_dir = Path(__file__).resolve().parent / "Characters"

        _SENTINEL = "(no characters saved)"

        @PromptServer.instance.routes.get("/identity_forge/vault/preview/{character_name}")
        async def _vault_preview(request: web.Request) -> web.Response:
            """Serve the saved PNG for one character (used by the inline node preview in JS)."""
            name = request.match_info["character_name"]
            img_path = _vault_dir / name / "image.png"
            if not img_path.exists():
                raise web.HTTPNotFound()
            return web.FileResponse(img_path, headers={"Cache-Control": "no-cache"})

        @PromptServer.instance.routes.get("/identity_forge/vault/characters")
        async def _vault_characters(request: web.Request) -> web.Response:
            """Return current vault character names as a JSON array.

            Used by the Refresh button on the Load node to update the dropdown
            without restarting ComfyUI.
            """
            try:
                if not _vault_dir.is_dir():
                    return web.json_response([_SENTINEL])
                names = sorted(
                    [
                        e.name for e in _os.scandir(_vault_dir)
                        if e.is_dir()
                        and (_vault_dir / e.name / "image.png").exists()
                        and (_vault_dir / e.name / "character.json").exists()
                    ],
                    key=str.casefold,
                )
                return web.json_response(names if names else [_SENTINEL])
            except Exception:
                return web.json_response([_SENTINEL])

    except Exception:
        pass  # Not running inside ComfyUI, or PromptServer not yet ready


_register_vault_routes()

# ---------------------------------------------------------------------------
# Node imports
# ---------------------------------------------------------------------------

# Package-relative inside ComfyUI; absolute fallback keeps the entrypoint
# importable in flatter layouts.
try:
    from .nodes.identity_forge import IdentityForge
    from .nodes.identity_forge_archetype import IdentityForgeArchetype
    from .nodes.identity_forge_cosplayer import IdentityForgeCosplayer
    from .nodes.identity_forge_modifier import IdentityForgeModifier
    from .nodes.identity_forge_vault_save import IdentityForgeVaultSave
    from .nodes.identity_forge_vault_load import IdentityForgeVaultLoad
except ImportError:  # pragma: no cover
    from nodes.identity_forge import IdentityForge
    from nodes.identity_forge_archetype import IdentityForgeArchetype
    from nodes.identity_forge_cosplayer import IdentityForgeCosplayer
    from nodes.identity_forge_modifier import IdentityForgeModifier
    from nodes.identity_forge_vault_save import IdentityForgeVaultSave
    from nodes.identity_forge_vault_load import IdentityForgeVaultLoad

#: Tells ComfyUI where to find this pack's frontend JavaScript.
WEB_DIRECTORY = "./js"

__all__ = ["comfy_entrypoint", "WEB_DIRECTORY"]


class IdentityForgeExtension(ComfyExtension):
    """Registers the IdentityForge node pack with ComfyUI."""

    async def get_node_list(self) -> list[type[io.ComfyNode]]:
        return [
            IdentityForge,
            IdentityForgeArchetype,
            IdentityForgeCosplayer,
            IdentityForgeModifier,
            IdentityForgeVaultSave,
            IdentityForgeVaultLoad,
        ]


async def comfy_entrypoint() -> IdentityForgeExtension:
    return IdentityForgeExtension()
