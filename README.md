# KlippyNFC - NFC Tag Reader/Writer for Klipper and PN532 Modules

A Klipper plugin to read and write with a PN532 NFC module.

Write an NFC Tag with the Klipper Web Interface URL.
Experimental support for reading OpenPrintTags (COMING SOON!)

## Table of Contents

- [Hardware Requirements](#hardware-requirements)
- [Setup](#setup)
- [Usage](#usage)
  - [First-Time Tag Writing](#first-time-tag-writing)
  - [G-Code Commands Reference](#g-code-commands-reference)
  - [Common Workflows](#common-workflows)
- [Troubleshooting](#troubleshooting)
  - [Hardware Issues](#hardware-issues)
  - [Debugging](#debugging)
- [Technical Details](#technical-details)
- [Future Enhancements](#future-enhancements)

---

## Hardware Requirements

### Required Hardware

- **PN532 NFC Breakout Board**
  - Common vendors: Adafruit, Elechouse, generic modules
  - Must support SPI mode (most do)
  - ~$8-15 USD

- **Raspberry Pi with SPI**
  - Tested on: Raspberry Pi 4, Pi 3B+
  - Should work on: Pi Zero 2W, Pi 5
  - SPI interface must be enabled

- **External Power Supply for PN532**
  - Use external 3.3V or 5V power supply (check your PN532 voltage rating)
  - Recommended: Share Pi's 5V rail with proper decoupling capacitor (some boards include this)
  - **DO NOT** power PN532 from Pi's 3.3V pin - causes brownouts

### NFC Tags (Recommended)

**Best Choice: NTAG215**
- 504 bytes usable memory (plenty for URLs)
- Works with all modern phones (iPhone 7+, Android)
- Standard NFC Forum Type 2 tag
- Cost: ~$0.25-0.50 per tag in bulk

**Alternative Options:**
- **NTAG213** - 144 bytes (sufficient for most URLs, cheaper)
- **NTAG216** - 888 bytes (overkill for URLs, more expensive)
- **MIFARE Ultralight** - 48 bytes (too small, not recommended)

### Wiring Supplies

- Jumper wires (female-to-female recommended)

## Setup

### Step 1: Enable SPI on Raspberry Pi

The PN532 communicates via SPI, which must be enabled:

```bash
sudo raspi-config
```

Navigate: `3 Interface Options` → `I4 SPI` → `Yes` → `OK` → `Finish`

Reboot the Pi:
```bash
sudo reboot
```

Verify SPI is enabled:
```bash
ls /dev/spidev0.*
# Should show: /dev/spidev0.0  /dev/spidev0.1
```

### Step 2: Install Python Dependencies

Install the `pn532pi` library in Klipper's Python environment:

```bash
~/klippy-env/bin/pip install pn532pi
```

Verify installation:
```bash
~/klippy-env/bin/pip show pn532pi
```

### Step 3: Install Plugin

Copy the plugin file to Klipper's extras directory:

```bash
# If you cloned the repo:
cd /path/to/klippyNFC
cp klippy_nfc.py ~/klipper/klippy/extras/

# Or download directly:
wget https://raw.githubusercontent.com/erikbuild/klippyNFC/main/klippy_nfc.py -O ~/klipper/klippy/extras/klippy_nfc.py
```

### Step 4: Wire PN532 to Raspberry Pi

**Set PN532 to SPI Mode:**

Before wiring, configure the PN532 mode switches:
- Most PN532 boards have two small DIP switches (SW1, SW2)
- **For SPI mode:** SW1=OFF, SW2=ON
- Consult your specific board's documentation if different

**Wiring Table:**

| PN532 Pin | RPi Pin (Physical) | RPi GPIO | Description |
|-----------|-------------------|----------|-------------|
| VCC       | **See warning below** | - | Power (3.3V or 5V depending on board) |
| GND       | Pin 6 (or any GND) | Ground | Ground |
| SCK       | Pin 23 | GPIO 11 | SPI Clock (SCLK) |
| MISO      | Pin 21 | GPIO 9 | SPI MISO (Master In, Slave Out) |
| MOSI      | Pin 19 | GPIO 10 | SPI MOSI (Master Out, Slave In) |
| SS (NSS)  | Pin 24 | GPIO 8 | SPI Chip Select (CE0) |

**⚠️ POWER WARNING:**
- **DO NOT** connect VCC to Pi's 3.3V pin (Pin 1 or 17)
- The PN532 draws too much current and will cause brownouts
- **Options for proper power:**
  - Use external 3.3V/5V power supply with shared ground
  - Connect to Pi's 5V pin (Pin 2 or 4) **only if** your PN532 has a 5V→3.3V regulator
- When in doubt, check your PN532's voltage rating and current requirements

**Wiring Diagram:**
```
Raspberry Pi          PN532 (SPI Mode)
┌──────────┐         ┌────────────┐
│  Pin 23  │────────▶│ SCK        │
│  Pin 21  │◀────────│ MISO       │
│  Pin 19  │────────▶│ MOSI       │
│  Pin 24  │────────▶│ SS         │
│  Pin 6   │────────▶│ GND        │
│  Pin 2   │────────▶│ VCC        │
└──────────┘         └────────────┘
```

### Step 5: Configure Klipper

Add this section to your `printer.cfg`:

```ini
[klippy_nfc]
# SPI Configuration (required)
spi_bus: 0              # SPI bus number: 0 for SPI0 (default), 1 for SPI1
spi_ce: 0               # Chip select: 0 for CE0/GPIO8 (default), 1 for CE1/GPIO7

# URL Configuration (optional)
port: 80              # Web interface port (default: 80 for Mainsail)
# url: http://192.168.1.100:80  # Explicit URL override (auto-detected if not set)
```

**Configuration Notes:**
- `spi_bus` and `spi_ce` defaults match standard wiring above
- `port` should match your Mainsail configuration (usually 80)
- `url` is auto-detected from hostname/IP if not specified
- If your network uses mDNS, the auto-detected URL will use `.local` domain

### Step 6: Restart Klipper

Apply the configuration changes:

```bash
sudo systemctl restart klipper
```

Check for errors:
```bash
tail -50 ~/printer_config/logs/klippy.log
```

Look for:
- `NFC tag writer ready. Use NFC_WRITE_TAG to write tags with URL: http://...`
- **No errors** about PN532 initialization

If you see `Failed to initialize PN532`, check wiring and power supply.

## Usage

### First-Time Tag Writing

**Step-by-step:**

1. **Prepare a blank NFC tag** (NTAG215 recommended)

2. **Place tag on PN532 reader**
   - Position tag flat against the PN532 antenna
   - Tag should be centered over the chip
   - Keep phone away during writing to avoid interference

3. **Open your Klipper web interface** (Mainsail/Fluidd)
   - Navigate to the G-code console

4. **Run the write command:**
   ```gcode
   NFC_WRITE_TAG
   ```

5. **Wait for completion**
   - You should see:
     ```
     Scanning for NFC tag...
     Tag detected: 04a1b2c3d4e5f6
     Writing URL: http://printer.local:7125
     Success! Successfully wrote 48 bytes (12 pages)
     ```

6. **Remove tag**
   - Your tag is now programmed!
   - Test by tapping your phone to it

### G-Code Commands Reference

#### NFC_WRITE_TAG

Write the current URL to an NFC tag.

**Basic usage:**
```gcode
NFC_WRITE_TAG
```

**With custom URL:**
```gcode
NFC_WRITE_TAG URL=http://192.168.1.100:7125
```

**With custom port:**
```gcode
NFC_WRITE_TAG URL=http://ender3.local:80
```

**Examples:**
```gcode
# Write tag for Mainsail on default port
NFC_WRITE_TAG

# Write tag for specific IP and port
NFC_WRITE_TAG URL=http://10.0.1.50:7125

# Write tag for Fluidd
NFC_WRITE_TAG URL=http://fluidd.local:7125

# Write tag for custom port
NFC_WRITE_TAG URL=http://prusa-mk4.local:8080
```

**Output:**
```
Scanning for NFC tag...
Tag detected: 04123456789abc
Writing URL: http://printer.local:7125
Success! Successfully wrote 48 bytes (12 pages)
```

**Errors:**
```
Error: No NFC tag detected. Place tag on reader and try again.
Error: Failed to write page 5
```

#### NFC_STATUS

Display current tag writer status and configuration.

**Usage:**
```gcode
NFC_STATUS
```

**Output when never written:**
```
Current URL: http://printer.local:7125
Last write: Not written yet
```

**Output after successful write:**
```
Current URL: http://printer.local:7125
Last write: Successfully wrote 48 bytes (12 pages)
Write time: 2025-01-15 14:23:45
```

**Output after failed write:**
```
Current URL: http://printer.local:7125
Last write: Failed: No tag detected
Write time: 2025-01-15 14:20:12
```

#### NFC_SET_URL

Change the URL that will be written to future tags.

**Usage:**
```gcode
NFC_SET_URL URL=http://new-url.local:7125
```

**Examples:**
```gcode
# Change to specific IP
NFC_SET_URL URL=http://192.168.1.100:7125

# Change to custom domain
NFC_SET_URL URL=http://my-printer.home:7125

# Change port
NFC_SET_URL URL=http://printer.local:80
```

**Output:**
```
NFC URL updated to: http://192.168.1.100:7125
```

**Notes:**
- This only affects future tag writes
- Already-written tags are not affected
- Change persists until Klipper restart (reverts to config/auto-detected URL)
- Use this for writing multiple tags with different URLs

## Troubleshooting

### Phone Compatibility

Physical NFC tags written by this plugin are standard NDEF format and work with:

- ✅ **iPhone 7 and later** (iOS 14+ required for automatic reading)
  - Works in background - no app needed
  - Notification appears when tag is detected

- ✅ **Android phones with NFC** (Android 4.0+)
  - NFC must be enabled in Settings
  - Opens browser automatically

### Hardware Issues

#### "Failed to initialize PN532"

**Symptom:** Klipper log shows `Failed to initialize PN532, NFC tag writing disabled`

**Causes and fixes:**
1. **Wiring problems**
   - Double-check all 6 connections (VCC, GND, SCK, MISO, MOSI, SS)
   - Ensure wires are firmly seated
   - Try different jumper wires (they can be faulty)
   - Check for cold solder joints if you soldered connections

2. **SPI not enabled**
   - Verify: `ls /dev/spidev0.*` should show devices
   - Re-run: `sudo raspi-config` → Interface Options → SPI → Enable
   - Reboot after enabling

3. **Wrong SPI mode**
   - Check PN532 mode switches: SW1=OFF, SW2=ON for SPI
   - Power cycle PN532 after changing switches
   - Some boards use jumpers instead of switches - check your board's docs

4. **Power supply insufficient**
   - PN532 needs stable 3.3V or 5V (check your board's specs)
   - **DO NOT** use Pi's 3.3V pin (Pin 1/17) - insufficient current
   - Use external power supply or Pi's 5V pin (if your board has regulator)
   - Add 10μF capacitor between VCC and GND for stability

5. **Wrong chip select pin**
   - Default uses CE0 (GPIO 8, Pin 24)
   - If using CE1: change `spi_ce: 1` in config
   - Verify wiring matches config

#### "pn532pi library not found"

**Symptom:** Import error in Klipper logs

**Fix:**
```bash
# Install in Klipper's Python environment
~/klippy-env/bin/pip install pn532pi

# Verify installation
~/klippy-env/bin/pip show pn532pi

# If still not found, try reinstalling
~/klippy-env/bin/pip uninstall pn532pi
~/klippy-env/bin/pip install pn532pi
```

### Debugging

#### Check Klipper Logs

View NFC-related log messages:
```bash
# Tail logs in real-time
tail -f /tmp/klippy.log | grep -i nfc

# View recent logs
tail -100 /tmp/klippy.log | grep -i nfc

# View all NFC logs
grep -i nfc /tmp/klippy.log
```

**What to look for:**
```
# Good - initialization successful
NFC tag writer ready. Use NFC_WRITE_TAG to write tags with URL: http://...
PN532 firmware version: 0x32

# Bad - hardware not detected
Failed to initialize PN532: ...
Failed to communicate with PN532

# During tag write
Scanning for NFC tag...
Tag detected: 04abc123...
Writing URL: http://...
Wrote page 4: e1106d00...
Successfully wrote 48 bytes (12 pages)
```

#### Test PN532 Directly

Verify PN532 works outside of Klipper:

```bash
# Activate Klipper's Python environment
source ~/klippy-env/bin/activate

# Test Python script
python3 << 'EOF'
from pn532pi import Pn532, Pn532Spi

spi = Pn532Spi(0)  # CE0
nfc = Pn532(spi)
nfc.begin()

version = nfc.getFirmwareVersion()
if version:
    print(f"PN532 firmware version: {version:#x}")
    print("PN532 is working!")
else:
    print("Failed to communicate with PN532")
EOF
```

If this fails, it's a hardware/wiring issue, not a Klipper issue.

#### Common Log Errors and Meanings

| Error Message | Meaning | Fix |
|---------------|---------|-----|
| `Failed to communicate with PN532` | No response from PN532 | Check wiring, power, SPI mode |
| `pn532pi library not found` | Python dependency missing | Install pn532pi |
| `No NFC tag detected` | Tag not in range or incompatible | Check tag type, placement |
| `Failed to write page X` | Write operation failed | Check tag protection, memory |
| `Chip select must be 1 or 0` | Invalid config value | Fix `spi_ce` in printer.cfg |

## Technical Details

### NFC Technology

**Tag Type:** NFC Forum Type 2 Tag
- Based on ISO/IEC 14443-3 Type A protocol
- Operates at 13.56 MHz
- Compatible tags: NTAG213/215/216, MIFARE Ultralight

**NDEF Format:**
- URI Record Type with prefix compression
- Standard NFC Data Exchange Format
- Universal compatibility across all NFC phones

**Memory Layout (Type 2 tags):**
```
Page 0-3:  UID and lock bytes (read-only, managed by tag chip)
Page 4:    Capability Container (CC)
           - Magic: 0xE1
           - Version: 0x10
           - Size: 0x6D (880 bytes)
           - Access: 0x00 (read/write)
Page 5+:   NDEF message in TLV format
           - TLV Type: 0x03 (NDEF Message)
           - TLV Length: varies
           - NDEF data: URL record
           - Terminator: 0xFE
```

**Write Process:**
1. Scan for tag using `readPassiveTargetID()` (5-second timeout)
2. Build NDEF URI record with URL prefix compression
3. Format as Type 2 memory layout
4. Write page-by-page (4 bytes per page) using `ntag2xx_WritePage()`
5. Start at page 4 (pages 0-3 are read-only UID/locks)

### URL Discovery

The plugin automatically discovers your web interface URL:

1. **Hostname lookup:** `socket.gethostname()`
2. **IP fallback:** If hostname is "localhost", connects to 8.8.8.8 to determine local IP
3. **Port configuration:** Uses `port` parameter (default 7125)
4. **Manual override:** `url` parameter takes precedence if set

**Example auto-detected URLs:**
- `http://mainsailos.local:80` (hostname with mDNS)
- `http://192.168.1.100:80` (IP address)
- `http://prusawire:80` (custom hostname)

## Future Enhancements

**Planned Features:**
- Tag reading capability (verify written URL)

**Potential Features:**
- I2C and UART interface support
- Material/filament tracking with NFC tags
- Print job information embedding
- Access control via NFC authentication
- Integration with Klipper's notification system
- QR code generation alongside NFC tags
- Multi-URL tags (select URL based on context)
- Custom NDEF records (not just URLs)

## License

MIT License - see LICENSE file

## Contributing

Contributions welcome! Please test thoroughly with your hardware before submitting PRs.

## Acknowledgments

- Built on [pn532pi](https://github.com/gassajor000/pn532pi) by gassajor000
- Inspired by Seeed Studio's PN532 Arduino library
