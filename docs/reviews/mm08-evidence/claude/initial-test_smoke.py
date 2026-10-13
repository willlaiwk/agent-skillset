import unittest
from smoke import greeting

class GreetingTests(unittest.TestCase):
    def test_name(self):
        self.assertEqual(greeting("Ada"), "Hello, Ada!")

    def test_name_lin(self):
        self.assertEqual(greeting("Lin"), "Hello, Lin!")

if __name__ == "__main__":
    unittest.main()
