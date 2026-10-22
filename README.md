# KN · 论文阅读库

[打开在线阅读库](https://greynails.github.io/kn-paper-library/) · [原论文目录](https://greynails.github.io/kn-paper-library/papers.html) · [下载资料包](https://github.com/GreyNails/kn-paper-library/releases)

257 场论文讲解，约 54 小时内容。完整语音转写与 17,881 张 PPT、论文页及演示画面按时间对齐，保留推导、例子和实验。原论文目录收录 306 份论文 PDF 和 4 份官方网页全文导出，共 6,904 页。

在线页面支持标题、模型名、arXiv 编号搜索，以及主题筛选。每篇讲解都可下载完整资料包，包含离线 HTML、PDF、Word、全部 PPT 画面、原始逐字稿、字幕与校对记录。原文作者与来源链接保留在对应文档中。全部原论文另有 5 卷完整离线备份，可在原论文目录或 Releases 下载。

语音稿经过自动转写及专项术语校对；少量无法可靠辨词的位置附有原音。PPT 画面保持源视频分辨率，连续动画保留代表画面。

## 本地运行

只需要 Python 3.10 或更新版本：

```bash
python -m http.server 8000 --directory site
```

打开 `http://localhost:8000`。网站由静态 HTML、CSS 和 JavaScript 构成，通过 GitHub Pages 自动部署。

## 从已校验的文档重新导出

```bash
python tools/build_site.py --source /path/to/paper --downloads /path/to/downloads
python tools/verify_site.py --downloads /path/to/downloads
```

导出器仅接受已通过全量校验的原始文档集。校验器独立核对每段讲解文字、画面顺序、图片字节、页面链接及资料包完整性。当前发布统计见 `publication-manifest.json` 和 `publication-verification.json`。
