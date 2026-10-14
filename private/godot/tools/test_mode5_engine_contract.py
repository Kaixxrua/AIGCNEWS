import unittest
from mode5_engine_contract import MODE5_ENGINES, WORKLETS, require_pair


class Mode5PairTests(unittest.TestCase):
    def test_all_reviewed_releases(self):
        self.assertEqual(len(MODE5_ENGINES), 4)
        for wasm, (js, audio, positional) in MODE5_ENGINES.items():
            require_pair(True, {'index.wasm': wasm, 'index.js': js,
                               'index.audio.worklet.js': audio, 'index.audio.position.worklet.js': positional})

    def test_unknown_stock_or_mixed_release_rejected(self):
        wasm, (js, *_) = next(iter(MODE5_ENGINES.items()))
        valid = {'index.wasm': wasm, 'index.js': js, 'index.audio.worklet.js': WORKLETS[0],
                 'index.audio.position.worklet.js': WORKLETS[1]}
        for name in valid:
            with self.assertRaisesRegex(ValueError, 'matching'):
                require_pair(True, {**valid, name: '0'*64})
        with self.assertRaises(ValueError):
            require_pair(True, {})

    def test_standard_pack_does_not_require_private_engine(self):
        require_pair(False, {})


if __name__ == '__main__':
    unittest.main()
