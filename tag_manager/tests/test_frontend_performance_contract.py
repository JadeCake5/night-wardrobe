import unittest
import os

class TestFrontendPerformanceContract(unittest.TestCase):
    def setUp(self):
        self.worktree_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.style_css = os.path.join(self.worktree_dir, 'static', 'style.css')
        self.base_html = os.path.join(self.worktree_dir, 'templates', 'base.html')
        self.manga_html = os.path.join(self.worktree_dir, 'templates', 'manga.html')
        self.video_decrypt_html = os.path.join(self.worktree_dir, 'templates', 'video_decrypt.html')
        self.gallery_html = os.path.join(self.worktree_dir, 'templates', 'gallery.html')
        self.workshop_html = os.path.join(self.worktree_dir, 'templates', 'workshop.html')
        self.characters_html = os.path.join(self.worktree_dir, 'templates', 'characters.html')
        self.loras_html = os.path.join(self.worktree_dir, 'templates', 'loras.html')

    def test_css_contracts(self):
        with open(self.style_css, 'r', encoding='utf-8') as f:
            content = f.read()
        
        self.assertTrue('display: none;' in content.split('.nav-loading {')[1].split('}')[0])
        self.assertTrue('display: none;' in content.split('.manga-drawer-mask {')[1].split('}')[0])
        self.assertTrue('display: none;' in content.split('.manga-drawer {')[1].split('}')[0])
        self.assertTrue('display: none;' in content.split('.update-toast {')[1].split('}')[0])
        self.assertTrue('pointer-events: none;' in content.split('.image-select {')[1].split('}')[0])

    def test_manga_polling_contract(self):
        with open(self.manga_html, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('function startPollingIfNeeded()', content)
        self.assertIn('window.__wardrobePageCleanup', content)
        self.assertIn('document.removeEventListener(\'keydown\'', content)

    def test_video_decrypt_polling_contract(self):
        with open(self.video_decrypt_html, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('function startPollingIfNeeded()', content)

    def test_gallery_cleanup_contract(self):
        with open(self.gallery_html, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('window.__wardrobePageCleanup', content)
        self.assertIn('document.removeEventListener(\'keydown\'', content)

    def test_workshop_cleanup_contract(self):
        with open(self.workshop_html, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('window.WorkshopAPI = undefined;', content)
        self.assertIn('window.__wardrobePageCleanup = null;', content)
        self.assertIn('if (document.readyState === \'complete\') {', content)

    def test_spa导航契约_取消序号防抖与heavy声明式检测(self):
        with open(self.base_html, 'r', encoding='utf-8') as f:
            content = f.read()
        # AbortController 取消旧 fetch + 导航序号丢弃晚到旧响应
        self.assertIn('AbortController', content)
        self.assertIn('navSeq', content)
        self.assertIn("'superseded'", content)
        # 导航进行中忽略同链接重复点击
        self.assertIn('navBusyUrl', content)
        # heavy 改声明式 data-heavy，不再全树扫描
        self.assertIn('data-heavy', content)
        self.assertIn("hasAttribute('data-heavy')", content)
        self.assertNotIn("querySelectorAll('*')", content)

    def test大列表模板声明dataheavy(self):
        for path in (self.gallery_html, self.characters_html, self.loras_html,
                     os.path.join(self.worktree_dir, 'templates', 'tags.html'),
                     os.path.join(self.worktree_dir, 'templates', 'workflows.html')):
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            self.assertIn('{% block main_attrs %} data-heavy{% endblock %}', content, path)

    def test_gallery详情按需加载契约(self):
        with open(self.gallery_html, 'r', encoding='utf-8') as f:
            content = f.read()
        # 不再内联全部 200 条详情大对象
        self.assertNotIn('galleryData', content)
        # Lightbox 打开时按 id 请求单条详情
        self.assertIn("fetch('/api/gallery/' + id)", content)
        self.assertIn('lightboxRequestId', content)

    def test_characters与loras加载更多结构(self):
        with open(self.characters_html, 'r', encoding='utf-8') as f:
            chars = f.read()
        self.assertIn('id="loadMoreChars"', chars)
        self.assertIn("/api/characters/page", chars)
        self.assertIn('charCardHTML', chars)
        with open(self.loras_html, 'r', encoding='utf-8') as f:
            loras = f.read()
        self.assertIn('id="loadMoreLoras"', loras)
        self.assertIn("/api/loras/page", loras)
        self.assertIn('loraCardHTML', loras)
        # 追加批次后只渲染新片段的标签频率
        self.assertIn('renderLoraTagFreq(grid)', loras)

if __name__ == '__main__':
    unittest.main()
