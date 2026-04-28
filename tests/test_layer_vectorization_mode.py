from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
AUTO = (ROOT / "autofigure2.py").read_text(encoding="utf-8")
SERVER = (ROOT / "server.py").read_text(encoding="utf-8")
APP_JS = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")


class LayerVectorizationModeTests(unittest.TestCase):
    def test_autofigure_has_layer_vectorization_pipeline(self):
        self.assertIn("def vectorize_raster_layers_to_svg", AUTO)
        self.assertIn("def _vectorize_layer_png", AUTO)
        self.assertIn("PSD→矢量 SVG", AUTO)
        self.assertIn("--vectorize_layers", AUTO)
        self.assertIn("vectorize_layers: bool = False", AUTO)

    def test_server_passes_vectorize_layers_to_worker_and_artifacts(self):
        self.assertIn("vectorize_layers: Optional[bool] = False", SERVER)
        self.assertIn("if req.vectorize_layers", SERVER)
        self.assertIn("--vectorize_layers", SERVER)
        self.assertIn("vector_layer_svg", SERVER)

    def test_frontend_exposes_vector_output_mode(self):
        self.assertIn("vectorModeBtn", INDEX)
        self.assertIn("vectorModeBtn", APP_JS)
        self.assertIn('outputMode === "vector"', APP_JS)
        self.assertIn("vectorize_layers", APP_JS)
        self.assertIn("PSD→矢量 SVG", INDEX)


if __name__ == "__main__":
    unittest.main()
