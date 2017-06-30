import glob
import os
import platform
import re
import sys
import warnings

# Hack to silence atexit traceback in newer python versions.
try:
    import multiprocessing
except ImportError:
    pass

try:
    from ConfigParser import SafeConfigParser
except ImportError:
    # PY3
    from configparser import SafeConfigParser

# Don't force people to install setuptools unless
# we have to.
try:
    from setuptools import setup
    from setuptools.command.build_py import build_py
except ImportError:
    from ez_setup import use_setuptools
    use_setuptools()
    from setuptools import setup
    from setuptools.command.build_py import build_py

from distutils.command.build_ext import build_ext
from distutils.errors import CCompilerError
from distutils.errors import DistutilsPlatformError, DistutilsExecError
from distutils.core import Extension

try:
    import sphinx
    _HAVE_SPHINX = True
except ImportError:
    _HAVE_SPHINX = False

version = "2.9.5"

f = open("README.rst")
try:
    try:
        readme_content = f.read()
    except:
        readme_content = ""
finally:
    f.close()

PY3 = sys.version_info[0] == 3

# PYTHON-654 - Clang doesn't support -mno-fused-madd but the pythons Apple
# ships are built with it. This is a problem starting with Xcode 5.1
# since clang 3.4 errors out when it encounters unrecognized compiler
# flags. This hack removes -mno-fused-madd from the CFLAGS automatically
# generated by distutils for Apple provided pythons, allowing C extension
# builds to complete without error. The inspiration comes from older
# versions of distutils.sysconfig.get_config_vars.
if sys.platform == 'darwin' and 'clang' in platform.python_compiler().lower():
    from distutils.sysconfig import get_config_vars
    res = get_config_vars()
    for key in ('CFLAGS', 'PY_CFLAGS'):
        if key in res:
            flags = res[key]
            flags = re.sub('-mno-fused-madd', '', flags)
            res[key] = flags

nose_config_options = {
    'with-xunit': '1',    # Write out nosetests.xml for CI.
    'py3where': 'build',  # Tell nose where to find tests under PY3.
}

def write_nose_config():
    """Write out setup.cfg. Since py3where has to be set
    for tests to run correctly in Python 3 we create this
    on the fly.
    """
    config = SafeConfigParser()
    config.add_section('nosetests')
    for opt, val in nose_config_options.items():
        config.set('nosetests', opt, val)
    try:
        cf = open('setup.cfg', 'w')
        config.write(cf)
    finally:
        cf.close()


should_run_tests = False
if "test" in sys.argv or "nosetests" in sys.argv:
    should_run_tests = True


class doc(build_py):

    description = "generate or test documentation"

    build_py.user_options.append(
        ("test", "t", "run doctests instead of generating documentation"))

    build_py.boolean_options.append('test')

    def initialize_options(self):
        self.test = False
        build_py.initialize_options(self)

    def run(self):
        if not _HAVE_SPHINX:
            raise RuntimeError(
                "You must install Sphinx to build or test the documentation.")

        if PY3:
            import doctest
            from doctest import OutputChecker as _OutputChecker

            # Match u or U (possibly followed by r or R), removing it.
            # r/R can follow u/U but not precede it. Don't match the
            # single character string 'u' or 'U'.
            _u_literal_re = re.compile(
                r"(\W|^)(?<![\'\"])[uU]([rR]?[\'\"])", re.UNICODE)
            # Match b or B (possibly followed by r or R), removing.
            # r/R can follow b/B but not precede it. Don't match the
            # single character string 'b' or 'B'.
            _b_literal_re = re.compile(
                r"(\W|^)(?<![\'\"])[bB]([rR]?[\'\"])", re.UNICODE)

            class _StringPrefixFixer(_OutputChecker):

                def check_output(self, want, got, optionflags):
                    # The docstrings are written with python 2.x in mind.
                    # To make the doctests pass in python 3 we have to
                    # strip the 'u' prefix from the expected results. The
                    # actual results won't have that prefix.
                    want = re.sub(_u_literal_re, r'\1\2', want)
                    # We also have to strip the 'b' prefix from the actual
                    # results since python 2.x expected results won't have
                    # that prefix.
                    got = re.sub(_b_literal_re, r'\1\2', got)
                    return super(
                        _StringPrefixFixer, self).check_output(
                            want, got, optionflags)

                def output_difference(self, example, got, optionflags):
                    example.want = re.sub(
                        _u_literal_re, r'\1\2', example.want)
                    got = re.sub(_b_literal_re, r'\1\2', got)
                    return super(
                        _StringPrefixFixer, self).output_difference(
                            example, got, optionflags)

            doctest.OutputChecker = _StringPrefixFixer

            # No need to run build_py for python 2.x.
            build_py.run(self)

        if self.test:
            path = os.path.join(
                os.path.abspath('.'), "doc", "_build", "doctest")
            mode = "doctest"
        else:
            path = os.path.join(
                os.path.abspath('.'), "doc", "_build", version)
            mode = "html"

            try:
                os.makedirs(path)
            except:
                pass

        sphinx_args = ["-E", "-b", mode, "doc", path]

        # sphinx.main calls sys.exit when sphinx.build_main exists.
        # Call build_main directly so we can check status and print
        # the full path to the built docs.
        if hasattr(sphinx, 'build_main'):
            status = sphinx.build_main(sphinx_args)
        else:
            status = sphinx.main(sphinx_args)

        if status:
            raise RuntimeError("documentation step '%s' failed" % (mode,))

        sys.stdout.write("\nDocumentation step '%s' performed, results here:\n"
                         "   %s/\n" % (mode, path))


if sys.platform == 'win32' and sys.version_info > (2, 6):
    # 2.6's distutils.msvc9compiler can raise an IOError when failing to
    # find the compiler
    build_errors = (CCompilerError, DistutilsExecError,
                    DistutilsPlatformError, IOError)
else:
    build_errors = (CCompilerError, DistutilsExecError, DistutilsPlatformError)


_COMPILER_ATTRS = (
    'compiler', 'compiler_so', 'compiler_cxx', 'linker_exe', 'linker_so')


# From distutils.cygwinccompiler in recent pythons.
def _is_cygwingcc():
    out = os.popen('gcc -dumpmachine', 'r')
    out_string = out.read()
    out.close()
    return out_string.strip().endswith('cygwin')


class custom_build_ext(build_ext):
    """Allow C extension building to fail.

    The C extension speeds up BSON encoding, but is not essential.
    """

    warning_message = """
********************************************************************
WARNING: %s could not
be compiled. No C extensions are essential for PyMongo to run,
although they do result in significant speed improvements.
%s

Please see the installation docs for solutions to build issues:

http://api.mongodb.org/python/current/installation.html

Here are some hints for popular operating systems:

If you are seeing this message on Linux you probably need to
install GCC and/or the Python development package for your
version of Python.

Debian and Ubuntu users should issue the following command:

    $ sudo apt-get install build-essential python-dev

Users of Red Hat based distributions (RHEL, CentOS, Amazon Linux,
Oracle Linux, Fedora, etc.) should issue the following command:

    $ sudo yum install gcc python-devel

If you are seeing this message on Microsoft Windows please install
PyMongo using the MS Windows installer for your version of Python,
available on pypi here:

http://pypi.python.org/pypi/pymongo/#downloads

If you are seeing this message on OSX please read the documentation
here:

http://api.mongodb.org/python/current/installation.html#osx
********************************************************************
"""

    def run(self):
        try:
            build_ext.run(self)
        except DistutilsPlatformError:
            e = sys.exc_info()[1]
            sys.stdout.write('%s\n' % str(e))
            warnings.warn(self.warning_message % ("Extension modules",
                                                  "There was an issue with "
                                                  "your platform configuration"
                                                  " - see above."))

    def set_nose_options(self):
        # Under python 3 we need to tell nose where to find the
        # proper tests. if we built the C extensions this will be
        # someplace like build/lib.<os>-<arch>-<python version>
        if PY3:
            ver = '.'.join(map(str, sys.version_info[:2]))
            lib_dirs = glob.glob(os.path.join('build', 'lib*' + ver))
            if lib_dirs:
                nose_config_options['py3where'] = lib_dirs[0]
        write_nose_config()

    def build_extension(self, ext):
        # http://bugs.python.org/issue12641
        # This makes a number of well researched assumptions about distutils
        # but is written in a defensive style to guard against those
        # assumptions failing.
        compiler = getattr(self, "compiler", None)
        if compiler and getattr(compiler, "compiler_type", None) == "mingw32":
            try:
                from distutils import cygwinccompiler
            except ImportError:
                pass
            else:
                # If cygwinccompiler.is_cygwingcc exists the problem is
                # already solved for us.
                if not hasattr(cygwinccompiler, "is_cygwingcc"):
                    gcc_version = getattr(compiler, "gcc_version", None)
                    # If gcc_version is None assume we need to strip
                    # -mno-cygwin.
                    if (not _is_cygwingcc() and
                            (not gcc_version or gcc_version >= "4.6")):
                        for att in [getattr(compiler, attrname)
                                    for attrname in _COMPILER_ATTRS
                                    if hasattr(compiler, attrname)]:
                            if isinstance(att, list) and '-mno-cygwin' in att:
                                att.remove('-mno-cygwin')

        name = ext.name
        if sys.version_info[:3] >= (2, 4, 0):
            try:
                build_ext.build_extension(self, ext)
                if should_run_tests:
                    self.set_nose_options()
            except build_errors:
                e = sys.exc_info()[1]
                sys.stdout.write('%s\n' % str(e))
                warnings.warn(self.warning_message % ("The %s extension "
                                                      "module" % (name,),
                                                      "The output above "
                                                      "this warning shows how "
                                                      "the compilation "
                                                      "failed."))
        else:
            warnings.warn(self.warning_message % ("The %s extension "
                                                  "module" % (name,),
                                                  "Please use Python >= 2.4 "
                                                  "to take advantage of the "
                                                  "extension."))

ext_modules = [Extension('bson._cbson',
                         include_dirs=['bson'],
                         sources=['bson/_cbsonmodule.c',
                                  'bson/time64.c',
                                  'bson/buffer.c',
                                  'bson/encoding_helpers.c']),
               Extension('pymongo._cmessage',
                         include_dirs=['bson'],
                         sources=['pymongo/_cmessagemodule.c',
                                  'bson/buffer.c'])]

extra_opts = {
    "packages": ["bson", "pymongo", "gridfs"],
    "test_suite": "nose.collector"
}
if "--no_ext" in sys.argv:
    sys.argv.remove("--no_ext")
elif (sys.platform.startswith("java") or
      sys.platform == "cli" or
      "PyPy" in sys.version):
    sys.stdout.write("""
*****************************************************\n
The optional C extensions are currently not supported\n
by this python implementation.\n
*****************************************************\n
""")
elif sys.byteorder == "big":
    sys.stdout.write("""
*****************************************************\n
The optional C extensions are currently not supported\n
on big endian platforms and will not be built.\n
Performance may be degraded.\n
*****************************************************\n
""")
else:
    extra_opts['ext_modules'] = ext_modules

# The nosetests command requires nose be available, otherwise the xunit
# plugin will not work.
# Note: projects listed in setup_requires will NOT be automatically installed
# on the system where the setup script is being run. They are simply
# downloaded to the ./.eggs directory if they're not locally available
# already.
# See:
# https://nose.readthedocs.io/en/latest/api/commands.html#bootstrapping
# https://nose.readthedocs.io/en/latest/setuptools_integration.html
# https://setuptools.readthedocs.io/en/latest/setuptools.html#new-and-changed-setup-keywords
if "nosetests" in sys.argv:
    extra_opts["setup_requires"] = ["nose"]

if PY3:
    extra_opts["use_2to3"] = True
    if should_run_tests:
        # Distribute isn't smart enough to copy the
        # tests and run 2to3 on them. We don't want to
        # install the test suite so only do this if we
        # are testing.
        # https://bitbucket.org/tarek/distribute/issue/233
        extra_opts["packages"].append("test")
        extra_opts['package_data'] = {"test": ["certificates/ca.pem",
                                               "certificates/client.pem"]}
        # Hack to make "python3.x setup.py nosetests" work in python 3
        # otherwise it won't run 2to3 before running the tests.
        if "nosetests" in sys.argv:
            sys.argv.remove("nosetests")
            sys.argv.append("test")
            # All "nosetests" does is import and run nose.main.
            extra_opts["test_suite"] = "nose.main"

# This may be called a second time if
# we are testing with C extensions.
if should_run_tests:
    write_nose_config()

setup(
    name="pymongo",
    version=version,
    description="Python driver for MongoDB <http://www.mongodb.org>",
    long_description=readme_content,
    author="Mike Dirolf",
    author_email="mongodb-user@googlegroups.com",
    maintainer="Bernie Hackett",
    maintainer_email="bernie@mongodb.com",
    url="http://github.com/mongodb/mongo-python-driver",
    keywords=["mongo", "mongodb", "pymongo", "gridfs", "bson"],
    install_requires=[],
    license="Apache License, Version 2.0",
    tests_require=["nose"],
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: Microsoft :: Windows",
        "Operating System :: POSIX",
        "Programming Language :: Python :: 2",
        "Programming Language :: Python :: 2.4",
        "Programming Language :: Python :: 2.5",
        "Programming Language :: Python :: 2.6",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.1",
        "Programming Language :: Python :: 3.2",
        "Programming Language :: Python :: 3.3",
        "Programming Language :: Python :: 3.4",
        "Programming Language :: Python :: 3.5",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: Implementation :: CPython",
        "Programming Language :: Python :: Implementation :: Jython",
        "Programming Language :: Python :: Implementation :: PyPy",
        "Topic :: Database"],
    cmdclass={"build_ext": custom_build_ext,
              "doc": doc},
    **extra_opts
)
