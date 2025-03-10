"""distutils.cygwinccompiler

Provides the CygwinCCompiler class, a subclass of UnixCCompiler that
handles the Cygwin port of the GNU C compiler to Windows.  It also contains
the Mingw32CCompiler class which handles the mingw32 port of GCC (same as
cygwin in no-cygwin mode).
"""

# problems:
#
# * if you use a msvc compiled python version (1.5.2)
#   1. you have to insert a __GNUC__ section in its config.h
#   2. you have to generate an import library for its dll
#      - create a def-file for python??.dll
#      - create an import library using
#             dlltool --dllname python15.dll --def python15.def \
#                       --output-lib libpython15.a
#
#   see also http://starship.python.net/crew/kernr/mingw32/Notes.html
#
# * We put export_symbols in a def-file, and don't use
#   --export-all-symbols because it doesn't worked reliable in some
#   tested configurations. And because other windows compilers also
#   need their symbols specified this no serious problem.
#
# tested configurations:
#
# * cygwin gcc 2.91.57/ld 2.9.4/dllwrap 0.2.4 works
#   (after patching python's config.h and for C++ some other include files)
#   see also http://starship.python.net/crew/kernr/mingw32/Notes.html
# * mingw32 gcc 2.95.2/ld 2.9.4/dllwrap 0.2.4 works
#   (ld doesn't support -shared, so we use dllwrap)
# * cygwin gcc 2.95.2/ld 2.10.90/dllwrap 2.10.90 works now
#   - its dllwrap doesn't work, there is a bug in binutils 2.10.90
#     see also http://sources.redhat.com/ml/cygwin/2000-06/msg01274.html
#   - using gcc -mdll instead dllwrap doesn't work without -static because
#     it tries to link against dlls instead their import libraries. (If
#     it finds the dll first.)
#     By specifying -static we force ld to link against the import libraries,
#     this is windows standard and there are normally not the necessary symbols
#     in the dlls.
#   *** only the version of June 2000 shows these problems
# * cygwin gcc 3.2/ld 2.13.90 works
#   (ld supports -shared)
# * mingw gcc 3.2/ld 2.13 works
#   (ld supports -shared)

# This module should be kept compatible with Python 2.1.

__revision__ = "$Id$"

import os,sys,copy
from distutils.ccompiler import gen_preprocess_options, gen_lib_options
from distutils.unixccompiler import UnixCCompiler
from distutils.file_util import write_file
from distutils.errors import DistutilsExecError, CompileError, UnknownFileError
from distutils import log

def get_msvcr():
    """Include the appropriate MSVC runtime library if Python was built
    with MSVC 7.0 or later.
    """
    msc_pos = sys.version.find('MSC v.')
    if msc_pos != -1:
        msc_ver = sys.version[msc_pos+6:msc_pos+10]
        if msc_ver == '1300':
            # MSVC 7.0
            return ['msvcr70']
        elif msc_ver == '1310':
            # MSVC 7.1
            return ['msvcr71']
        elif msc_ver == '1400':
            # VS2005 / MSVC 8.0
            return ['msvcr80']
        elif msc_ver == '1500':
            # VS2008 / MSVC 9.0
            return ['msvcr90']
        else:
            raise ValueError("Unknown MS Compiler version %s " % msc_ver)


class CygwinCCompiler (UnixCCompiler):

    compiler_type = 'cygwin'
    obj_extension = ".o"
    static_lib_extension = ".a"
    shared_lib_extension = ".dll"
    dylib_lib_extension = ".dll.a"
    static_lib_format = "lib%s%s"
    shared_lib_format = "%s%s"
    exe_extension = ".exe"

    def __init__ (self, verbose=0, dry_run=0, force=0):

        UnixCCompiler.__init__ (self, verbose, dry_run, force)

        (status, details) = check_config_h()
        self.debug_print("Python's GCC status: %s (details: %s)" %
                         (status, details))
        if status is not CONFIG_H_OK:
            self.warn(
                "Python's pyconfig.h doesn't seem to support your compiler. "
                "Reason: %s. "
                "Compiling may fail because of undefined preprocessor macros."
                % details)

        self.gcc_version, self.ld_version, self.dllwrap_version = \
            get_versions()
        self.debug_print(self.compiler_type + ": gcc %s, ld %s, dllwrap %s\n" %
                         (self.gcc_version,
                          self.ld_version,
                          self.dllwrap_version) )

        # ld_version >= "2.10.90" and < "2.13" should also be able to use
        # gcc -mdll instead of dllwrap
        # Older dllwraps had own version numbers, newer ones use the
        # same as the rest of binutils ( also ld )
        # dllwrap 2.10.90 is buggy
        if self.ld_version >= "2.10.90":
            self.linker_dll = "gcc"
        else:
            self.linker_dll = "dllwrap"

        # ld_version >= "2.13" support -shared so use it instead of
        # -mdll -static
        if self.ld_version >= "2.13":
            shared_option = "-shared"
        else:
            shared_option = "-mdll -static"

        # Hard-code GCC because that's what this is all about.
        # XXX optimization, warnings etc. should be customizable.
        self.set_executables(compiler='gcc -mcygwin -O -Wall',
                             compiler_so='gcc -mcygwin -mdll -O -Wall',
                             compiler_cxx='g++ -mcygwin -O -Wall',
                             linker_exe='gcc -mcygwin',
                             linker_so=('%s -mcygwin %s' %
                                        (self.linker_dll, shared_option)))

        # cygwin and mingw32 need different sets of libraries
        if self.gcc_version == "2.91.57":
            # cygwin shouldn't need msvcrt, but without the dlls will crash
            # (gcc version 2.91.57) -- perhaps something about initialization
            self.dll_libraries=["msvcrt"]
            self.warn(
                "Consider upgrading to a newer version of gcc")
        else:
            # Include the appropriate MSVC runtime library if Python was built
            # with MSVC 7.0 or later.
            self.dll_libraries = get_msvcr()

    # __init__ ()


    def _compile(self, obj, src, ext, cc_args, extra_postargs, pp_opts):
        if ext == '.rc' or ext == '.res':
            # gcc needs '.res' and '.rc' compiled to object files !!!
            try:
                self.spawn(["windres", "-i", src, "-o", obj])
            except DistutilsExecError, msg:
                raise CompileError, msg
        else: # for other files use the C-compiler
            try:
                self.spawn(self.compiler_so + cc_args + [src, '-o', obj] +
                           extra_postargs)
            except DistutilsExecError, msg:
                raise CompileError, msg

    def link (self,
              target_desc,
              objects,
              output_filename,
              output_dir=None,
              libraries=None,
              library_dirs=None,
              runtime_library_dirs=None,
              export_symbols=None,
              debug=0,
              extra_preargs=None,
              extra_postargs=None,
              build_temp=None,
              target_lang=None):

        # use separate copies, so we can modify the lists
        extra_preargs = copy.copy(extra_preargs or [])
        libraries = copy.copy(libraries or [])
        objects = copy.copy(objects or [])

        # Additional libraries
        libraries.extend(self.dll_libraries)

        # handle export symbols by creating a def-file
        # with executables this only works with gcc/ld as linker
        if ((export_symbols is not None) and
            (target_desc != self.EXECUTABLE or self.linker_dll == "gcc")):
            # (The linker doesn't do anything if output is up-to-date.
            # So it would probably better to check if we really need this,
            # but for this we had to insert some unchanged parts of
            # UnixCCompiler, and this is not what we want.)

            # we want to put some files in the same directory as the
            # object files are, build_temp doesn't help much
            # where are the object files
            temp_dir = os.path.dirname(objects[0])
            # name of dll to give the helper files the same base name
            (dll_name, dll_extension) = os.path.splitext(
                os.path.basename(output_filename))

            # generate the filenames for these files
            def_file = os.path.join(temp_dir, dll_name + ".def")
            lib_file = os.path.join(temp_dir, 'lib' + dll_name + ".a")

            # Generate .def file
            contents = [
                "LIBRARY %s" % os.path.basename(output_filename),
                "EXPORTS"]
            for sym in export_symbols:
                contents.append(sym)
            self.execute(write_file, (def_file, contents),
                         "writing %s" % def_file)

            # next add options for def-file and to creating import libraries

            # dllwrap uses different options than gcc/ld
            if self.linker_dll == "dllwrap":
                extra_preargs.extend(["--output-lib", lib_file])
                # for dllwrap we have to use a special option
                extra_preargs.extend(["--def", def_file])
            # we use gcc/ld here and can be sure ld is >= 2.9.10
            else:
                # doesn't work: bfd_close build\...\libfoo.a: Invalid operation
                #extra_preargs.extend(["-Wl,--out-implib,%s" % lib_file])
                # for gcc/ld the def-file is specified as any object files
                objects.append(def_file)

        #end: if ((export_symbols is not None) and
        #        (target_desc != self.EXECUTABLE or self.linker_dll == "gcc")):

        # who wants symbols and a many times larger output file
        # should explicitly switch the debug mode on
        # otherwise we let dllwrap/ld strip the output file
        # (On my machine: 10KB < stripped_file < ??100KB
        #   unstripped_file = stripped_file + XXX KB
        #  ( XXX=254 for a typical python extension))
        if not debug:
            extra_preargs.append("-s")

        UnixCCompiler.link(self,
                           target_desc,
                           objects,
                           output_filename,
                           output_dir,
                           libraries,
                           library_dirs,
                           runtime_library_dirs,
                           None, # export_symbols, we do this in our def-file
                           debug,
                           extra_preargs,
                           extra_postargs,
                           build_temp,
                           target_lang)

    # link ()

    # -- Miscellaneous methods -----------------------------------------

    # overwrite the one from CCompiler to support rc and res-files
    def object_filenames (self,
                          source_filenames,
                          strip_dir=0,
                          output_dir=''):
        if output_dir is None: output_dir = ''
        obj_names = []
        for src_name in source_filenames:
            base, ext = os.path.splitext(src_name)
            # use 'normcase' only for resource suffixes
            ext_normcase = os.path.normcase(ext)
            if ext_normcase in ['.rc','.res']:
                ext = ext_normcase
            if ext not in (self.src_extensions + ['.rc','.res']):
                raise UnknownFileError, \
                      "unknown file type '%s' (from '%s')" % \
                      (ext, src_name)
            base = os.path.splitdrive(base)[1] # Chop off the drive
            base = base[os.path.isabs(base):]  # If abs, chop off leading /
            if strip_dir:
                base = os.path.basename (base)
            if ext == '.res' or ext == '.rc':
                # these need to be compiled to object files
                obj_names.append (os.path.join (output_dir,
                                            base + ext + self.obj_extension))
            else:
                obj_names.append (os.path.join (output_dir,
                                            base + self.obj_extension))
        return obj_names

    # object_filenames ()

# class CygwinCCompiler


# the same as cygwin plus some additional parameters
class Mingw32CCompiler (CygwinCCompiler):

    compiler_type = 'mingw32'

    def __init__ (self,
                  verbose=0,
                  dry_run=0,
                  force=0):

        CygwinCCompiler.__init__ (self, verbose, dry_run, force)

        # ld_version >= "2.13" support -shared so use it instead of
        # -mdll -static
        if self.ld_version >= "2.13":
            shared_option = "-shared"
        else:
            shared_option = "-mdll -static"

        # A real mingw32 doesn't need to specify a different entry point,
        # but cygwin 2.91.57 in no-cygwin-mode needs it.
        if self.gcc_version <= "2.91.57":
            entry_point = '--entry _DllMain@12'
        else:
            entry_point = ''

        if self.gcc_version < '4' or is_cygwingcc():
            no_cygwin = ' -mno-cygwin'
        else:
            no_cygwin = ''

        self.set_executables(compiler='gcc%s -O2 -Wall' % no_cygwin,
                             compiler_so='gcc%s -mdll -O2 -Wall' % no_cygwin,
                             compiler_cxx='g++%s -O2 -Wall' % no_cygwin,
                             linker_exe='gcc%s' % no_cygwin,
                             linker_so='%s%s %s %s'
                                    % (self.linker_dll, no_cygwin,
                                       shared_option, entry_point))
        # Maybe we should also append -mthreads, but then the finished
        # dlls need another dll (mingwm10.dll see Mingw32 docs)
        # (-mthreads: Support thread-safe exception handling on `Mingw32')

        # no additional libraries needed
        self.dll_libraries=[]

        # Include the appropriate MSVC runtime library if Python was built
        # with MSVC 7.0 or later.
        self.dll_libraries = get_msvcr() or []

    # __init__ ()

# class Mingw32CCompiler

# Because these compilers aren't configured in Python's pyconfig.h file by
# default, we should at least warn the user if he is using an unmodified
# version.

CONFIG_H_OK = "ok"
CONFIG_H_NOTOK = "not ok"
CONFIG_H_UNCERTAIN = "uncertain"

def check_config_h():

    """Check if the current Python installation (specifically, pyconfig.h)
    appears amenable to building extensions with GCC.  Returns a tuple
    (status, details), where 'status' is one of the following constants:
      CONFIG_H_OK
        all is well, go ahead and compile
      CONFIG_H_NOTOK
        doesn't look good
      CONFIG_H_UNCERTAIN
        not sure -- unable to read pyconfig.h
    'details' is a human-readable string explaining the situation.

    Note there are two ways to conclude "OK": either 'sys.version' contains
    the string "GCC" (implying that this Python was built with GCC), or the
    installed "pyconfig.h" contains the string "__GNUC__".
    """

    # XXX since this function also checks sys.version, it's not strictly a
    # "pyconfig.h" check -- should probably be renamed...

    from distutils import sysconfig
    import string
    # if sys.version contains GCC then python was compiled with
    # GCC, and the pyconfig.h file should be OK
    if string.find(sys.version,"GCC") >= 0:
        return (CONFIG_H_OK, "sys.version mentions 'GCC'")

    fn = sysconfig.get_config_h_filename()
    try:
        # It would probably better to read single lines to search.
        # But we do this only once, and it is fast enough
        f = open(fn)
        try:
            s = f.read()
        finally:
            f.close()

    except IOError, exc:
        # if we can't read this file, we cannot say it is wrong
        # the compiler will complain later about this file as missing
        return (CONFIG_H_UNCERTAIN,
                "couldn't read '%s': %s" % (fn, exc.strerror))

    else:
        # "pyconfig.h" contains an "#ifdef __GNUC__" or something similar
        if string.find(s,"__GNUC__") >= 0:
            return (CONFIG_H_OK, "'%s' mentions '__GNUC__'" % fn)
        else:
            return (CONFIG_H_NOTOK, "'%s' does not mention '__GNUC__'" % fn)



def get_versions():
    """ Try to find out the versions of gcc, ld and dllwrap.
        If not possible it returns None for it.
    """
    from distutils.version import LooseVersion
    from distutils.spawn import find_executable
    import re

    gcc_exe = os.environ.get('CC') or find_executable('gcc')
    ld_exe = os.environ.get('LD') or find_executable('ld')
    if gcc_exe:
        out = os.popen(gcc_exe + ' -dumpversion','r')
        out_string = out.read()
        out.close()
        result = re.search('(\d+\.\d+(\.\d+)*)',out_string)
        if result:
            gcc_version = LooseVersion(result.group(1))
        else:
            gcc_version = None
        out = os.popen(gcc_exe + ' --print-prog-name ld','r')
        ld_exe = out.read().decode('ascii').split()[0]
        out.close()
    else:
        gcc_version = None
    if ld_exe:
        out = os.popen(ld_exe + ' -v','r')
        out_string = out.read()
        out.close()
        result = re.search('(\d+\.\d+(\.\d+)*)',out_string)
        if result:
            ld_version = LooseVersion(result.group(1))
        else:
            ld_version = None
    else:
        ld_version = None
    dllwrap_exe = os.environ.get('DLLWRAP') or find_executable('dllwrap')
    if dllwrap_exe:
        out = os.popen(dllwrap_exe + ' --version','r')
        out_string = out.read()
        out.close()
        result = re.search(' (\d+\.\d+(\.\d+)*)',out_string)
        if result:
            dllwrap_version = LooseVersion(result.group(1))
        else:
            dllwrap_version = None
    else:
        dllwrap_version = None
    return (gcc_version, ld_version, dllwrap_version)

def is_cygwingcc():
    '''Try to determine if the gcc that would be used is from cygwin.'''
    out = os.popen('gcc -dumpmachine', 'r')
    out_string = out.read()
    out.close()
    # out_string is the target triplet cpu-vendor-os
    # Cygwin's gcc sets the os to 'cygwin'
    return out_string.strip().endswith('cygwin')
