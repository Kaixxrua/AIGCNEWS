import unittest

from scripts import import_reviewed_ui_sources as reviewed


class ReviewedUiImportersTest(unittest.TestCase):
    def test_every_selected_component_id_is_unique(self) -> None:
        ids = (
            [f"agent-elements-{slug}" for slug, *_ in reviewed.AGENT_SPECS]
            + [f"smoothui-{slug}" for slug, *_ in reviewed.SMOOTH_SPECS]
            + [f"kibo-{slug}" for slug, *_ in reviewed.KIBO_SPECS]
            + [f"diceui-{slug}" for slug, *_ in reviewed.DICE_SPECS]
            + [f"ai-elements-{slug}" for slug, *_ in reviewed.AI_SPECS]
        )
        self.assertEqual(len(ids), 19)
        self.assertEqual(len(ids), len(set(ids)))

    def test_sources_are_commit_pinned_with_license_hashes(self) -> None:
        for source in reviewed.SOURCES.values():
            self.assertRegex(source["revision"], r"^[0-9a-f]{40}$")
            self.assertRegex(source["license_sha256"], r"^[0-9a-f]{64}$")

    def test_media_validation_rejects_network_and_embeds(self) -> None:
        unsafe = [
            b'fetch("https://example.com/data")',
            b'<img src="/remote.png">',
            b'<iframe title="remote"></iframe>',
        ]
        for raw in unsafe:
            with self.assertRaises(ValueError):
                reviewed.validate("component.tsx", raw)

    def test_media_validation_allows_documentation_urls_in_comments(self) -> None:
        reviewed.validate("component.tsx", b"/* See https://example.com/spec */\nexport const value = 1")


if __name__ == "__main__":
    unittest.main()
