
from .latus.test import test_latus

def setUpPackage():
    tl = test_latus.test_latus()
    tl.write_files()

def tearDownPackage():
    tl = test_latus.test_latus()
    tl.clean()