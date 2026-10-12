import unittest
from smoke import greeting

class GreetingTests(unittest.TestCase):
    def test_name(self):
        self.assertEqual(greeting("Ada"), "Hello, Ada!")

    def test_lin(self):
        self.assertEqual(greeting("Lin"), "Hello, Lin!")

    def test_surrounding_whitespace(self):
        self.assertEqual(greeting("  Ada  "), "Hello, Ada!")

    def test_blank_name(self):
        for name in ("", "   ", "\t\n"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "^name is required$"):
                    greeting(name)

if __name__ == "__main__":
    unittest.main()
