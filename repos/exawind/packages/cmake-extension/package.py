# Copyright (c) 2022, National Technology & Engineering Solutions of Sandia,
# LLC (NTESS). Under the terms of Contract DE-NA0003525 with NTESS, the U.S.
# Government retains certain rights in this software.
#
# This software is released under the BSD 3-clause license. See LICENSE file
# for more details.
import argparse
import inspect
import llnl.util.tty as tty
import glob
import os
import shutil
import time

from spack.builder import run_after
from spack.directives import depends_on, variant
from spack.package import CMakePackage
import spack.cmd.common.arguments as arguments


class CmakeExtension(CMakePackage):
    variant("ninja", default=False, description="Enable Ninja makefile generator")
    depends_on("ninja", type="build", when="+ninja")

    @property
    def generator(self):
        if "+ninja" in self.spec:
            return "Ninja"
        else:
            return "Unix Makefiles"

    def do_clean(self):
        super().do_clean()
        if not self.stage.managed_by_spack:
            build_artifacts = glob.glob(os.path.join(self.stage.source_path, "spack-*"))
            for f in build_artifacts:
                if os.path.isfile(f):
                    os.remove(f)
                if os.path.isdir(f):
                    shutil.rmtree(f)
            ccjson = os.path.join(self.stage.source_path, "compile_commands.json")

            if os.path.isfile(ccjson):
                os.remove(ccjson)

    @run_after("cmake")
    def copy_compile_commands(self):
        if self.spec.satisfies("dev_path=*"):
            target = os.path.join(self.stage.source_path, "compile_commands.json")
            source = os.path.join(self.build_directory, "compile_commands.json")
            if os.path.isfile(source):
                shutil.copyfile(source, target)

    @run_after("install")
    def test(self):
        """
        This method will be used to run regression test
        TODO: workout how to get the track,build,site mapped correctly
        thinking of a call to super and writing logic into the packages
        and auxilary python lib
        """ 
        spec = self.spec
        test_env = os.environ.copy()

        cdash_args = {
            "site": "darwin",
            "build": "test",
            "track": "track",
            "timeout": 5*60,
            }

        with working_dir(self.builder.build_directory):
            ctest_args = []
            # Stop tests if they haven't finished in 4-8 hrs (depending on which tests are enabled) so we still get dashboard reporting of build & whatever did run
            ctest_script_filename = "spack_ctest.cmake"
            num_procs = os.getenv("CTEST_TEST_PARALLEL_LEVEL", default=spack.config.get("config:build_jobs"))

            tty.debug("{} creating CTest script".format(spec.name))
            with open(ctest_script_filename, mode='w') as file:
                print("arguments = {}".format(arguments))
                print("argparse.Namespace = {}".format(argparse.Namespace))
                file.write('set(CTEST_SOURCE_DIRECTORY "{}")\n'.format(self.stage.source_path))
                file.write('set(CTEST_BINARY_DIRECTORY "{}")\n'.format(self.builder.build_directory))
                file.write('set(CTEST_SITE "{}" )\n'.format(cdash_args["site"]))
                file.write('set(CTEST_BUILD_NAME "{}" )\n'.format(cdash_args["build"]))
                file.write('set(CTEST_TEST_TIMEOUT "{}" )\n'.format(cdash_args["timeout"]))
                file.write('ctest_start ( "Experimental" TRACK "{}" )\n'.format(cdash_args["track"]))
                file.write('ctest_test ( PARALLEL_LEVEL {} RETURN_VALUE test_status )\n'.format( num_procs))

            ctest_args = []
            ctest_args.append("-S")
            ctest_args.append(ctest_script_filename)

            ctest_args.append("--stop-time")
            overall_test_timeout=60*60*4 # 4 hours
            ctest_args.append(time.strftime("%H:%M:%S", time.localtime(time.time() + overall_test_timeout)))
            ctest_args.extend(["-VV", "-R", "unit"])
            # We want the install to succeed even if some tests fail so pass
            # fail_on_error=False
            tty.debug("{} running CTest script".format(spec.name))
            tty.debug("Running:: ctest"+" ".join(ctest_args))
            inspect.getmodule(self).ctest(*ctest_args, env=test_env, fail_on_error=False)

            test_xml_dir = "Testing"
            with open("Testing/TAG", mode="r") as tag_file:
                timestamp = tag_file.readline().strip('\n')
                test_xml_dir = os.path.join(test_xml_dir, timestamp)
           
            shutil.copy(os.path.join(test_xml_dir, "Test.xml"), "spack-build-results")
