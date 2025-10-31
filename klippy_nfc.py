################################################################################
#                                                                              #
#  klippyNFC - NFC Tag Writer for Klipper                                      #
#                                                                              #
#  Author: Erik Reynolds (erikbuild)                                           #
#  Repository: https://github.com/erikbuild/klippyNFC                          #
#                                                                              #
#  Writes NFC tags using PN532 hardware that present the Klipper               #
#  web interface URL when tapped by a phone.                                   #
#                                                                              #
################################################################################

# ABOUTME: Klipper plugin for PN532 NFC tag writing
# ABOUTME: Writes NFC tags with the Klipper web interface URL

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

        # State
        self.nfc = None
        self.current_url = None
        self.last_write_status = "Not written yet"
        self.last_write_time = None

        # Register event handlers
        self.printer.register_event_handler("klippy:ready", self.handle_ready)

        # Register G-code commands
        gcode = self.printer.lookup_object('gcode')
        gcode.register_command('NFC_STATUS', self.cmd_NFC_STATUS,
                             desc=self.cmd_NFC_STATUS_help)
        gcode.register_command('NFC_WRITE_TAG', self.cmd_NFC_WRITE_TAG,
                             desc=self.cmd_NFC_WRITE_TAG_help)
        gcode.register_command('NFC_SET_URL', self.cmd_NFC_SET_URL,
                             desc=self.cmd_NFC_SET_URL_help)

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
            # Some PN532 boards (Elechouse) need multiple attempts
            version = None
            for attempt in range(5):
                version = self.nfc.getFirmwareVersion()
                if version and version != 0:
                    break
                if attempt < 4:
                    logging.info(f"getFirmwareVersion attempt {attempt + 1} returned {version:#x}, retrying...")
                    time.sleep(0.2)

            if not version or version == 0:
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

    def _scan_for_tag(self, timeout_ms=2000):
        """Scan for a Type 2 NFC tag (NTAG, Ultralight, etc.)

        Returns (success, uid) tuple where:
        - success: True if tag detected
        - uid: Tag UID as bytes, or None if no tag
        """
        try:
            # Read passive target (Type A, 106 kbps)
            # cardbaudrate = 0 for Type A tags (ISO14443A at 106 kbps)
            # readPassiveTargetID returns (success, uid) tuple
            success, uid = self.nfc.readPassiveTargetID(cardbaudrate=0, timeout=timeout_ms)

            if success and uid and len(uid) > 0:
                logging.info(f"Tag detected: UID = {uid.hex()}")
                return True, uid
            else:
                return False, None

        except Exception as e:
            logging.error(f"Error scanning for tag: {e}")
            return False, None

    def _write_tag(self, url):
        """Write NDEF URL message to a Type 2 NFC tag

        Returns (success, message) tuple
        """
        try:
            # Build NDEF message
            ndef_data = self._build_ndef_uri_record(url)
            memory = self._build_type2_memory(ndef_data)

            logging.info(f"Writing {len(memory)} bytes to tag")

            # Write memory to tag, starting at page 4
            # (Pages 0-3 contain UID and are readonly)
            page = 4
            offset = 0

            while offset < len(memory):
                # Get 4 bytes for this page
                page_data = memory[offset:offset+4]

                # Pad to 4 bytes if needed
                while len(page_data) < 4:
                    page_data += b'\x00'

                # Write page using mifareultralight_WritePage (NTAG uses same command)
                success = self.nfc.mifareultralight_WritePage(page, bytearray(page_data))

                if not success:
                    error_msg = f"Failed to write page {page}"
                    logging.error(error_msg)
                    return False, error_msg

                logging.info(f"Wrote page {page}: {page_data.hex()}")

                page += 1
                offset += 4

            success_msg = f"Successfully wrote {len(memory)} bytes ({(len(memory)+3)//4} pages)"
            logging.info(success_msg)
            return True, success_msg

        except Exception as e:
            error_msg = f"Error writing tag: {e}"
            logging.error(error_msg)
            return False, error_msg

    def handle_ready(self):
        """Called when Klipper is ready"""
        self.current_url = self._get_url()

        if not self._init_pn532():
            logging.error("Failed to initialize PN532, NFC tag writing disabled")
            return

        logging.info(f"NFC tag writer ready. Use NFC_WRITE_TAG to write tags with URL: {self.current_url}")

    # G-code command handlers
    cmd_NFC_STATUS_help = "Display NFC tag writer status and current URL"
    def cmd_NFC_STATUS(self, gcmd):
        gcode = self.printer.lookup_object('gcode')

        gcode.respond_info(f"Current URL: {self.current_url}")
        gcode.respond_info(f"Last write: {self.last_write_status}")
        if self.last_write_time:
            gcode.respond_info(f"Write time: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(self.last_write_time))}")

    cmd_NFC_WRITE_TAG_help = "Write current URL to an NFC tag (place tag on reader first)"
    def cmd_NFC_WRITE_TAG(self, gcmd):
        gcode = self.printer.lookup_object('gcode')

        if not self.nfc:
            gcode.respond_info("Error: PN532 not initialized")
            return

        # Use URL parameter if provided, otherwise use current URL
        url = gcmd.get('URL', self.current_url)

        gcode.respond_info(f"Scanning for NFC tag...")

        # Scan for tag
        success, uid = self._scan_for_tag(timeout_ms=5000)

        if not success:
            self.last_write_status = "Failed: No tag detected"
            self.last_write_time = time.time()
            gcode.respond_info("Error: No NFC tag detected. Place tag on reader and try again.")
            return

        gcode.respond_info(f"Tag detected: {uid.hex()}")
        gcode.respond_info(f"Writing URL: {url}")

        # Write to tag
        success, message = self._write_tag(url)

        self.last_write_status = message
        self.last_write_time = time.time()

        if success:
            gcode.respond_info(f"Success! {message}")
        else:
            gcode.respond_info(f"Error: {message}")

    cmd_NFC_SET_URL_help = "Set a custom URL for NFC tag writing"
    def cmd_NFC_SET_URL(self, gcmd):
        url = gcmd.get('URL')
        self.current_url = url

        gcode = self.printer.lookup_object('gcode')
        gcode.respond_info(f"NFC URL updated to: {url}")

def load_config(config):
    return KlippyNFC(config)
