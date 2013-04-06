
import unittest
import logging
import test_latus
import folder
import analyze

class test_analyze(unittest.TestCase):
    def setUp(self):
        root = test_latus.get_root()
        # Load up metadata from the root (this way we have many duplicate files, so we can make sure
        # we only get the subset in simple we're looking for).
        f = folder.folder(root, root)
        f.scan()
        self.analyze = analyze.analyze(root, root, True)

    def tearDown(self):
        del self.analyze

    def test_analyze(self):
        # check we found the right number of files
        hashes = self.analyze.run()
        # todo : figure out how to not have these constants of 2 and - 1
        self.assertEqual(len(hashes), 2) # 2 different file contents
        n_found = hashes[hashes.keys()[0]]
        t = test_latus.test_latus()
        n_files_written = t.write_files(force=True, write_flag=False)
        self.assertEqual(n_found, n_files_written - 1) # -1 since we have one other contents (different_test_string)

if __name__ == "__main__":
    unittest.main()

