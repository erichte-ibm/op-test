import unittest
import os

import OpTestConfiguration

from common.OpTestSystem import OpSystemState

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

        # TODO: check for empty keys/non-secureboot state

    def addSecureBootKeys(self):
        self.cv_SYSTEM.goto_state(OpSystemState.OS)
        for k in ["PK", "KEK", "db"]:
            self.cv_HOST.copy_test_file_to_host(k + ".auth", sourcedir=os.path.join("test_binaries","keys"))
            self.cv_HOST.host_run_command("cat /tmp/{0}.auth > /sys/firmware/secvar/vars/{0}/update".format(k))

        # System needs to power fully off to process keys on next reboot
        self.cv_SYSTEM.sys_power_off()
        
        # TODO: expect secvar logs from skiboot


    # TODO: figure out how to detect secure boot state
    # TODO: handle either enabled or not enabled
    def checkSecureBootEnabled(self, enabled=True):
        self.cv_SYSTEM.goto_state(OpSystemState.OS)

        self.cv_HOST.host_run_command("ls /sys/firmware/devicetree/base/ibm,secureboot/os-secure-enforcing")
        #self.cv_HOST.host_run_command("ls /sys/firmware/devicetree/base/ibm,secureboot/physical-presence-asserted || true")
        #self.cv_HOST.host_run_command("ls /sys/firmware/devicetree/base/ibm,secureboot/clear-os-keys || true")


    def runTest(self):
        # start clean
        self.assertPhysicalPresence()


        # add secure boot keys
        self.addSecureBootKeys()

        # boot to signed RHEL and
        # check os secure boot enabled
        self.checkSecureBootEnabled()

        # enroll a different db key, so
        # fail to boot an unsigned kernel

        # fail to boot a dbx'd kernel (TODO)

        return
        # clean up after 
        self.assertPhysicalPresence()
