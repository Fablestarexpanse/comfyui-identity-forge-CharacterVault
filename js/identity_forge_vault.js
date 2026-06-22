/**
 * Identity Forge — Vault Preview extension.
 *
 * When a character is selected in the IdentityForgeVaultLoad node's dropdown,
 * the saved image is loaded and displayed directly inside the node body
 * (the same way ComfyUI's built-in PreviewImage node shows results).
 *
 * Selecting "(no characters saved)" or a missing entry clears the preview.
 * The preview also restores automatically when a saved workflow is reloaded.
 *
 * No floating overlays, no MutationObservers — everything is scoped to the
 * node's own drawing callbacks.
 */

import { app } from "../../scripts/app.js";

const NONE_SENTINEL = "(no characters saved)";
const PREVIEW_URL = (name) =>
  `/identity_forge/vault/preview/${encodeURIComponent(name)}`;

/**
 * Load the image for *characterName* and attach it to *node* via node.imgs.
 * ComfyUI's built-in drawing code takes it from there.
 */
function setNodePreview(node, characterName) {
  try {
    if (!characterName || characterName === NONE_SENTINEL) {
      node.imgs = null;
      node.setSizeForImage?.(true);
      node.setDirtyCanvas?.(true, true);
      return;
    }

    const img = new Image();

    img.onload = () => {
      try {
        node.imgs = [img];
        node.setSizeForImage?.();
        node.setDirtyCanvas?.(true, true);
      } catch (_) {
        // Silently ignore — never break the canvas render loop.
      }
    };

    img.onerror = () => {
      try {
        // Image missing or route not yet available — clear any stale preview.
        node.imgs = null;
        node.setSizeForImage?.(true);
        node.setDirtyCanvas?.(true, true);
      } catch (_) {}
    };

    img.src = PREVIEW_URL(characterName);
  } catch (_) {
    // Defensive catch so nothing here can throw into ComfyUI's extension loader.
  }
}

app.registerExtension({
  name: "identity_forge.vault_preview",

  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== "IdentityForgeVaultLoad") return;

    try {
      const onCreated = nodeType.prototype.onNodeCreated;

      nodeType.prototype.onNodeCreated = function () {
        try {
          if (onCreated) onCreated.apply(this, arguments);

          const node = this;

          // Find the character combo widget.
          const charWidget = node.widgets?.find((w) => w.name === "character");
          if (!charWidget) return;

          // Update the inline preview whenever the dropdown value changes.
          const origCallback = charWidget.callback;
          charWidget.callback = function (value) {
            try {
              if (origCallback) origCallback.apply(this, arguments);
            } catch (_) {}
            setNodePreview(node, value);
          };

          // Restore preview when a workflow is loaded (widget already has a value).
          // Small delay so the node finishes sizing itself first.
          const initial = charWidget.value;
          if (initial && initial !== NONE_SENTINEL) {
            setTimeout(() => setNodePreview(node, initial), 50);
          }
        } catch (_) {
          // Don't break node creation if something above throws.
        }
      };
    } catch (_) {
      // Don't break extension loading.
    }
  },
});
