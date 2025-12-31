import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class SmokeTest(unittest.TestCase):
    def test_required_files(self):
        required = ['invoice_automation.py', 'invoices']
        missing = [p for p in (ROOT / r for r in required) if not p.exists()]
        self.assertFalse(missing, f"Missing: {', '.join(str(p) for p in missing)}")

if __name__ == '__main__':
    unittest.main()
