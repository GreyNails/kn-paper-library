#!/usr/bin/env python3
"""Independently verify all exported speech, images, paths, and download ZIPs."""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urlsplit, unquote
import argparse, concurrent.futures, hashlib, json, zipfile


class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.speech = None
        self.in_time = False
        self.paragraphs = []
        self.images = []
        self.links = []
        self.audio = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'p' and 'speech' in attrs.get('class', '').split():
            self.speech = []
        if tag == 'time':
            self.in_time = True
        if tag == 'img':
            self.images.append(attrs['src'])
        if tag == 'audio':
            self.audio.append(attrs['src'])
        if tag == 'a' and attrs.get('href'):
            self.links.append(attrs['href'])
        if tag in ['script', 'img', 'audio'] and attrs.get('src'):
            self.links.append(attrs['src'])
        if tag == 'link' and attrs.get('href'):
            self.links.append(attrs['href'])

    def handle_endtag(self, tag):
        if tag == 'time':
            self.in_time = False
        if tag == 'p' and self.speech is not None:
            self.paragraphs.append(''.join(self.speech))
            self.speech = None

    def handle_data(self, text):
        if self.speech is not None and not self.in_time:
            self.speech.append(text)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--downloads', type=Path)
    a = p.parse_args()
    root = Path(__file__).resolve().parents[1]
    site = root / 'site'
    rows = json.loads((site / 'data/catalog.json').read_text())
    assert len(rows) == 257
    images = []
    for row in rows:
        vid = row['video_id']
        expected = json.loads((site / 'data/books' / (vid + '.json')).read_text())
        parser = Page()
        parser.feed((site / 'reading' / vid / 'index.html').read_text())
        assert parser.paragraphs == expected['paragraphs'], vid + ': narration mismatch'
        assert expected['segment_ids'] == expected['source_segment_ids'], vid + ': segment coverage mismatch'
        assert parser.images == [x['src'] for x in expected['frames']], vid + ': image order mismatch'
        assert len(parser.audio) == len(expected['audio_notes']), vid + ': audio count mismatch'
        images.extend(expected['frames'])
    def check_image(frame):
        path = site / frame['path']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == frame['sha256'], str(path)
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(check_image, images))
    assert len(images) == 17881
    local_links = 0
    for path in site.rglob('*.html'):
        parser = Page()
        text = path.read_text()
        parser.feed(text)
        for link in parser.links:
            split = urlsplit(link)
            if split.scheme or not split.path:
                continue
            local_links += 1
            target = (path.parent / unquote(split.path)).resolve()
            assert target.is_relative_to(site), (path, link)
            assert target.is_file() or target.is_dir() and (target / 'index.html').is_file(), (path, link)
        for private in ['oauth_token', 'notion-connection.json', 'notion-sync-state.json']:
            assert private not in text, 'Private runtime data leaked into ' + str(path)
    packages = []
    original_keys = set()
    if a.downloads:
        packages = sorted(a.downloads.glob('v*-materials.zip'))
        assert len(packages) == 257
        def check_zip(path):
            with zipfile.ZipFile(path) as z:
                assert z.testzip() is None, path.name + ': bad CRC'
                required = {'阅读文档.html', '阅读文档.pdf', '阅读文档.docx', '全部PPT画面.pdf',
                            '原始逐字稿.txt', '字幕.srt', '校对记录.json', '原论文链接.json'}
                assert required <= set(z.namelist()), path.name + ': missing files'
                assert all(z.getinfo(name).file_size > 0 for name in required)
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(check_zip, packages))
        papers = {p['key']: p for p in json.loads((site / 'data/papers.json').read_text())}
        for path in sorted(a.downloads.glob('originals-*.zip')):
            with zipfile.ZipFile(path) as z:
                assert z.testzip() is None, path.name + ': bad original CRC'
                index = json.loads(z.read('目录.json'))
                for item in index:
                    assert item['key'] not in original_keys
                    assert hashlib.sha256(z.read(item['filename'])).hexdigest() == papers[item['key']]['sha256']
                    original_keys.add(item['key'])
        assert original_keys == set(papers), 'Original PDF archive coverage differs from the catalog'
    total = sum(p.stat().st_size for p in site.rglob('*') if p.is_file())
    assert total < 950_000_000
    report = {'passed': True, 'documents': len(rows), 'ordered_slide_images': len(images),
              'all_narration_preserved': True, 'all_image_bytes_preserved': True,
              'local_links_checked': local_links, 'missing_local_links': 0,
              'download_packages_checked': len(packages), 'original_pdfs_checked': len(original_keys), 'site_bytes': total}
    (root / 'publication-verification.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
