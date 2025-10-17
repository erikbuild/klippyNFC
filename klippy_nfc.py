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

class KlippyNFC:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.name = config.get_name()

        # Configuration
        self.spi_bus = config.getint('spi_bus', 0) # 0=SPI0, 1=SPI1
        self.spi_ce = config.getint('spi_ce', 0)  # 0=CE0 (GPIO8), 1=CE1 (GPIO7)
        self.url_override = config.get('url', None)
        self.port = config.getint('port', 80)
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

    def _build_type2_memory(self, ndef_data):
        """Build Type 2 tag memory layout

        Type 2 tags use 16-byte pages:
        - Pages 0-3: UID + lock bytes (readonly, managed by PN532)
        - Page 4: Capability Container
        - Page 5+: NDEF message in TLV format

        Returns bytes representing the full memory content starting from page 4
        """
        memory = bytearray()

        # Page 4: Capability Container
        # E1 = NDEF Magic Number
        # 10 = Version 1.0
        # Size = (total_bytes / 8), we'll use a reasonable max
        # 00 = Read/Write access
        memory.extend([0xE1, 0x10, 0x6D, 0x00])  # CC: supports ~880 bytes
        memory.extend([0x00] * 12)  # Rest of page 4

        # Page 5+: NDEF TLV
        # 03 = NDEF Message TLV
        # Length byte(s)
        # NDEF message
        # FE = Terminator TLV
        memory.append(0x03)  # NDEF Message TLV

        # Length encoding (1 or 3 bytes)
        if len(ndef_data) < 255:
            memory.append(len(ndef_data))
        else:
            memory.append(0xFF)
            memory.append((len(ndef_data) >> 8) & 0xFF)
            memory.append(len(ndef_data) & 0xFF)

        memory.extend(ndef_data)
        memory.append(0xFE)  # Terminator TLV

        # Pad to 16-byte boundary
        while len(memory) % 16 != 0:
            memory.append(0x00)

        return bytes(memory)

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

                # SENS_RES (ISO14443A) - 0x4400 indicates Type 2 tag (NTAG/Ultralight)
                sens_res = bytes([0x44, 0x00])

                # SEL_RES for Type 2 (no ISO14443-4)
                sel_res = 0x00

                # Build command buffer for tgInitAsTarget
                # Format: 0x8C + MODE + MIFARE params (6) + FELICA params (18) + NFCID3t (10)
                command = bytearray([0x8C, mode])  # 0x8C = TgInitAsTarget command
                # MIFARE parameters (6 bytes total)
                command.extend(sens_res)           # SENS_RES (2 bytes)
                command.extend(uid_bytes)          # NFCID1t/UID (3 bytes)
                command.append(sel_res)            # SEL_RES (1 byte)
                # Felica parameters (18 bytes) - not used for Type 4
                command.extend(bytes(18))
                # NFCID3t (10 bytes) - required by PN532
                command.extend(bytes(10))

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

                # Handle Type 2 tag memory commands
                self._handle_type2_commands(ndef_data)

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

    def _handle_type2_commands(self, ndef_data):
        """Handle Type 2 tag memory READ commands

        Type 2 tags use simple memory-based protocol:
        - READ command (0x30 + page): Returns 16 bytes (4 pages)
        - Memory layout: Pages 0-3 (UID/locks by PN532), Pages 4+ (our data)
        """
        # Build Type 2 memory layout (starts at page 4)
        our_memory = self._build_type2_memory(ndef_data)

        try:
            # Wait for commands from initiator
            while self.running:
                # Get command from initiator
                status, data = self.nfc.tgGetData()

                if status <= 0:
                    break

                # Parse command
                if len(data) < 2:
                    logging.warning(f"Command too short: {len(data)} bytes")
                    continue

                cmd = data[0]

                # Handle READ command (0x30)
                if cmd == 0x30:
                    page = data[1]
                    logging.info(f"READ command for page {page}")

                    # Pages 0-3 are UID/lock bytes (handled by PN532)
                    # We provide pages 4+ from our memory
                    if page < 4:
                        # PN532 should handle these, but respond with zeros if asked
                        response = bytearray(16)
                        self.nfc.tgSetData(response)
                    else:
                        # Calculate offset in our memory
                        # our_memory starts at page 4, so page N maps to offset (N-4)*4
                        offset = (page - 4) * 4

                        if offset < len(our_memory):
                            # Return 16 bytes (4 pages) starting from this offset
                            end = min(offset + 16, len(our_memory))
                            response = bytearray(our_memory[offset:end])

                            # Pad to 16 bytes if needed
                            while len(response) < 16:
                                response.append(0x00)

                            self.nfc.tgSetData(response)
                            logging.info(f"Returned {len(response)} bytes from page {page}")
                        else:
                            # Out of bounds, return zeros
                            response = bytearray(16)
                            self.nfc.tgSetData(response)
                            logging.warning(f"Page {page} out of bounds, returning zeros")
                else:
                    # Unsupported command - respond with zeros
                    logging.warning(f"Unsupported command: {cmd:02x}")
                    response = bytearray(16)
                    self.nfc.tgSetData(response)

        except Exception as e:
            logging.error(f"Error handling Type 2 commands: {e}")

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
