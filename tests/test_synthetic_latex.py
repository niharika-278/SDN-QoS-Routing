import re
import unittest
from pathlib import Path

from synthetic_demo.analyze_synthetic_data import analysis_artifact_names


ROOT = Path(__file__).resolve().parents[1]
TEX = ROOT / "synthetic_demo" / "illustrative_results_section.tex"


class SyntheticLatexTests(unittest.TestCase):
    def test_fragment_structure_and_artifact_references(self):
        text = TEX.read_text(encoding="utf-8")
        self.assertIn("SYNTHETIC / ILLUSTRATIVE --- NOT MEASURED", text)
        self.assertEqual(text.count("{"), text.count("}"))
        stack = []
        for token in re.finditer(r"\\(begin|end)\{([^}]+)\}", text):
            kind, environment = token.groups()
            if kind == "begin":
                stack.append(environment)
            else:
                self.assertTrue(stack, f"unmatched end environment: {environment}")
                self.assertEqual(stack.pop(), environment)
        self.assertFalse(stack, f"unclosed environments: {stack}")
        labels = set(re.findall(r"\\label\{([^}]+)\}", text))
        references = set(re.findall(r"\\(?:ref|eqref)\{([^}]+)\}", text))
        self.assertTrue(labels)
        self.assertTrue(references)
        self.assertTrue(references <= labels)
        for artifact in analysis_artifact_names():
            if artifact.endswith(".svg"):
                self.assertIn(artifact.replace("_", r"\_"), text, artifact)
        self.assertIn("No Mininet traffic experiment", text)
        self.assertIn("not empirical evidence", text)
        self.assertNotIn("statistically significant", text.lower())

    def test_no_main_manuscript_insertion(self):
        manuscript = (ROOT / "Niharika_2427030375_C2.tex").read_text(encoding="utf-8")
        self.assertNotIn("illustrative_results_section", manuscript)


if __name__ == "__main__":
    unittest.main()
