#!/usr/bin/env python3
"""Export a validated paper collection as a static reader and release downloads."""
from pathlib import Path
import argparse, base64, concurrent.futures, hashlib, html, json, re, shutil, zipfile


def load(path):
    return json.loads(path.read_text())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--downloads', type=Path, required=True)
    p.add_argument('--owner', default='GreyNails')
    p.add_argument('--repo', default='kn-paper-library')
    a = p.parse_args()
    source = a.source.resolve()
    repo = Path(__file__).resolve().parents[1]
    site = repo / 'site'
    validation = load(source / 'qa/document-validation.json')
    assert validation['status'] == 'passed' and validation['counts'] == {'passed': 257}
    result = load(source / '处理结果.json')
    release = f'https://github.com/{a.owner}/{a.repo}/releases/download/'
    homepage = f'https://{a.owner.lower()}.github.io/{a.repo}/'
    videos = load(source / 'manifest.json')['videos']
    papers = {x.stem: load(x) for x in sorted((source / 'originals').glob('*.json'))}
    source_links = {x['pdf_path']: (release + 'v1.0.0-papers/' + key + '.pdf'
                    if x.get('document_type') == 'web' else x['pdf_url'].replace('http://', 'https://', 1))
                    for key, x in papers.items()}
    a.downloads.mkdir(parents=True, exist_ok=True)
    archive_groups = []
    current, size = [], 0
    for key, item in papers.items():
        n = (source / item['pdf_path']).stat().st_size
        if current and size + n > 650 * 1024**2:
            archive_groups.append(current)
            current, size = [], 0
        current.append(key)
        size += n
    if current:
        archive_groups.append(current)
    archive_links = {}
    archive_records = []
    for index, keys in enumerate(archive_groups, 1):
        name = f'originals-{index:02d}.zip'
        with zipfile.ZipFile(a.downloads / name, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as z:
            for key in keys:
                item = papers[key]
                z.write(source / item['pdf_path'], key + '.pdf')
                archive_links[key] = release + 'v1.0.0-papers/' + name
            z.writestr('目录.json', json.dumps([{'key': k, 'title': papers[k]['title'],
                         'sha256': papers[k]['sha256'], 'filename': k + '.pdf',
                         'source_url': papers[k]['source_url']} for k in keys], ensure_ascii=False, indent=2))
        archive_records.append({'name': name, 'papers': len(keys), 'bytes': (a.downloads / name).stat().st_size})
    (site / '.nojekyll').write_text('')
    all_images = []

    def rewrite_papers(body):
        for local, remote in source_links.items():
            body = body.replace('href="../../' + local + '"', 'href="' + remote + '"')
        return body.replace('本地完整 PDF', '下载完整 PDF')

    def one_video(v):
        vid = v['video_id']
        directory = source / 'documents' / vid
        content = load(directory / 'content.json')
        audit = load(directory / 'audit.json')
        raw = load(source / 'transcripts' / (vid + '.json'))
        original_html = (directory / '阅读文档.html').read_text()
        frames = []
        for section in content['sections']:
            path = Path(section['image_path'])
            destination = site / 'assets' / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            data = (source / path).read_bytes()
            if not destination.exists() or sha(destination.read_bytes()) != sha(data):
                destination.write_bytes(data)
            frames.append({'src': '../../assets/' + path.as_posix(), 'path': 'assets/' + path.as_posix(),
                           'sha256': sha(data), 'slide_index': section['slide_index']})
        iterator = iter(frames)
        def image_match(m):
            frame = next(iterator)
            assert sha(base64.b64decode(m.group(1))) == frame['sha256']
            return 'src="' + frame['src'] + '"'
        body, count = re.subn(r'src="data:image/[^;]+;base64,([^"]+)"', image_match, original_html)
        assert count == len(frames)
        notes = content.get('audio_review_notes', [])
        audio_iterator = iter(notes)
        def audio_match(m):
            item = next(audio_iterator)
            raw_audio = (source / item['audio_path']).read_bytes()
            assert base64.b64decode(m.group(1)) == raw_audio
            destination = site / 'assets' / item['audio_path']
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw_audio)
            return 'src="../../assets/' + item['audio_path'] + '"'
        body, audio_count = re.subn(r'src="data:audio/[^;]+;base64,([^"]+)"', audio_match, body)
        assert audio_count == len(notes)
        body = rewrite_papers(body)
        body = body.replace('<main>', '<main><p class="meta"><a href="../../">← 返回阅读库</a> · <a href="../../papers.html">原论文目录</a></p>', 1)
        zip_url = release + 'v1.0.0-documents/' + vid + '-materials.zip'
        panel = '<p class="intro"><a href="' + zip_url + '">下载完整资料包</a> · 含离线 HTML、PDF、Word、全部 PPT 画面和字幕。</p>'
        body = body.replace('<h2>原论文与材料</h2>', panel + '<h2>原论文与材料</h2>', 1)
        body = body.replace('原论文 PDF 单独保存在 paper/originals；JSON / SRT 转写记录保留在 paper/transcripts。', '原论文可从上方链接下载；完整资料包保留全文、原始逐字稿、字幕和校对记录。')
        target = site / 'reading' / vid
        target.mkdir(parents=True, exist_ok=True)
        (target / 'index.html').write_text(body)
        expected = {'video_id': vid, 'title': audit['title'], 'frames': frames,
                    'paragraphs': [p['text'] for s in content['sections'] for p in s['paragraphs']],
                    'segment_ids': [i for s in content['sections'] for p in s['paragraphs'] for i in p['segment_ids']],
                    'source_segment_ids': [s['id'] for s in raw['segments']],
                    'audio_notes': notes, 'source_transcript_sha256': audit['source_transcript_sha256']}
        save(site / 'data' / 'books' / (vid + '.json'), expected)
        offline = rewrite_papers(original_html)
        offline = offline.replace('<main>', '<main><p class="meta"><a href="' + homepage + 'reading/' + vid + '/">打开在线阅读版</a></p>', 1)
        package = a.downloads / (vid + '-materials.zip')
        with zipfile.ZipFile(package, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=3) as z:
            z.writestr('阅读文档.html', offline)
            for filename in ['阅读文档.pdf', '阅读文档.docx']:
                z.write(directory / filename, filename)
            z.write(source / 'slides' / vid / '全部讲解画面.pdf', '全部PPT画面.pdf')
            for extension, name in [('txt', '原始逐字稿.txt'), ('srt', '字幕.srt')]:
                z.write(source / 'transcripts' / (vid + '.' + extension), name)
            edits = load(source / 'edited_transcripts' / (vid + '.json'))
            z.writestr('校对记录.json', json.dumps({'video_id': vid, 'method': edits['method'],
                       'source_sha256': edits['source_sha256'], 'changes': edits['changes']}, ensure_ascii=False, indent=2))
            z.writestr('原论文链接.json', json.dumps([{'title': papers[k]['title'],
                       'source_url': papers[k]['source_url'], 'download': source_links[papers[k]['pdf_path']],
                       'offline_archive': archive_links[k]}
                       for k in content['papers']], ensure_ascii=False, indent=2))
            for note in notes:
                z.write(source / note['audio_path'], note['audio_path'])
        assert package.stat().st_size < 2 * 1024**3
        return {'video_id': vid, 'title': audit['title'], 'original_title': v['title'],
                'category': v['category'], 'duration_seconds': v['duration'],
                'slides': audit['slides'], 'characters': audit['characters'],
                'cover': frames[0]['path'], 'url': 'reading/' + vid + '/', 'download': zip_url,
                'papers': content['papers'], 'frames': frames}

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        catalog = list(pool.map(one_video, videos))
    for row in catalog:
        all_images.extend(row.pop('frames'))
    assert len(all_images) == 17881
    save(site / 'data/catalog.json', catalog)
    public_papers = [{'key': key, 'title': x['title'], 'source_url': x['source_url'],
                      'download': source_links[x['pdf_path']], 'pages': x['pages'],
                      'document_type': x.get('document_type', 'paper'), 'video_ids': x['video_ids'],
                      'sha256': x['sha256'], 'archive_download': archive_links[key]}
                     for key, x in papers.items()]
    save(site / 'data/papers.json', public_papers)
    save(site / 'data/collection.json', {k: result[k] for k in ['video_count', 'duration_hours', 'speech_segments',
         'source_characters', 'ppt_frames', 'paper_pdfs', 'official_web_archives', 'original_pages']})
    esc = html.escape
    cards = []
    for row in catalog:
        search = ' '.join([row['title'], row['original_title'], row['category']] +
                          [papers[k]['title'] + ' ' + k for k in row['papers']]).lower()
        minutes = row['duration_seconds'] / 60
        cards.append(f'<article class="card" data-category="{esc(row["category"],quote=True)}" data-search="{esc(search,quote=True)}">'
                     f'<a class="cover" href="{row["url"]}"><img src="{row["cover"]}" loading="lazy" width="640" height="360" alt="{esc(row["title"],quote=True)}"></a>'
                     f'<div class="card-body"><p class="eyebrow">{esc(row["category"])} · {row["video_id"]}</p>'
                     f'<h2><a href="{row["url"]}">{esc(row["title"])}</a></h2>'
                     f'<p class="detail">{minutes:.0f} 分钟 · {row["slides"]} 张画面 · {row["characters"]:,} 字符</p>'
                     f'<div class="actions"><a class="primary" href="{row["url"]}">开始阅读 ↗</a><a href="{row["download"]}">下载资料包</a></div></div></article>')
    categories = list(dict.fromkeys(v['category'] for v in videos))
    chips = '<button class="chip active" data-filter="all">全部 <span>257</span></button>' + ''.join(
        f'<button class="chip" data-filter="{esc(c,quote=True)}">{esc(c)} <span>{sum(v["category"]==c for v in videos)}</span></button>' for c in categories)
    page = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>KN · 论文阅读库</title><link rel="stylesheet" href="assets/library.css"><body>
<header class="top"><a class="brand" href="./">KN<span>论文阅读库</span></a><nav><a href="papers.html">原论文目录</a><a href="https://github.com/{a.owner}/{a.repo}">GitHub ↗</a></nav></header>
<main><section class="hero"><p class="eyebrow">PAPER READING COLLECTION</p><h1>把一场讲解，<br>变成随时可读的一篇。</h1><p class="lead">完整语音转写与 PPT 画面按时间对齐。保留推导、例子和实验，一边读讲解，一边看原文。</p>
<div class="stats"><div><strong>257</strong><span>篇讲解</span></div><div><strong>53.95</strong><span>小时内容</span></div><div><strong>17,881</strong><span>张原始画面</span></div><div><strong>306</strong><span>份原论文 PDF</span></div></div></section>
<section class="collection"><div class="collection-heading"><h2>从这里开始阅读</h2><p id="result-count" aria-live="polite">257 篇</p></div>
<label class="search"><span>⌕</span><input id="search" type="search" placeholder="搜索论文、模型或 arXiv 编号" aria-label="搜索论文"></label>
<div class="filters">{chips}</div><div class="grid">{''.join(cards)}</div><p id="empty" hidden>没有找到匹配的论文，试试其他关键词。</p></section>
<footer>语音自动转写并做专项术语校对；截图保持源视频分辨率。部分无法可靠辨词的位置附原音供核对。<br>完整资料包包含离线 HTML、PDF、Word、PPT 画面及字幕。原文作者与来源保留在每篇文档中。</footer></main>
<script src="assets/library.js"></script></body></html>'''
    (site / 'index.html').write_text(page)
    rows = []
    for item in sorted(public_papers, key=lambda x: x['title'].lower()):
        kind = '官方网页导出 PDF' if item['document_type'] == 'web' else '原论文 PDF'
        links = ' · '.join(f'<a href="reading/{v}/">{v}</a>' for v in item['video_ids'])
        rows.append(f'<article class="paper-row" data-search="{esc((item["title"]+" "+item["key"]).lower(),quote=True)}"><h2>{esc(item["title"])}</h2><p>{kind} · {item["pages"]} 页 · {links}</p><div class="actions"><a class="primary" href="{item["download"]}">下载完整 PDF</a><a href="{item["archive_download"]}">离线备份分卷</a><a href="{esc(item["source_url"],quote=True)}">官方来源 ↗</a></div></article>')
    (site / 'papers.html').write_text(f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>原论文目录 · KN</title><link rel="stylesheet" href="assets/library.css"><body><header class="top"><a class="brand" href="./">KN<span>论文阅读库</span></a><nav><a href="./">返回阅读库</a></nav></header><main><section class="hero compact"><p class="eyebrow">ORIGINAL PAPERS</p><h1>回到原文。</h1><p class="lead">306 份论文 PDF，4 份官方网页全文导出，共 6,904 页。不同版本分别保存，综述视频对应的多篇原文分别关联。</p></section><label class="search"><span>⌕</span><input id="search" type="search" placeholder="搜索原论文标题或编号" aria-label="搜索原论文"></label><p id="result-count" aria-live="polite">310 份原文</p><div class="paper-list">{''.join(rows)}</div><p id="empty" hidden>没有找到匹配的原文。</p><footer>网页导出是官方网页的浏览器阅读副本；论文原始 PDF 保留原文件。</footer></main><script src="assets/library.js"></script></body></html>''')
    site_bytes = sum(p.stat().st_size for p in site.rglob('*') if p.is_file())
    assert site_bytes < 950_000_000, f'Site exceeds the publishing budget: {site_bytes}'
    save(repo / 'publication-manifest.json', {'videos': 257, 'slide_images': len(all_images),
         'originals': len(papers), 'site_bytes': site_bytes, 'repository': f'{a.owner}/{a.repo}',
         'website': homepage, 'document_release': 'v1.0.0-documents', 'paper_release': 'v1.0.0-papers',
         'original_archives': archive_records})
    print(json.dumps({'videos': 257, 'slide_images': len(all_images), 'originals': len(papers),
                      'site_bytes': site_bytes, 'packages': len(list(a.downloads.glob('v*-materials.zip')))}, ensure_ascii=False))


if __name__ == '__main__':
    main()
