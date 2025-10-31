################################################################################
#                                                                              #
#  klippyNFC - NFC Tag Reader/Writer for Klipper                               #
#                                                                              #
#  Author: Erik Reynolds (erikbuild)                                           #
#  Repository: https://github.com/erikbuild/klippyNFC                          #
#                                                                              #
#  Reads and writes NFC tags using PN532 hardware. Written tags present        #
#  the Klipper web interface URL when tapped by a phone.                       #
#                                                                              #
################################################################################

# ABOUTME: Klipper plugin for PN532 NFC tag reading and writing
# ABOUTME: Reads and writes NFC tags with the Klipper web interface URL

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
        gcode.register_command('NFC_READ_TAG', self.cmd_NFC_READ_TAG,
                             desc=self.cmd_NFC_READ_TAG_help)
        gcode.register_command('NFC_VERIFY_TAG', self.cmd_NFC_VERIFY_TAG,
                             desc=self.cmd_NFC_VERIFY_TAG_help)
        gcode.register_command('NFC_TAG_INFO', self.cmd_NFC_TAG_INFO,
                             desc=self.cmd_NFC_TAG_INFO_help)

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
        else:
            # Append .local for mDNS resolution if needed
            # Don't append if:
            # - Already has .local suffix
            # - Contains a dot (already FQDN or IP-like)
            if not hostname.endswith('.local') and '.' not in hostname:
                hostname = f"{hostname}.local"

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

    def _parse_ndef_uri_record(self, ndef_bytes):
        """Parse an NDEF URI record to extract the URL

        Args:
            ndef_bytes: Raw NDEF message bytes

        Returns:
            Tuple of (success, url) where:
            - success: True if valid URI record parsed
            - url: Extracted URL string, or None if invalid
        """
        try:
            if len(ndef_bytes) < 5:
                logging.error(f"NDEF message too short: {len(ndef_bytes)} bytes")
                return False, None

            # Parse NDEF record header
            tnf_flags = ndef_bytes[0]
            type_length = ndef_bytes[1]
            payload_length = ndef_bytes[2]
            record_type = ndef_bytes[3]

            # Validate TNF (should be 0x01 = Well Known)
            tnf = tnf_flags & 0x07
            if tnf != 0x01:
                logging.error(f"Invalid TNF: {tnf:#x}, expected 0x01 (Well Known)")
                return False, None

            # Validate record type (should be 'U' for URI)
            if record_type != ord('U'):
                logging.error(f"Invalid record type: {record_type:#x}, expected 'U' (0x55)")
                return False, None

            # Extract URI code and data
            if len(ndef_bytes) < 5 + payload_length:
                logging.error(f"NDEF payload truncated: expected {5 + payload_length}, got {len(ndef_bytes)}")
                return False, None

            uri_code = ndef_bytes[4]
            uri_data = ndef_bytes[5:5 + payload_length - 1].decode('utf-8')

            # Decompress URI prefix
            uri_prefixes = {
                0x00: '',
                0x01: 'http://www.',
                0x02: 'https://www.',
                0x03: 'http://',
                0x04: 'https://',
            }

            prefix = uri_prefixes.get(uri_code, '')
            if uri_code not in uri_prefixes:
                logging.warning(f"Unknown URI code: {uri_code:#x}, treating as no prefix")

            url = prefix + uri_data
            logging.info(f"Parsed NDEF URI: {url}")
            return True, url

        except Exception as e:
            logging.error(f"Error parsing NDEF URI record: {e}")
            return False, None

    def _build_type2_memory(self, ndef_data):
        """Build Type 2 tag memory layout

        Type 2 tags (NTAG) memory structure:
        - Pages 0-2: UID + lock bytes (readonly, managed by PN532)
        - Page 3: Capability Container (CC)
        - Page 4+: NDEF message in TLV format

        Returns (cc_bytes, tlv_bytes) tuple where:
        - cc_bytes: Capability Container (4 bytes) to write at page 3
        - tlv_bytes: TLV data to write starting at page 4
        """
        # Capability Container (Page 3)
        # E1 = NDEF Magic Number
        # 10 = Version 1.0
        # Size = (total_bytes / 8), using 0x12 for NTAG213 (144 bytes)
        # 00 = Read/Write access
        cc_bytes = bytearray([0xE1, 0x10, 0x12, 0x00])

        # TLV blocks (Page 4+)
        tlv_bytes = bytearray()

        # NDEF Message TLV
        # 03 = NDEF Message TLV type
        # Length byte(s)
        # NDEF message
        # FE = Terminator TLV
        tlv_bytes.append(0x03)  # NDEF Message TLV

        # Length encoding (1 or 3 bytes)
        if len(ndef_data) < 255:
            tlv_bytes.append(len(ndef_data))
        else:
            tlv_bytes.append(0xFF)
            tlv_bytes.append((len(ndef_data) >> 8) & 0xFF)
            tlv_bytes.append(len(ndef_data) & 0xFF)

        tlv_bytes.extend(ndef_data)
        tlv_bytes.append(0xFE)  # Terminator TLV

        # Pad to 4-byte boundary
        while len(tlv_bytes) % 4 != 0:
            tlv_bytes.append(0x00)

        return bytes(cc_bytes), bytes(tlv_bytes)

    def _parse_type2_memory(self, cc_bytes, tlv_bytes):
        """Parse Type 2 tag memory layout to extract NDEF message

        Args:
            cc_bytes: 4 bytes from page 3 (Capability Container)
            tlv_bytes: TLV data from page 4+ until terminator

        Returns:
            Tuple of (success, ndef_data, metadata) where:
            - success: True if valid NDEF structure
            - ndef_data: Raw NDEF message bytes, or None if invalid
            - metadata: Dictionary with CC info (magic, version, size, access)
        """
        try:
            # Parse Capability Container
            if len(cc_bytes) < 4:
                logging.error(f"CC too short: {len(cc_bytes)} bytes")
                return False, None, None

            cc_magic = cc_bytes[0]
            cc_version = cc_bytes[1]
            cc_size = cc_bytes[2]
            cc_access = cc_bytes[3]

            # Validate NDEF magic number
            if cc_magic != 0xE1:
                logging.error(f"Invalid CC magic number: {cc_magic:#x}, expected 0xE1")
                return False, None, None

            # Build metadata
            metadata = {
                'magic': cc_magic,
                'version_major': (cc_version >> 4) & 0x0F,
                'version_minor': cc_version & 0x0F,
                'memory_size': cc_size * 8,  # Size is in units of 8 bytes
                'read_access': (cc_access >> 4) & 0x0F,
                'write_access': cc_access & 0x0F,
            }

            logging.info(f"CC: version={metadata['version_major']}.{metadata['version_minor']}, "
                        f"size={metadata['memory_size']} bytes, "
                        f"access=R{metadata['read_access']:#x}/W{metadata['write_access']:#x}")

            # Parse TLV structure
            if len(tlv_bytes) < 2:
                logging.error(f"TLV too short: {len(tlv_bytes)} bytes")
                return False, None, metadata

            offset = 0
            ndef_data = None

            while offset < len(tlv_bytes):
                tlv_type = tlv_bytes[offset]
                offset += 1

                # Terminator TLV
                if tlv_type == 0xFE:
                    logging.info("Found Terminator TLV")
                    break

                # Null TLV (skip)
                if tlv_type == 0x00:
                    continue

                # NDEF Message TLV
                if tlv_type == 0x03:
                    if offset >= len(tlv_bytes):
                        logging.error("TLV length missing")
                        return False, None, metadata

                    # Parse length (1 or 3 bytes)
                    length_byte = tlv_bytes[offset]
                    offset += 1

                    if length_byte == 0xFF:
                        # 3-byte length format
                        if offset + 2 > len(tlv_bytes):
                            logging.error("TLV 3-byte length truncated")
                            return False, None, metadata
                        ndef_length = (tlv_bytes[offset] << 8) | tlv_bytes[offset + 1]
                        offset += 2
                    else:
                        # 1-byte length format
                        ndef_length = length_byte

                    # Extract NDEF message
                    if offset + ndef_length > len(tlv_bytes):
                        logging.error(f"NDEF message truncated: expected {ndef_length}, "
                                    f"got {len(tlv_bytes) - offset}")
                        return False, None, metadata

                    ndef_data = tlv_bytes[offset:offset + ndef_length]
                    offset += ndef_length

                    logging.info(f"Extracted NDEF message: {ndef_length} bytes")
                    break
                else:
                    logging.warning(f"Unknown TLV type: {tlv_type:#x}, skipping")
                    # Try to skip this TLV block
                    if offset < len(tlv_bytes):
                        skip_length = tlv_bytes[offset]
                        offset += 1 + skip_length

            if ndef_data is None:
                logging.error("No NDEF Message TLV found")
                return False, None, metadata

            return True, bytes(ndef_data), metadata

        except Exception as e:
            logging.error(f"Error parsing Type 2 memory: {e}")
            return False, None, None

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

    def _read_pages(self, start_page, count):
        """Read multiple consecutive pages from tag

        Args:
            start_page: First page number to read
            count: Number of pages to read (each page is 4 bytes)

        Returns:
            Tuple of (success, pages_data) where:
            - success: True if all pages read successfully
            - pages_data: bytes containing all page data concatenated, or None if failed
        """
        try:
            pages_data = bytearray()

            # MIFARE Ultralight read returns 16 bytes (4 pages) at a time
            # So we read in chunks and extract only the pages we need
            pages_read = 0
            current_page = start_page

            while pages_read < count:
                # Read starting at current_page (returns tuple: (success, 16 bytes = 4 pages))
                result = self.nfc.mifareultralight_ReadPage(current_page)

                # Handle tuple return value (success, data)
                if isinstance(result, tuple):
                    success, read_data = result
                    if not success or read_data is None:
                        logging.error(f"Failed to read from page {current_page}")
                        return False, None
                else:
                    # Fallback if API returns data directly
                    read_data = result
                    if read_data is None:
                        logging.error(f"Failed to read from page {current_page}")
                        return False, None

                # Convert to bytes if needed
                if isinstance(read_data, (list, bytearray)):
                    read_data = bytes(read_data)

                logging.debug(f"Read from page {current_page}: {read_data.hex()} ({len(read_data)} bytes)")

                # Calculate how many pages we need from this read
                pages_remaining = count - pages_read
                pages_to_take = min(4, pages_remaining)

                # Extract only the bytes we need (4 bytes per page)
                bytes_to_take = pages_to_take * 4
                pages_data.extend(read_data[:bytes_to_take])

                pages_read += pages_to_take
                current_page += pages_to_take

            logging.info(f"Read {count} pages ({len(pages_data)} bytes) starting from page {start_page}")
            return True, bytes(pages_data)

        except Exception as e:
            logging.error(f"Error reading pages: {e}")
            return False, None

    def _write_pages(self, start_page, data):
        """Write data to consecutive pages starting at start_page

        Args:
            start_page: First page number to write
            data: bytes to write (will be padded to 4-byte boundary)

        Returns:
            Tuple of (success, message) where:
            - success: True if all pages written successfully
            - message: Status message
        """
        try:
            # Pad to 4-byte boundary
            write_data = bytearray(data)
            while len(write_data) % 4 != 0:
                write_data.append(0x00)

            page = start_page
            offset = 0
            pages_written = 0

            while offset < len(write_data):
                # Get 4 bytes for this page
                page_data = write_data[offset:offset+4]

                # Write page
                success = self.nfc.mifareultralight_WritePage(page, page_data)

                if not success:
                    error_msg = f"Failed to write page {page}"
                    logging.error(error_msg)
                    return False, error_msg

                logging.debug(f"Wrote page {page}: {page_data.hex()}")

                page += 1
                offset += 4
                pages_written += 1

            success_msg = f"Wrote {len(data)} bytes ({pages_written} pages) starting at page {start_page}"
            logging.info(success_msg)
            return True, success_msg

        except Exception as e:
            error_msg = f"Error writing pages: {e}"
            logging.error(error_msg)
            return False, error_msg

    def _write_tag(self, url):
        """Write NDEF URL message to a Type 2 NFC tag

        Returns (success, message) tuple
        """
        try:
            # Build NDEF message
            ndef_data = self._build_ndef_uri_record(url)
            cc_bytes, tlv_bytes = self._build_type2_memory(ndef_data)

            total_bytes = len(cc_bytes) + len(tlv_bytes)
            logging.info(f"Writing {total_bytes} bytes to tag (CC: {len(cc_bytes)}, TLV: {len(tlv_bytes)})")

            # Write Capability Container to page 3
            success, message = self._write_pages(3, cc_bytes)
            if not success:
                error_msg = f"Failed to write Capability Container: {message}"
                logging.error(error_msg)
                return False, error_msg
            logging.info(f"Wrote CC to page 3: {cc_bytes.hex()}")

            # Write TLV data starting at page 4
            success, message = self._write_pages(4, tlv_bytes)
            if not success:
                error_msg = f"Failed to write TLV data: {message}"
                logging.error(error_msg)
                return False, error_msg

            tlv_pages = (len(tlv_bytes) + 3) // 4
            success_msg = f"Successfully wrote {total_bytes} bytes (1 CC page + {tlv_pages} TLV pages)"
            logging.info(success_msg)
            return True, success_msg

        except Exception as e:
            error_msg = f"Error writing tag: {e}"
            logging.error(error_msg)
            return False, error_msg

    def _read_tag(self):
        """Read and parse NDEF URL from a Type 2 NFC tag

        Returns:
            Tuple of (success, url, raw_ndef, metadata, uid) where:
            - success: True if tag read and parsed successfully
            - url: Extracted URL string, or None if failed
            - raw_ndef: Raw NDEF message bytes, or None if failed
            - metadata: Dictionary with CC info, or None if failed
            - uid: Tag UID as bytes, or None if failed
        """
        try:
            # We need to estimate how many pages to read
            # NTAG213 has 45 pages total (pages 0-44)
            # Pages 0-2: UID and internal
            # Page 3: CC (4 bytes)
            # Pages 4+: TLV data
            # We'll read up to page 40 to be safe (allows ~148 bytes of TLV data)

            # Read CC from page 3
            success, cc_data = self._read_pages(3, 1)
            if not success:
                logging.error("Failed to read Capability Container")
                return False, None, None, None, None

            logging.info(f"Read CC: {cc_data.hex()}")

            # Read TLV data starting from page 4
            # For safety, read enough pages to cover most NDEF messages
            # NTAG213 has room for ~130 bytes of TLV data (pages 4-36)
            success, tlv_data = self._read_pages(4, 33)
            if not success:
                logging.error("Failed to read TLV data")
                return False, None, None, None, None

            # Parse Type 2 memory layout
            success, ndef_data, metadata = self._parse_type2_memory(cc_data, tlv_data)
            if not success:
                logging.error("Failed to parse Type 2 memory layout")
                return False, None, None, metadata, None

            # Parse NDEF URI record
            success, url = self._parse_ndef_uri_record(ndef_data)
            if not success:
                logging.error("Failed to parse NDEF URI record")
                return False, None, ndef_data, metadata, None

            # Get UID from last scan (should be available from readPassiveTargetID)
            # Note: UID is already logged by _scan_for_tag, we just return None here
            # since the PN532 API doesn't provide a way to retrieve it after scanning

            logging.info(f"Successfully read tag with URL: {url}")
            return True, url, ndef_data, metadata, None

        except Exception as e:
            logging.error(f"Error reading tag: {e}")
            return False, None, None, None, None

    def _verify_tag(self, expected_url):
        """Verify that a tag contains the expected URL

        Args:
            expected_url: URL string to verify against

        Returns:
            Tuple of (success, match, actual_url) where:
            - success: True if tag read successfully
            - match: True if URL matches expected_url
            - actual_url: URL read from tag, or None if read failed
        """
        try:
            success, url, _, _, _ = self._read_tag()

            if not success:
                logging.error("Failed to read tag for verification")
                return False, False, None

            match = (url == expected_url)

            if match:
                logging.info(f"Tag verification SUCCESS: URL matches '{expected_url}'")
            else:
                logging.warning(f"Tag verification FAILED: expected '{expected_url}', got '{url}'")

            return True, match, url

        except Exception as e:
            logging.error(f"Error verifying tag: {e}")
            return False, False, None

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

    cmd_NFC_READ_TAG_help = "Read and display full details from an NFC tag"
    def cmd_NFC_READ_TAG(self, gcmd):
        gcode = self.printer.lookup_object('gcode')

        if not self.nfc:
            gcode.respond_info("Error: PN532 not initialized")
            return

        gcode.respond_info("Scanning for NFC tag...")

        # Scan for tag
        success, uid = self._scan_for_tag(timeout_ms=5000)

        if not success:
            gcode.respond_info("Error: No NFC tag detected. Place tag on reader and try again.")
            return

        gcode.respond_info(f"Tag detected: {uid.hex()}")
        gcode.respond_info("Reading tag...")

        # Read tag
        success, url, raw_ndef, metadata, _ = self._read_tag()

        if not success:
            gcode.respond_info("Error: Failed to read tag data")
            return

        # Display full tag details
        gcode.respond_info("=== Tag Details ===")
        gcode.respond_info(f"UID: {uid.hex()}")
        gcode.respond_info(f"URL: {url}")

        if metadata:
            gcode.respond_info(f"Tag Version: {metadata['version_major']}.{metadata['version_minor']}")
            gcode.respond_info(f"Memory Size: {metadata['memory_size']} bytes")
            access_r = metadata['read_access']
            access_w = metadata['write_access']
            gcode.respond_info(f"Access: Read={access_r:#x}, Write={access_w:#x}")

        if raw_ndef:
            gcode.respond_info(f"NDEF Length: {len(raw_ndef)} bytes")
            gcode.respond_info(f"NDEF Data: {raw_ndef.hex()}")

        gcode.respond_info("===================")

    cmd_NFC_VERIFY_TAG_help = "Verify that a tag contains the expected URL"
    def cmd_NFC_VERIFY_TAG(self, gcmd):
        gcode = self.printer.lookup_object('gcode')

        if not self.nfc:
            gcode.respond_info("Error: PN532 not initialized")
            return

        # Use URL parameter if provided, otherwise use current URL
        expected_url = gcmd.get('URL', self.current_url)

        gcode.respond_info("Scanning for NFC tag...")

        # Scan for tag
        success, uid = self._scan_for_tag(timeout_ms=5000)

        if not success:
            gcode.respond_info("Error: No NFC tag detected. Place tag on reader and try again.")
            return

        gcode.respond_info(f"Tag detected: {uid.hex()}")
        gcode.respond_info(f"Verifying against expected URL: {expected_url}")

        # Verify tag
        success, match, actual_url = self._verify_tag(expected_url)

        if not success:
            gcode.respond_info("Error: Failed to read tag for verification")
            return

        if match:
            gcode.respond_info(f"SUCCESS: Tag URL matches expected URL")
        else:
            gcode.respond_info(f"MISMATCH: Tag contains different URL")
            gcode.respond_info(f"  Expected: {expected_url}")
            gcode.respond_info(f"  Actual:   {actual_url}")

    cmd_NFC_TAG_INFO_help = "Display tag information (UID, type, memory, protection)"
    def cmd_NFC_TAG_INFO(self, gcmd):
        gcode = self.printer.lookup_object('gcode')

        if not self.nfc:
            gcode.respond_info("Error: PN532 not initialized")
            return

        gcode.respond_info("Scanning for NFC tag...")

        # Scan for tag
        success, uid = self._scan_for_tag(timeout_ms=5000)

        if not success:
            gcode.respond_info("Error: No NFC tag detected. Place tag on reader and try again.")
            return

        gcode.respond_info("=== Tag Information ===")
        gcode.respond_info(f"UID: {uid.hex()}")
        gcode.respond_info(f"UID Length: {len(uid)} bytes")

        # Determine tag type based on UID length
        if len(uid) == 4:
            tag_type = "MIFARE Classic or Ultralight"
        elif len(uid) == 7:
            tag_type = "NTAG or MIFARE Ultralight (7-byte UID)"
        elif len(uid) == 10:
            tag_type = "MIFARE DESFire or Plus"
        else:
            tag_type = "Unknown"

        gcode.respond_info(f"Tag Type: {tag_type}")

        # Try to read CC to get more info
        success, cc_data = self._read_pages(3, 1)
        if success:
            cc_magic = cc_data[0]
            cc_version = cc_data[1]
            cc_size = cc_data[2]
            cc_access = cc_data[3]

            if cc_magic == 0xE1:
                gcode.respond_info("Format: NDEF (Type 2 Tag)")
                version_major = (cc_version >> 4) & 0x0F
                version_minor = cc_version & 0x0F
                gcode.respond_info(f"NDEF Version: {version_major}.{version_minor}")
                gcode.respond_info(f"Memory Capacity: {cc_size * 8} bytes")

                read_access = (cc_access >> 4) & 0x0F
                write_access = cc_access & 0x0F

                if read_access == 0x00:
                    read_status = "Allowed"
                else:
                    read_status = f"Restricted (code {read_access:#x})"

                if write_access == 0x00:
                    write_status = "Allowed"
                elif write_access == 0x0F:
                    write_status = "Write-Protected"
                else:
                    write_status = f"Restricted (code {write_access:#x})"

                gcode.respond_info(f"Read Access: {read_status}")
                gcode.respond_info(f"Write Access: {write_status}")
                gcode.respond_info(f"CC Bytes: {cc_data.hex()}")
            else:
                gcode.respond_info(f"Format: Non-NDEF or unformatted (CC magic: {cc_magic:#x})")
        else:
            gcode.respond_info("Could not read Capability Container")

        gcode.respond_info("=======================")

def load_config(config):
    return KlippyNFC(config)
