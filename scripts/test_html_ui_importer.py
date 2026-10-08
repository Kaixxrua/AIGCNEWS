import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from import_batch_html_sources import FragmentGate, Reject, excerpts, read_local, stylesheets
from ui_import_common import sha


class HtmlImportTests(unittest.TestCase):
    def test_excerpts_keep_utf8_bytes_and_document_order(self):
        raw = ('# 表单\n<Preview class="w-full">\n<p>你好</p>\n</Preview>\n'
               '### Size\n<Preview><p>Small</p></Preview>').encode()
        examples = list(excerpts(raw, 'preview'))
        self.assertEqual([title for title, _, _ in examples], ['Default', 'Size'])
        self.assertEqual([selection['wrapper_class'] for _, _, selection in examples], ['w-full', 'w-fit'])
        for _, markup, selection in examples:
            selected = raw[selection['start']:selection['end']]
            self.assertEqual(selected, markup.encode())
            self.assertEqual(selection['sha256'], sha(selected))

    def test_hugo_ignores_docs_shell_and_keeps_original_html(self):
        raw = b'---\nimage: /docs.png\n---\n{{< code ctitle="Form" >}}<input />{{< /code >}}'
        title, markup, selection = next(excerpts(raw, 'hugo'))
        self.assertEqual((title, markup), ('Form', '<input />'))
        FragmentGate().feed(markup)
        self.assertEqual(selection['wrapper_class'], 'w-full')

    def test_network_resources_and_unmounted_dependencies_are_held(self):
        for markup in (
            '<img src="/avatar.png">', '<script src="//remote/script.js"></script>',
            '<svg><image href="data:image/png;base64,x" /></svg>',
            '<a href="https&#58;//example.com">go</a>', '<a href="javascript:alert(1)">go</a>',
            '<button onclick="alert(1)">x</button>', '<div x-data="{}"></div>',
            '<div @click="open=true"></div>', '<form action="/api">form</form>',
            '<div v-for="x in values"></div>', '<button hx-get="/api">go</button>',
            '<div style="background:url(//example.com/a)">x</div>',
            '<iframe srcdoc="x"></iframe>', '<meta http-equiv="refresh" content="1">',
            '<Component />', '<canvas></canvas>',
        ):
            with self.subTest(markup=markup), self.assertRaises(Reject):
                FragmentGate().feed(markup)

    def test_native_interactions_and_inline_vectors_stay_usable(self):
        FragmentGate().feed('<details open><summary>More</summary><p>Content</p></details>'
                            '<form action=""><input type="checkbox" checked></form>'
                            '<svg xmlns="http://www.w3.org/2000/svg"><use href="#icon" /></svg>')

    def test_stylesheet_closure_is_local_and_cycle_safe(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'entry.css').write_text('@import "./theme.css";')
            (root / 'theme.css').write_text('@import "./entry.css"; .x{color:red}')
            self.assertEqual(set(stylesheets(root, 'entry.css')), {'entry.css', 'theme.css'})
            for css in ('@import "https://example.com/x.css";',
                        '@import url(//example.com/x.css);', '.x{background:url(/asset.png)}'):
                (root / 'theme.css').write_text(css)
                with self.subTest(css=css), self.assertRaises(Reject):
                    stylesheets(root, 'entry.css')

    def test_outside_and_go_hidden_paths_are_held(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'root'
            root.mkdir()
            (root / '_hidden.css').write_text('x')
            (root.parent / 'outside.css').write_text('x')
            (root / 'linked.css').symlink_to(root.parent / 'outside.css')
            for name in ('_hidden.css', '../outside.css', 'linked.css'):
                with self.subTest(name=name), self.assertRaises(Reject):
                    read_local(root, name)


if __name__ == '__main__':
    unittest.main()
