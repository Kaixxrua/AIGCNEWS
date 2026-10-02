from __future__ import annotations

from backend.app.services.project_catalog.readme_intro import (
    INTRO_CHARS,
    INTRO_PARAGRAPHS,
    readme_intro,
)

TYPICAL = """\
<p align="center"><img src="docs/logo.png" alt="Acme" width="120"></p>
<h1 align="center">Acme Agent</h1>
<p align="center">
  <a href="https://ci.example.com"><img src="https://img.shields.io/badge/ci-passing-green"></a>
  <a href="https://pypi.example.com"><img src="https://img.shields.io/badge/pypi-1.0-blue"></a>
</p>

[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md)

[![CI](https://github.com/acme/agent/actions/workflows/ci.yml/badge.svg)](https://github.com/acme/agent/actions)

Acme Agent is an **open-source** framework for building [tool-using agents](https://example.com/docs)
that run on your own hardware. It plans with `small models` and checks its own work.

> [!IMPORTANT]
> Version 2 changes the config format, read the migration guide first.

## Installation

```bash
pip install acme-agent
```

Install it with pip and run the setup wizard before anything else, then restart your shell.

### From source

Clone the repository and build the wheel yourself if you need the nightly features.

## Why Acme

Most agent frameworks assume a hosted model. Acme keeps the whole loop local, so prompts and files never leave
the machine.

- Local first
- Small models

## License

MIT licensed, see the LICENSE file for the details of what you can do with it.
"""


def test_picks_the_prose_and_skips_headers_badges_switchers_alerts_and_setup() -> None:
    assert readme_intro(TYPICAL) == (
        [
            "Acme Agent is an open-source framework for building tool-using agents that run on your own hardware."
            " It plans with small models and checks its own work.",
            "Most agent frameworks assume a hosted model. Acme keeps the whole loop local, so prompts and files"
            " never leave the machine.",
        ],
        False,
    )


def test_empty_readmes_have_no_intro() -> None:
    assert readme_intro(None) == ([], False)
    assert readme_intro("") == ([], False)
    assert readme_intro("# Title only\n\n![logo](logo.png)\n\n- a list\n- of things\n") == ([], False)


def test_stops_after_the_paragraph_limit_and_reports_more() -> None:
    body = "\n\n".join(f"Paragraph {index} explains one more part of what the tool does for you." for index in range(5))

    paragraphs, more = readme_intro(body)

    assert len(paragraphs) == INTRO_PARAGRAPHS
    assert paragraphs[0].startswith("Paragraph 0 ")
    assert more is True


def test_a_paragraph_keeps_its_text_when_a_list_follows_without_a_blank_line() -> None:
    text = (
        "Acme turns a folder of notes into a searchable knowledge base, and it ships with these pieces\n"
        "- a fast indexer\n"
        "- a chat window\n"
    )

    assert readme_intro(text) == (
        ["Acme turns a folder of notes into a searchable knowledge base, and it ships with these pieces"],
        False,
    )


def test_skipped_sections_run_until_a_heading_of_the_same_or_higher_level() -> None:
    text = """\
# Tool

## Getting started

Run the installer and accept the defaults unless you know what you are changing.

### Docker

Use the published image when you would rather not install anything on the host.

## Build your own Redis

Each step adds one feature to a tiny key-value server until it speaks the real protocol.

## 1. Usage

Call the command with a folder and it prints a summary of everything inside it.

## Architecture

The parser streams lines and never loads a whole file into memory at once.
"""

    assert readme_intro(text) == (
        [
            "Each step adds one feature to a tiny key-value server until it speaks the real protocol.",
            "The parser streams lines and never loads a whole file into memory at once.",
        ],
        False,
    )


def test_falls_back_to_skipped_sections_when_nothing_else_reads_as_prose() -> None:
    text = "# tinytool\n\n## Usage\n\ntinytool prints the size of every folder under the current directory, largest first.\n"

    assert readme_intro(text) == (
        ["tinytool prints the size of every folder under the current directory, largest first."],
        False,
    )


def test_reads_restructuredtext_titles_and_skips_directives() -> None:
    text = """\
=========
Acme Tool
=========

.. image:: https://img.shields.io/pypi/v/acme-tool.svg
   :target: https://pypi.org/project/acme-tool

Acme Tool reads your logs and tells you which service broke first, with a timeline you can paste anywhere.

Installation
------------

Run pip install acme-tool to get the command line program and all of its plugins.

Design
------

The parser streams lines and never loads a whole file, so it handles gigabytes of logs on a laptop.
"""

    assert readme_intro(text) == (
        [
            "Acme Tool reads your logs and tells you which service broke first, with a timeline you can paste"
            " anywhere.",
            "The parser streams lines and never loads a whole file, so it handles gigabytes of logs on a laptop.",
        ],
        False,
    )


def test_drops_front_matter_comments_notes_code_and_short_taglines() -> None:
    text = (
        "﻿---\r\ntitle: acme\r\n---\r\n"
        "<!-- badges start -->\r\n<!-- badges end -->\r\n"
        "Fast. Local. Yours.\r\n\r\n"
        "> **Note:** this project moved to a new organisation last spring.\r\n\r\n"
        "Note: the old API is gone and will not come back in any later version.\r\n\r\n"
        "Docs · Blog · Discord · Twitter\r\n\r\n"
        "The `Vec<T>` wrapper keeps <YOUR_TOKEN> out of logs and makes every secret type-checked.\r\n\r\n"
        "```rust\r\nlet secret = Secret::new(token);\r\n```\r\n\r\n"
        "    indented code that is long enough to look like a sentence if it were prose\r\n\r\n"
        "Quick start:\r\n\r\n"
        "~~~\r\nan unterminated fence with a long line that would otherwise read like a paragraph\r\n"
    )

    assert readme_intro(text) == (
        ["The Vec<T> wrapper keeps <YOUR_TOKEN> out of logs and makes every secret type-checked."],
        False,
    )


def test_html_keeps_link_text_and_drops_tables_and_folded_blocks() -> None:
    text = """\
<div align="center">
<p>Built by <a href="https://acme.dev"><b>Acme Labs</b></a> for people who read papers on the train and want them
offline.</p>
</div>
<table><tr><td>A long table cell that has enough words to look like a paragraph of text</td></tr></table>
<details><summary>More</summary>Folded text that also has enough words to look like a paragraph.</details>
"""

    assert readme_intro(text) == (
        ["Built by Acme Labs for people who read papers on the train and want them offline."],
        False,
    )


def test_wide_characters_count_double_and_a_short_tail_is_left_out() -> None:
    first = "这是一个把论文变成可检索知识库的工具，支持中文与英文混合检索，也能导出引用。"
    second = "第二段继续介绍它的设计，包括增量索引、离线运行与插件机制，以及如何接入现有工作流。"
    text = f"{first}\n\n{second}\n"

    # 第一段 40 字按 80 算；剩下的 40 不到一截残句的下限，第二段整段不摆
    assert readme_intro(text, limit=120) == ([first], True)
    assert readme_intro(text) == ([first, second], False)


def test_overflowing_paragraphs_are_cut_at_a_sentence_end_or_a_word() -> None:
    sentences = (
        "Acme indexes every page you visit. It keeps the index on your disk. "
        "It answers questions with links back to the pages it read and never uploads anything anywhere."
    )
    words = " ".join(["word"] * 60)

    assert readme_intro(sentences, limit=90) == (
        ["Acme indexes every page you visit. It keeps the index on your disk."],
        True,
    )
    cut, more = readme_intro(words, limit=50)
    assert more is True
    assert cut == ["word word word word word word word word word word…"]


def test_default_budget_fits_a_few_paragraphs() -> None:
    assert INTRO_PARAGRAPHS == 3
    assert INTRO_CHARS == 640
