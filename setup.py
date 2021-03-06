
import distutils
import py2exe

distutils.core.setup(
    console=['sync.py'],

    name="latus sync",
    version="0.0",
    author='James Abel',
    author_email='j@abel.co',
    url='www.lat.us',
    license='LICENSE', # points to the actual file
    description="secure sync",

    # make a single executable
    # PyQt version:
    # options = {'py2exe': {'bundle_files': 1, 'compressed': True, "includes" : ["sip", "PyQt5.QtGui", "PyQt5.QtCore"]}},
    options={'py2exe': {'bundle_files': 1, 'compressed': True, }},

    zipfile = None,
)
