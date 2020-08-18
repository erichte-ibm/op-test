import unittest
import os, time

import OpTestConfiguration

from common.OpTestSystem import OpSystemState
from common.OpTestInstallUtil import InstallUtil

"""
THE PLAN:

 - assert physical presence
   - clears any existing keys
   - gets the machine in a known state without secureboot
 - enroll a set of PK, KEK, db
   - pregenerated, use secvar sysfs interface
   - ideally do this in skiroot
 - reboot, and ensure secure boot is now enabled
 - successfully boot a signed kernel
 - fail to boot an unsigned/improperly signed kernel
 - fail to boot a dbx'd kernel
 - assert physical presence
   - ensure machine is in a non-secure boot state


"""


class OsSecureBoot(unittest.TestCase):
    def setUp(self):
        conf = OpTestConfiguration.conf
        self.cv_SYSTEM = conf.system()
        self.cv_BMC = conf.bmc()
        self.cv_HOST = conf.host()
        self.cv_IPMI = conf.ipmi()
        self.OpIU = InstallUtil()

    def getTestData(self, data="keys"):
        con = self.cv_SYSTEM.console
        self.OpIU.configure_host_ip()

        fil = "os{}.tar".format(data)
        url = "http://x86tpm2server.rtp.stglabs.ibm.com:8000/{}".format(fil)

        con.run_command("wget {0} -O /tmp/{1}".format(url, fil))
        con.run_command("tar xf /tmp/{} -C /tmp/".format(fil))

    def assertPhysicalPresence(self):
        self.cv_SYSTEM.goto_state(OpSystemState.OFF)

        self.cv_BMC.image_transfer("test_binaries/physicalPresence.bin")
        self.cv_BMC.run_command("cp /tmp/physicalPresence.bin /usr/local/share/pnor/ATTR_TMP")
        self.cv_BMC.run_command("echo '0 0x283a 0x15000000' > /var/lib/obmc/cfam_overrides")
        self.cv_BMC.run_command("echo '0 0x283F 0x20000000' >> /var/lib/obmc/cfam_overrides")

        self.cv_IPMI.ipmitool.run("raw 0x04 0x30 0xE8 0x00 0x40 0x00 0x00 0x00 0x00 0x00 0x00 0x00")
        output = self.cv_IPMI.ipmitool.run("raw 0x04 0x2D 0xE8")
        if "40 40 00 00" not in output:
            raise Exception("bad output = " + str(output))
        
        self.cv_SYSTEM.sys_power_on()

        raw_pty = self.cv_SYSTEM.console.get_console()
        # Console output should show following:
        # 41.13637|secure|Opened Physical Presence Detection Window
        # 41.13638|secure|System Will Power Off and Wait For Manual Power On
        # 41.14216|IPMI: Initiate soft power off
        # 41.25181|Stopping istep dispatcher
        # 41.42300|IPMI: shutdown complete
        raw_pty.expect("Opened Physical Presence Detection Window", timeout=120)
        raw_pty.expect("System Will Power Off and Wait For Manual Power On", timeout=30)
        raw_pty.expect("shutdown complete", timeout=30)

        # Shut itself off, turn it back on
        # Need to turn it on by the BMC for some reason?
        self.cv_BMC.run_command("obmcutil power on")

        # This is apparently needed because otherwise op-test can't determine
        # the state of the machine?
        self.cv_SYSTEM.sys_check_host_status()

        self.checkSecureBootEnabled(enabled=False, physical=True)
        # TODO: test empty keys

        

    def addSecureBootKeys(self):
        self.cv_SYSTEM.goto_state(OpSystemState.PETITBOOT_SHELL)
        con = self.cv_SYSTEM.console

        self.getTestData()

        for k in ["PK", "KEK", "db", "dbx"]:
        #for k in ["PK", "KEK", "db"]:
            con.run_command("cat /tmp/{0}.auth > /sys/firmware/secvar/vars/{0}/update".format(k))

        # System needs to power fully off to process keys on next reboot
        self.cv_SYSTEM.sys_power_off()
       
        # TODO: Probably can do an expect or something instead
        # need to stall because otherwise it just blows on through on its own
 
        time.sleep(10)
        self.cv_SYSTEM.goto_state(OpSystemState.OFF)
        # TODO: expect secvar logs from skiboot
        time.sleep(10)
        # TODO: need a better "turn on" command here

        # TODO: reboot to petitboot and ensure keys enrolled

        self.checkSecureBootEnabled(enabled=True)


    # TODO: figure out how to detect secure boot state
    # TODO: handle either enabled or not enabled
    def checkSecureBootEnabled(self, enabled=True, physical=False):
        self.cv_SYSTEM.goto_state(OpSystemState.PETITBOOT_SHELL)
        con = self.cv_SYSTEM.console

        con.run_command("test {} -f /sys/firmware/devicetree/base/ibm,secureboot/os-secureboot-enforcing"
            .format("" if enabled else "!"))

        if physical:
            con.run_command("test -f /sys/firmware/devicetree/base/ibm,secureboot/physical-presence-asserted")
            con.run_command("test -f /sys/firmware/devicetree/base/ibm,secureboot/clear-os-keys")

    def checkKexecKernels(self):
        self.cv_SYSTEM.goto_state(OpSystemState.PETITBOOT_SHELL)
        con = self.cv_SYSTEM.console

        self.getTestData(data="kernels")

        # Fail unsigned kernel
        output = con.run_command_ignore_fail("kexec -s /tmp/kernel-unsigned")
        if "Permission denied" not in "".join(output):
            raise Exception("bad")

        # Fail dbx kernel
        output = con.run_command_ignore_fail("kexec -s /tmp/kernel-dbx")
        if "Permission denied" not in "".join(output):
            raise Exception("bad")
        
        # Succeed good kernel
        con.run_command("kexec -s /tmp/kernel-signed")
#        con.run_command("kexec -e")


    def runTest(self):
        # start clean
        # TODO: maybe clear SECBOOT partition, so there aren't any updates
        # that might be processed when booting? is this needed?
        self.assertPhysicalPresence()

        # add secure boot keys
        self.addSecureBootKeys()

        # attempt to securely boot test kernels
        self.checkKexecKernels()

        # TODO: check that lockdown is enabled?

        # clean up after 
        self.assertPhysicalPresence()
