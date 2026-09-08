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

if __name__ == '__main__':
    unittest.main()
