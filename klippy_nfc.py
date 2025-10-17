################################################################################
#                                                                              #
#  klippyNFC - NFC Tag Emulation for Klipper                                   #
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

# Type 4 tag constants
NDEF_AID = bytes([0xD2, 0x76, 0x00, 0x00, 0x85, 0x01, 0x01])  # NDEF application ID
CC_FILE_ID = bytes([0xE1, 0x03])  # Capability Container file ID
NDEF_FILE_ID = bytes([0xE1, 0x04])  # NDEF message file ID

class KlippyNFC:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.name = config.get_name()

        # Configuration
        self.spi_bus = config.getint('spi_bus', 0)
        self.spi_ce = config.getint('spi_ce', 0)  # 0=CE0 (GPIO8), 1=CE1 (GPIO7)
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

    def _build_capability_container(self, ndef_size):
        """Build a Capability Container file for Type 4 tag

        CC file structure:
        - Bytes 0-1: CC length (0x000F = 15 bytes)
        - Byte 2: Mapping version (0x20 = version 2.0)
        - Bytes 3-4: Maximum R-APDU data size (MLe) (0x003B = 59 bytes)
        - Bytes 5-6: Maximum C-APDU data size (MLc) (0x0034 = 52 bytes)
        - Bytes 7-14: NDEF File Control TLV:
          - Byte 7: T (0x04 = NDEF File Control TLV)
          - Byte 8: L (0x06 = 6 bytes of data)
          - Bytes 9-10: File ID (0xE104)
          - Bytes 11-12: Maximum NDEF file size
          - Byte 13: Read access (0x00 = free)
          - Byte 14: Write access (0xFF = no write access)
        """
        cc = bytearray([
            0x00, 0x0F,        # CCLEN (15 bytes)
            0x20,              # Mapping version 2.0
            0x00, 0x3B,        # MLe (max 59 bytes can be read at once)
            0x00, 0x34,        # MLc (max 52 bytes can be sent at once)
            0x04,              # T: NDEF File Control TLV
            0x06,              # L: 6 bytes follow
            0xE1, 0x04,        # File ID (0xE104)
            (ndef_size >> 8) & 0xFF,  # Max NDEF size (high byte)
            ndef_size & 0xFF,          # Max NDEF size (low byte)
            0x00,              # Read access: free
            0xFF,              # Write access: no write
        ])
        return bytes(cc)

    def _init_pn532(self):
        """Initialize the PN532 hardware"""
        try:
            from pn532pi import Pn532, Pn532Spi

            # Initialize SPI interface
            spi = Pn532Spi(self.spi_ce)
            self.nfc = Pn532(spi)

            logging.info(f"Initializing PN532 on SPI{self.spi_bus} CE{self.spi_ce}")

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

                # Build command buffer for tgInitAsTarget
                # Format: MODE + SENS_RES + UID + SEL_RES + FELICA params
                command = bytearray([mode])
                command.extend(sens_res)
                command.extend(uid_bytes)
                command.append(sel_res)
                command.extend(bytes(18))  # FELICA params (not used for Type 4)

                # Debug: Log command buffer
                logging.info(f"Calling tgInitAsTarget with command ({len(command)} bytes): {command.hex()}")

                # Initialize as target
                success = self.nfc.tgInitAsTarget(command, 1000)

                # Debug: Log result
                logging.info(f"tgInitAsTarget returned: {success}")

                if success <= 0:
                    # No activation or timeout, continue loop
                    logging.debug("No target activation, continuing...")
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

        Implements proper Type 4 tag APDU command sequence:
        1. SELECT NDEF application (by AID)
        2. SELECT Capability Container file
        3. READ Capability Container
        4. SELECT NDEF file
        5. READ NDEF message
        """
        # Build Capability Container
        # NDEF message format: 2-byte length + NDEF data
        ndef_with_length = bytearray([(len(ndef_data) >> 8) & 0xFF, len(ndef_data) & 0xFF])
        ndef_with_length.extend(ndef_data)
        cc_data = self._build_capability_container(len(ndef_with_length))

        # State tracking
        selected_file = None  # Can be 'CC' or 'NDEF'

        try:
            # Wait for commands from initiator
            while self.running:
                # Get data from initiator
                status, data = self.nfc.tgGetData()

                if status <= 0:
                    break

                # Parse APDU command
                if len(data) < 4:
                    logging.warning(f"APDU too short: {len(data)} bytes")
                    continue

                cla = data[0]
                ins = data[1]
                p1 = data[2]
                p2 = data[3]

                # Handle SELECT command (0xA4)
                if ins == 0xA4:
                    if p1 == 0x04:  # Select by AID
                        # Extract AID from command data
                        if len(data) >= 5:
                            aid_length = data[4]
                            if len(data) >= 5 + aid_length:
                                aid = bytes(data[5:5+aid_length])
                                if aid == NDEF_AID:
                                    logging.info("NDEF application selected")
                                    self.nfc.tgSetData(bytearray([0x90, 0x00]))
                                else:
                                    logging.warning(f"Unknown AID: {aid.hex()}")
                                    self.nfc.tgSetData(bytearray([0x6A, 0x82]))  # File not found
                            else:
                                self.nfc.tgSetData(bytearray([0x67, 0x00]))  # Wrong length
                        else:
                            self.nfc.tgSetData(bytearray([0x67, 0x00]))  # Wrong length

                    elif p1 == 0x00:  # Select by file ID
                        if len(data) >= 5:
                            file_id_length = data[4]
                            if len(data) >= 5 + file_id_length:
                                file_id = bytes(data[5:5+file_id_length])
                                if file_id == CC_FILE_ID:
                                    selected_file = 'CC'
                                    logging.info("CC file selected")
                                    self.nfc.tgSetData(bytearray([0x90, 0x00]))
                                elif file_id == NDEF_FILE_ID:
                                    selected_file = 'NDEF'
                                    logging.info("NDEF file selected")
                                    self.nfc.tgSetData(bytearray([0x90, 0x00]))
                                else:
                                    logging.warning(f"Unknown file ID: {file_id.hex()}")
                                    self.nfc.tgSetData(bytearray([0x6A, 0x82]))  # File not found
                            else:
                                self.nfc.tgSetData(bytearray([0x67, 0x00]))  # Wrong length
                        else:
                            self.nfc.tgSetData(bytearray([0x67, 0x00]))  # Wrong length
                    else:
                        logging.warning(f"Unsupported SELECT P1: {p1:02x}")
                        self.nfc.tgSetData(bytearray([0x6A, 0x86]))  # Incorrect parameters

                # Handle READ BINARY command (0xB0)
                elif ins == 0xB0:
                    offset = (p1 << 8) | p2
                    length = data[4] if len(data) > 4 else 0

                    if selected_file == 'CC':
                        # Read from Capability Container
                        if offset < len(cc_data):
                            end = min(offset + length, len(cc_data))
                            response = bytearray(cc_data[offset:end])
                            response.extend([0x90, 0x00])
                            self.nfc.tgSetData(response)
                            logging.info(f"Read {len(response)-2} bytes from CC at offset {offset}")
                        else:
                            self.nfc.tgSetData(bytearray([0x6B, 0x00]))  # Wrong offset

                    elif selected_file == 'NDEF':
                        # Read from NDEF file
                        if offset < len(ndef_with_length):
                            end = min(offset + length, len(ndef_with_length))
                            response = bytearray(ndef_with_length[offset:end])
                            response.extend([0x90, 0x00])
                            self.nfc.tgSetData(response)
                            logging.info(f"Read {len(response)-2} bytes from NDEF at offset {offset}")
                        else:
                            self.nfc.tgSetData(bytearray([0x6B, 0x00]))  # Wrong offset

                    else:
                        logging.warning("READ BINARY without file selected")
                        self.nfc.tgSetData(bytearray([0x69, 0x86]))  # Command not allowed

                else:
                    # Unsupported command
                    logging.warning(f"Unsupported INS: {ins:02x}")
                    self.nfc.tgSetData(bytearray([0x6D, 0x00]))  # INS not supported

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
    return KlippyNFC(config)
