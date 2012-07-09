##
# Copyright 2009-2012 Stijn De Weirdt, Dries Verdegem, Kenneth Hoste, Pieter De Baets, Jens Timmerman
#
# This file is part of EasyBuild,
# originally created by the HPC team of the University of Ghent (http://ugent.be/hpc).
#
# http://github.com/hpcugent/easybuild
#
# EasyBuild is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation v2.
#
# EasyBuild is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with EasyBuild.  If not, see <http://www.gnu.org/licenses/>.
##
import os
import shutil
from distutils.version import LooseVersion
import easybuild
from easybuild.framework.application import Application
from easybuild.tools.filetools import run_cmd
from easybuild.tools.modules import get_software_root

class Libsmm(Application):
    """
    Support for the CP2K small matrix library
    Notes: - build can take really really long, and no real rebuilding needed for each version
           - CP2K can be built without this
    """

    def __init__(self, *args, **kwargs):
        Application.__init__(self, *args, **kwargs)

    def extra_options(self):
        # default dimensions
        dd = [1,4,5,6,9,13,16,17,22]
        vars = Application.extra_options(self)
        extra_vars = {'transpose_flavour':[1, "Transpose flavour of routines (default: 1)"],
                      'max_tiny_dim':[12, "Maximum tiny dimension (default: 12)"],
                      'dims':[dd, "Generate routines for these matrix dims (default: %s)" % dd]
                     }
        vars.update(extra_vars)
        return vars




    def configure(self):
        """Configure build: change to tools/build_libsmm dir"""
        try:
            dst = 'tools/build_libsmm'
            os.chdir(dst)
            self.log.debug('Change to directory %s' % dst)
        except OSError, err:
            self.log.exception('Failed to change to directory %s: %s' % (dst, err))

    def make(self):
        """Build libsmm
        Possible iterations over precision (single/double) and type (real/complex)
        - also type of transpose matrix
        - all set in the config file

        Make the config.in file (is source afterwards in the build)
        """

        fn = 'config.in'
        cfg_tpl = """# This config file was generated by EasyBuild v%(eb_version)s

# the build script can generate optimized routines packed in a library for
# 1) 'nn' => C=C+MATMUL(A,B)
# 2) 'tn' => C=C+MATMUL(TRANSPOSE(A),B)
# 3) 'nt' => C=C+MATMUL(A,TRANSPOSE(B))
# 4) 'tt' => C=C+MATMUL(TRANPOSE(A),TRANPOSE(B))
#
# select a tranpose_flavor from the list 1 2 3 4
#
transpose_flavor=%(transposeflavour)s

# 1) d => double precision real
# 2) s => single precision real
# 3) z => double precision complex
# 4) c => single precision complex
#
# select a data_type from the list 1 2 3 4
#
data_type=%(datatype)s

# target compiler... this are the options used for building the library.
# They should be aggessive enough to e.g. perform vectorization for the specific CPU (e.g. -ftree-vectorize -march=native),
# and allow some flexibility in reordering floating point expressions (-ffast-math).
# Higher level optimisation (in particular loop nest optimization) should not be used.
#
target_compile="%(targetcompile)s"

# target dgemm link options... these are the options needed to link blas (e.g. -lblas)
# blas is used as a fall back option for sizes not included in the library or in those cases where it is faster
# the same blas library should thus also be used when libsmm is linked.
#
OMP_NUM_THREADS=1
blas_linking="%(LIBBLAS)s"

# matrix dimensions for which optimized routines will be generated.
# since all combinations of M,N,K are being generated the size of the library becomes very large
# if too many sizes are being optimized for. Numbers have to be ascending.
#
dims_small="%(dims)s"

# tiny dimensions are used as primitves and generated in an 'exhaustive' search.
# They should be a sequence from 1 to N,
# where N is a number that is large enough to have good in cache performance
# (e.g. for modern SSE cpus 8 to 12)
# Too large (>12?) is not beneficial, but increases the time needed to build the library
# Too small (<8)   will lead to a slow library, but the build might proceed quickly
# The minimum number for a successful build is 4
#
dims_tiny="%(tiny_dims)s"

# host compiler... this is used only to compile a few tools needed to build the library.
# The library itself is not compiled this way.
# This compiler needs to be able to deal with some Fortran2003 constructs.
#
host_compile="%(hostcompile)s "

# number of processes to use in parallel for compiling / building and benchmarking the library.
# Should *not* be more than the physical (available) number of cores of the machine
#
tasks=%(tasks)s

        """

        # only GCC is supported for now
        if os.getenv('SOFTROOTGCC'):
            hostcompile = os.getenv('F90')

            # optimizations
            opts = "-O2 -funroll-loops -ffast-math -ftree-vectorize -march=native -fno-inline-functions"

            # Depending on the version, we need extra options
            extra = ''
            gccVersion = LooseVersion(os.getenv('SOFTVERSIONGCC'))
            if gccVersion >= LooseVersion('4.6'):
                extra = "-flto"

            targetcompile = "%s %s %s" % (hostcompile, opts, extra)
        else:
            self.log.error('No supported compiler found (tried GCC)')

        # try and find BLAS lib
        blas_found = False
        blas_libs = ["ACML", "ATLAS", "IMKL"]
        for blas_lib in blas_libs:
            if get_software_root(blas_lib):
                blas_found = True
            else:
                self.log.info("BLAS library %s not found" % blas_lib)

        if not blas_found:
            self.log.error('No known BLAS library found!')

        cfgdict = {
            'eb_version' : easybuild.VERBOSE_VERSION,
            'datatype': None,
            'transposeflavour': self.getcfg('transpose_flavour'),
            'targetcompile': targetcompile,
            'hostcompile': hostcompile,
            'dims':' '.join([str(d) for d in self.getcfg('dims')]),
            'tiny_dims':' '.join([str(d) for d in range(1, self.getcfg('max_tiny_dim')+1)]),
            'tasks': self.getcfg('parallel'),
            'LIBBLAS':"%s %s" % (os.getenv('LDFLAGS'), os.getenv('LIBBLAS'))
        }

        # configure for various iterations
        datatypes = [(1, 'double precision real'),
                     (3, 'double precision complex')
                     ]
        for (dt, descr) in datatypes:
            cfgdict['datatype'] = dt
            try:
                txt = cfg_tpl % cfgdict
                f = open(fn, 'w')
                f.write(txt)
                f.close()
                self.log.debug("config file %s for datatype %s ('%s'): %s" % (fn, dt, descr, txt))
            except IOError, err:
                self.log.error("Failed to write %s: %s" % (fn, err))

            self.log.info("Building for datatype %s ('%s')..." % (dt, descr))
            run_cmd("./do_clean")
            run_cmd("./do_all")

    def make_install(self):
        """Install CP2K: clean, and copy lib directory to install dir"""

        run_cmd("./do_clean")
        try:
            shutil.copytree('lib', os.path.join(self.installdir, 'lib'))
        except Exception, err:
            self.log.error("Something went wrong during dir lib copying to installdir: %s" % err)

    def sanitycheck(self):
        """Custom sanity check for libsmm"""

        if not self.getcfg('sanityCheckPaths'):
            self.setcfg('sanityCheckPaths', {'files':["lib/libsmm_%s.a" % x for x in ["dnn", "znn"]],
                                            'dirs':[]
                                           })

            self.log.info("Customized sanity check paths: %s" % self.getcfg('sanityCheckPaths'))

        Application.sanitycheck(self)
