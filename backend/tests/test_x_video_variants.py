import pytest

from backend.app.services.x_video_variants import select_playback_url
from scripts.backfill_x_video_variants import rewrite_media, variant_mapping


def variant(size, bitrate, **overrides):
    return dict(content_type='video/mp4', bitrate=bitrate,
                url=f'https://video.twimg.com/amplify_video/1/vid/avc1/{size}/{bitrate}.mp4?tag=29',
                **overrides)


def test_selects_advertised_720p_and_preserves_portrait_orientation():
    small, medium, large = [variant(size, rate) for size, rate in
                            [('640x360', 832000), ('1280x720', 2176000), ('3840x2160', 12000000)]]
    assert select_playback_url([large, small, medium]) == medium['url']
    portrait = variant('720x1280', 2176000)
    assert select_playback_url([large, small, portrait]) == portrait['url']


def test_high_bitrate_and_unknown_resolution_fall_back_to_smallest():
    variants = [variant('1920x1080', 4000000), variant('3840x2160', 12000000)]
    assert select_playback_url(variants) == variants[0]['url']
    assert select_playback_url([variant('1280x720', 5000000), variant('640x360', 832000)]) == variant('640x360', 832000)['url']


@pytest.mark.parametrize('url', ['http://video.twimg.com/a.mp4', 'https://evil.com/a.mp4',
    'https://video.twimg.com.evil.com/a.mp4', 'https://user@video.twimg.com/a.mp4',
    'https://video.twimg.com:444/a.mp4', 'https://video.twimg.com:bad/a.mp4'])
def test_rejects_untrusted_variant_urls(url):
    assert select_playback_url([{'url': url, 'bitrate': 832000, 'content_type': 'video/mp4'}]) == ''


@pytest.mark.parametrize('variants', [None, {}, [None], [{'content_type':'application/x-mpegURL'}],
    [{'url':'https://video.twimg.com/a.mp4','content_type':'video/mp4','bitrate':'832000'}]])
def test_malformed_variants_keep_legacy_playback(variants):
    assert select_playback_url(variants) == ''


def test_backfill_uses_exact_advertised_urls_and_preserves_other_fields():
    low, high = variant('1280x720', 2176000), variant('3840x2160', 12000000)
    mapping = variant_mapping({'quoted_status': {'video_info': {'variants': [high, low]}}})
    media = {'media': [{'type': 'video', 'url': high['url'], 'width': 3840},
                       {'type': 'photo', 'url': 'https://pbs.twimg.com/a.jpg'}], 'text': 'keep'}
    result = rewrite_media(media, mapping)
    assert result['media'][0] == {**media['media'][0], 'playback_url': low['url']}
    assert result['media'][1] == media['media'][1]
    assert result['text'] == 'keep'
    assert rewrite_media(result, mapping) == result
    assert 'playback_url' not in media['media'][0]
    assert rewrite_media(media, {}) == media
