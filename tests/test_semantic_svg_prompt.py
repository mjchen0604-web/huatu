from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "autofigure2.py").read_text(encoding="utf-8")


class SemanticSvgPromptTests(unittest.TestCase):
    def test_gpt_only_prompt_demands_element_level_editable_svg_layers(self):
        self.assertIn("def _build_semantic_svg_prompt", SOURCE)
        self.assertIn("ELEMENT-LEVEL EDITABILITY REQUIREMENTS", SOURCE)
        self.assertIn("each visible element must be its own editable SVG element or small <g> group", SOURCE)
        self.assertIn("Do not embed the original raster image", SOURCE)
        self.assertIn("text must be real <text> elements", SOURCE)
        self.assertIn("def _looks_like_raster_only_svg", SOURCE)
        self.assertIn("重新请求 GPT 输出可编辑矢量 SVG", SOURCE)

    def test_psd_only_prompt_is_not_used_for_svg_mode(self):
        self.assertIn('psd_only: bool = False', SOURCE)
        self.assertIn('if psd_only:', SOURCE)
        self.assertIn('--psd_only', SOURCE)
        self.assertIn('GPT-only 模式', SOURCE)


if __name__ == "__main__":
    unittest.main()
