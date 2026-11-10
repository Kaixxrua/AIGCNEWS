from __future__ import annotations

import unittest

from backend.app.services.project_catalog.game_details import normalize_game_details


class GameIdentityEvidenceTests(unittest.TestCase):
    def normalize(self, original: str, evidence: str, *, identity: str = "single_game", description: str = "") -> dict:
        return normalize_game_details({
            "game_identity": identity, "game_name_original": original,
            "game_name_zh": "已核实的原作中文名", "poster_candidate_id": "", "poster_kind": "",
        }, {"full_name": "example/community-port", "description": description, "readme_text": evidence})

    def test_actual_readme_emphasis_does_not_break_title_and_edition_evidence(self):
        # Minimal verbatim identity statements from these public READMEs, read
        # during the 2026-11-10 catalog audit; no repository-specific production
        # rules or poster URLs are involved.
        examples = [
            (
                "Revivedx/SavageWindRecomp",
                "**Savage Wind Recomp** is a work-in-progress static recompilation of *The Legend of Zelda: Breath of the Wild*\n"
                "(Nintendo Switch, version 1.9.0) into a native application for Windows and Linux.",
                "The Legend of Zelda: Breath of the Wild (Nintendo Switch, version 1.9.0)",
            ),
            (
                "peiikai/LASRecomp",
                "**LAS Recomp** is a static recompilation of *The Legend of Zelda: Link's Awakening* (Nintendo Switch, 2019) into a\n"
                "native Windows, macOS and Linux application.",
                "The Legend of Zelda: Link's Awakening (Nintendo Switch, 2019)",
            ),
            (
                "kuraeow/ultratears",
                "**UltraTears** builds a native version of *The Legend of Zelda: Tears of the Kingdom* (version 1.4.3) for Windows, Linux\n"
                "and the Steam Deck from your own copy of the game",
                "The Legend of Zelda: Tears of the Kingdom (version 1.4.3)",
            ),
        ]
        for repo, readme, original in examples:
            with self.subTest(repo=repo):
                result = self.normalize(original, readme)
                self.assertEqual(result["gameNameOriginal"], original)
                self.assertEqual(result["gameNameZh"], "已核实的原作中文名")
                self.assertEqual(result["identityEvidenceVersion"], 2)

    def test_display_equivalent_quotes_width_and_entities_keep_original_field(self):
        for original, evidence in [
            ("The Legend of Zelda: Link’s Awakening", "A port of The Legend of Zelda: Link's Awakening."),
            ("The Legend of Zelda: Link's Awakening", "A port of The Legend of Zelda： Link’s Awakening."),
            ("Game 2 (Switch, 2019)", "A port of *Game 2* （Switch， 2019）."),
            ("King's Quest", "A port of *King&#39;s Quest*."),
            ('The "Final" Game', 'A port of The “Final” Game.'),
            ("塞尔达传说：织梦岛", "这是塞尔达传说:织梦岛的移植项目。"),
        ]:
            with self.subTest(original=original, evidence=evidence):
                self.assertEqual(self.normalize(original, evidence)["gameNameOriginal"], original)

    def test_only_paired_emphasis_is_removed_and_word_punctuation_is_retained(self):
        for marker in ["*", "**", "***", "_", "__", "___"]:
            with self.subTest(marker=marker):
                self.assertEqual(self.normalize("Game Title (1999)", f"A port of {marker}Game Title{marker} (1999).")["gameNameOriginal"], "Game Title (1999)")
        for original, evidence in [
            ("A_Game", "A_Game"), ("A*Game", "A*Game"), ("King's Quest", "King's Quest"),
        ]:
            with self.subTest(literal=original):
                self.assertEqual(self.normalize(original, evidence)["gameNameOriginal"], original)
        for original, evidence in [
            ("AGame", "A_Game"), ("AGame", "A*Game"), ("Kings Quest", "King's Quest"),
        ]:
            with self.subTest(not_equivalent=original, evidence=evidence):
                self.assertEqual(self.normalize(original, evidence)["gameNameOriginal"], "")

    def test_sequel_year_platform_and_version_mismatches_remain_rejected(self):
        cases = [
            ("The Legend of Zelda: Breath of the Wild", "*The Legend of Zelda: Tears of the Kingdom*"),
            ("Game 2", "*Game 3*"), ("Game 2", "*Game 20*"), ("Game II", "*Game III*"),
            ("Game (Switch, 1993)", "*Game* (Switch, 2019)"),
            ("Game (Game Boy, 2019)", "*Game* (Nintendo Switch, 2019)"),
            ("Game (version 1.4.2)", "*Game* (version 1.4.3)"),
            ("Game (version 1.4)", "*Game* (version 1.4.3)"),
            ("Game 1.4", "*Game 1.4.3*"), ("Game 1.4", "*Game 1.40*"),
            ("Game Gold Edition", "*Game* (1999)"),
            ("Game 2", "Game ②"), ("Game IV", "Game Ⅳ"),
        ]
        for original, evidence in cases:
            with self.subTest(original=original, evidence=evidence):
                result = self.normalize(original, evidence)
                self.assertEqual(result["gameNameOriginal"], "")
                self.assertEqual(result["gameNameZh"], "")
                self.assertEqual(result["identityEvidenceVersion"], 2)

    def test_unknown_missing_or_project_only_identity_is_versioned_but_not_invented(self):
        for original, evidence, identity in [
            ("", "A general engine supporting many games", "unknown"),
            ("Game 2", "A port of Game 2", "unknown"),
            ("Missing Title", "A port of a different game", "single_game"),
            ("community-port", "*community-port*", "single_game"),
            ("example/community-port", "example/community-port", "single_game"),
        ]:
            with self.subTest(original=original, identity=identity):
                result = self.normalize(original, evidence, identity=identity)
                self.assertEqual(result["identityEvidenceVersion"], 2)
                self.assertEqual(result["detailsVersion"], 1)
                self.assertTrue(all(result[key] == "" for key in ("gameNameOriginal", "gameNameZh", "posterUrl")))


if __name__ == "__main__":
    unittest.main()
