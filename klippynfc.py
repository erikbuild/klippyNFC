################################################################################
#                                                                              #
#  KlippyNFC - NFC Tag Emulation for Klipper                                   #
#                                                                              #
#  Author: Erik Reynolds (erikbuild)                                           #
#  Repository: https://github.com/erikbuild/klippyNFC                          #
#                                                                              #
#  Emulates an NFC tag using PN532 hardware that presents the Klipper          #
#  web interface URL when tapped by a phone.                                   #
#                                                                              #
################################################################################

# ABOUTME: Klipper plugin for PN532 NFC tag emulation
# ABOUTME: Emulates an NFC tag presenting the Klipper web interface URL

import threading
import socket
import logging
import time

class NFCEmulator:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.name = config.get_name()

        # Configuration
        self.i2c_bus = config.getint('i2c_bus', 1)
        self.url_override = config.get('url', None)
        self.port = config.getint('port', 7125)
        self.uid = config.get('uid', '010203')

        # State
        self.nfc = None
        self.emulation_thread = None
        self.running = False
        self.current_url = None
        self.error_count = 0

        # Register event handlers
        self.printer.register_event_handler("klippy:ready", self.handle_ready)
        self.printer.register_event_handler("klippy:disconnect", self.handle_disconnect)

        # Register G-code commands
        gcode = self.printer.lookup_object('gcode')
        gcode.register_command('NFC_STATUS', self.cmd_NFC_STATUS,
                             desc=self.cmd_NFC_STATUS_help)
        gcode.register_command('NFC_SET_URL', self.cmd_NFC_SET_URL,
                             desc=self.cmd_NFC_SET_URL_help)
        gcode.register_command('NFC_RESTART', self.cmd_NFC_RESTART,
                             desc=self.cmd_NFC_RESTART_help)

    def _get_url(self):
        """Discover or construct the web interface URL"""
        if self.url_override:
            return self.url_override

        hostname = socket.gethostname()
        if not hostname or hostname == 'localhost':
            # Try to get the actual IP address
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                hostname = s.getsockname()[0]
                s.close()
            except Exception:
                hostname = "printer.local"

        return f"http://{hostname}:{self.port}"

    def _build_ndef_uri_record(self, url):
        """Build an NDEF URI record from a URL string

        Returns bytes representing the NDEF message
        """
        # URI identifier codes (see NFC Forum URI Record Type Definition)
        uri_prefixes = {
            'http://www.': 0x01,
            'https://www.': 0x02,
            'http://': 0x03,
            'https://': 0x04,
        }

        # Find matching prefix
        uri_code = 0x00  # No prefix
        uri_data = url
        for prefix, code in uri_prefixes.items():
            if url.startswith(prefix):
                uri_code = code
                uri_data = url[len(prefix):]
                break

        # Build NDEF record
        # TNF = 0x01 (Well Known), Flags: MB=1, ME=1, SR=1
        tnf_flags = 0xD1
        type_length = 0x01
        record_type = ord('U')  # URI type

        uri_bytes = uri_data.encode('utf-8')
        payload_length = 1 + len(uri_bytes)  # uri_code + uri_data

        # Construct NDEF message
        ndef_message = bytearray([
            tnf_flags,
            type_length,
            payload_length,
            record_type,
            uri_code
        ])
        ndef_message.extend(uri_bytes)

        return bytes(ndef_message)

    def _init_pn532(self):
        """Initialize the PN532 hardware"""
        try:
            from pn532pi import Pn532, Pn532I2c

            # Initialize I2C interface
            i2c = Pn532I2c(self.i2c_bus)
            self.nfc = Pn532(i2c)

            # Begin communication
            self.nfc.begin()

            # Get firmware version to verify communication
            version = self.nfc.getFirmwareVersion()
            if not version:
                raise RuntimeError("Failed to communicate with PN532")

            logging.info(f"PN532 firmware version: {version:#x}")

            # Configure SAM (Security Access Module)
            self.nfc.SAMConfig()

            return True

        except ImportError:
            logging.error("pn532pi library not found. Install with: pip install pn532pi")
            return False
        except Exception as e:
            logging.error(f"Failed to initialize PN532: {e}")
            return False

    def _emulation_loop(self):
        """Main emulation loop running in background thread"""
        logging.info(f"Starting NFC emulation for URL: {self.current_url}")

        while self.running:
            try:
                # Build NDEF message with current URL
                ndef_data = self._build_ndef_uri_record(self.current_url)

                # Convert UID string to bytes
                uid_bytes = bytes.fromhex(self.uid)

                # Configure target parameters for Type 4 tag emulation
                # Mode: Passive only (0x01)
                mode = 0x01

                # SENS_RES (ISO14443A)
                sens_res = bytes([0x00, 0x40])

                # SEL_RES (ISO14443-4 compliant)
                sel_res = 0x60

                # Initialize as target
                success = self.nfc.tgInitAsTarget(
                    mode=mode,
                    mifareParams=sens_res + uid_bytes + bytes([sel_res]),
                    felicaParams=bytes(18),  # Not used for Type 4
                    timeout=1000
                )

                if success <= 0:
                    # No activation or timeout, continue loop
                    time.sleep(0.1)
                    continue

                logging.info("NFC target activated")

                # Handle Type 4 tag APDU commands
                self._handle_type4_commands(ndef_data)

                # Reset error count on successful interaction
                self.error_count = 0

            except Exception as e:
                self.error_count += 1
                logging.error(f"NFC emulation error: {e}")

                if self.error_count > 10:
                    logging.error("Too many errors, stopping NFC emulation")
                    self.running = False
                    break

                time.sleep(1)

    def _handle_type4_commands(self, ndef_data):
        """Handle APDU commands for Type 4 tag protocol

        This implements the basic Type 4 tag operation specification
        """
        # Type 4 tag APDU command handlers would go here
        # This is a simplified implementation - full Type 4 protocol is complex

        try:
            # Wait for commands from initiator
            while self.running:
                # Get data from initiator
                status, data = self.nfc.tgGetData()

                if status <= 0:
                    break

                # Parse APDU command
                if len(data) < 4:
                    continue

                cla = data[0]
                ins = data[1]

                # Handle SELECT command (0xA4)
                if ins == 0xA4:
                    # Send success response
                    self.nfc.tgSetData(bytes([0x90, 0x00]))

                # Handle READ BINARY command (0xB0)
                elif ins == 0xB0:
                    # Send NDEF data
                    response = ndef_data + bytes([0x90, 0x00])
                    self.nfc.tgSetData(response)

                else:
                    # Unsupported command
                    self.nfc.tgSetData(bytes([0x6A, 0x82]))

        except Exception as e:
            logging.error(f"Error handling Type 4 commands: {e}")

    def handle_ready(self):
        """Called when Klipper is ready"""
        self.current_url = self._get_url()

        if not self._init_pn532():
            logging.error("Failed to initialize PN532, NFC emulation disabled")
            return

        # Start emulation thread
        self.running = True
        self.emulation_thread = threading.Thread(target=self._emulation_loop)
        self.emulation_thread.daemon = True
        self.emulation_thread.start()

        logging.info(f"NFC emulation started: {self.current_url}")

    def handle_disconnect(self):
        """Called when Klipper disconnects"""
        self.running = False
        if self.emulation_thread:
            self.emulation_thread.join(timeout=2)

    # G-code command handlers
    cmd_NFC_STATUS_help = "Display NFC emulation status and current URL"
    def cmd_NFC_STATUS(self, gcmd):
        gcode = self.printer.lookup_object('gcode')

        status = "running" if self.running else "stopped"
        gcode.respond_info(f"NFC Emulation: {status}")
        gcode.respond_info(f"Current URL: {self.current_url}")
        gcode.respond_info(f"Error count: {self.error_count}")

    cmd_NFC_SET_URL_help = "Set a custom URL for NFC emulation"
    def cmd_NFC_SET_URL(self, gcmd):
        url = gcmd.get('URL')
        self.current_url = url

        gcode = self.printer.lookup_object('gcode')
        gcode.respond_info(f"NFC URL updated to: {url}")

    cmd_NFC_RESTART_help = "Restart NFC emulation"
    def cmd_NFC_RESTART(self, gcmd):
        gcode = self.printer.lookup_object('gcode')

        # Stop current emulation
        self.running = False
        if self.emulation_thread:
            self.emulation_thread.join(timeout=2)

        # Restart
        self.handle_ready()
        gcode.respond_info("NFC emulation restarted")

def load_config(config):
    return NFCEmulator(config)
