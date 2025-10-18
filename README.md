# KlippyNFC - NFC Tag Writer for Klipper

A Klipper plugin that uses a PN532 NFC module to write NFC tags with your Klipper web interface URL. Write tags once, then tap your phone to them anytime to instantly access your printer's Mainsail, Fluidd, or Moonraker interface.

**Perfect for:**
- Quick access to printer web interface from your phone
- Sharing printer access with others (guests, family, colleagues)
- Labeling multiple printers in a farm
- Creating portable "business cards" for your printer setup

---

## Table of Contents

- [Hardware Requirements](#hardware-requirements)
- [Quick Start](#quick-start)
- [Detailed Installation](#detailed-installation)
- [Usage](#usage)
  - [First-Time Tag Writing](#first-time-tag-writing)
  - [G-Code Commands Reference](#g-code-commands-reference)
  - [Common Workflows](#common-workflows)
- [Troubleshooting](#troubleshooting)
  - [Hardware Issues](#hardware-issues)
  - [Tag Detection Issues](#tag-detection-issues)
  - [Network/URL Issues](#networkurl-issues)
  - [Debugging](#debugging)
- [FAQ](#frequently-asked-questions-faq)
- [Technical Details](#technical-details)
- [Limitations](#limitations)
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
  - **CRITICAL:** PN532 draws too much current for Pi's 3.3V regulator
  - Use external 3.3V or 5V power supply (check your PN532 voltage rating)
  - Recommended: Share Pi's 5V rail with proper decoupling capacitor
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

**Where to Buy:**
- Amazon: Search "NTAG215 blank NFC tags"
- AliExpress: Bulk packs (100+ tags) for best pricing

**Physical Formats:**
- Round stickers (20-30mm diameter) - most common

### Wiring Supplies

- Jumper wires (female-to-female recommended)
- Breadboard (optional, for testing)
- Soldering iron (if you want permanent connections)

## Quick Start

1. **Enable SPI:** `sudo raspi-config` → Interface Options → SPI → Enable → Reboot
2. **Install library:** `~/klippy-env/bin/pip install pn532pi`
3. **Copy plugin:** `cp klippy_nfc.py ~/klipper/klippy/extras/`
4. **Wire PN532** (see wiring table below)
5. **Add config** to `printer.cfg` (see configuration section)
6. **Restart Klipper:** `sudo systemctl restart klipper`
7. **Write a tag:** Place blank tag on PN532, run `NFC_WRITE_TAG` in console

## Detailed Installation

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
  - Use a breadboard power supply
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
│ External │────────▶│ VCC        │
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

### Common Workflows

#### Single Printer Setup

Write one tag and stick it to your printer enclosure:

```gcode
NFC_WRITE_TAG
```

Tap your phone to the tag whenever you need quick access.

#### Multiple Printer Farm

Write different tags for each printer:

```gcode
# Printer 1
NFC_SET_URL URL=http://prusawire.local:7125
NFC_WRITE_TAG

# Printer 2
NFC_SET_URL URL=http://voron-24.local:7125
NFC_WRITE_TAG

# Printer 3
NFC_SET_URL URL=http://prusa-mk4.local:7125
NFC_WRITE_TAG
```

Label and attach tags to each printer.

### Using Written Tags

Once a tag is written, anyone with a compatible phone can use it:

**iPhone (iOS 14+):**
1. Hold phone near tag (screen on, no app needed)
2. Notification appears at top of screen
3. Tap notification to open URL in Safari

**Android:**
1. Ensure NFC is enabled in Settings
2. Hold phone near tag (screen on, unlocked)
3. Browser opens automatically with URL

**Tips:**
- Tags work through thin materials (stickers, paper, thin plastic)
- Don't cover tags with metal - blocks NFC signal
- Tags are read-only after writing (can't be accidentally erased by phone)
- Tags work indefinitely - no battery or maintenance needed

## Troubleshooting

### Phone Compatibility

Physical NFC tags written by this plugin are standard NDEF format and work with:

- ✅ **iPhone 7 and later** (iOS 14+ required for automatic reading)
  - iPhone 7, 8, X, XR, XS, 11, 12, 13, 14, 15, 16
  - Works in background - no app needed
  - Notification appears when tag is detected

- ✅ **Android phones with NFC** (Android 4.0+)
  - Samsung Galaxy S series, Google Pixel, OnePlus, etc.
  - NFC must be enabled in Settings
  - Opens browser automatically

- ✅ **Other NFC-enabled devices**
  - Some smartwatches
  - Tablets with NFC

**Not compatible:**
- ❌ iPhone 6 and earlier (no NFC hardware)
- ❌ Phones without NFC capability
- ❌ Devices with NFC disabled in settings

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

#### Random Resets, Brownouts, or Intermittent Failures

**Symptoms:**
- PN532 works sometimes, fails other times
- Raspberry Pi reboots unexpectedly
- "Failed to communicate with PN532" errors

**Cause:** Power supply issues

**Solution:**
1. **Use external power supply** - 3.3V or 5V depending on your PN532 board
2. Add **decoupling capacitor** (10-100μF) across VCC and GND near PN532
3. Use **shorter wires** (< 6 inches) to reduce voltage drop
4. Ensure **adequate PSU** for your Raspberry Pi (3A minimum for Pi 4)

### Tag Detection Issues

#### "No NFC tag detected"

**Symptom:** `NFC_WRITE_TAG` command returns "Error: No NFC tag detected"

**Causes and fixes:**

1. **Tag not compatible**
   - ✅ Compatible: NTAG213, NTAG215, NTAG216, MIFARE Ultralight
   - ❌ Not compatible: MIFARE Classic, MIFARE DESFire, other proprietary formats
   - Check tag specifications from vendor

2. **Poor tag placement**
   - Place tag **flat** against PN532 antenna
   - Center tag over the chip (usually marked on PCB)
   - Remove any thick protective cases
   - Try different orientations

3. **Tag already written/locked**
   - Some tags can be write-protected
   - Try a fresh, confirmed-blank tag
   - Use a phone NFC app to check tag status

4. **Phone interfering**
   - Keep your phone **away** from PN532 during writing
   - Phone's NFC can interfere with detection

5. **Tag damaged**
   - NFC tags can be damaged by:
     - Static electricity
     - Bending/creasing
     - Exposure to strong magnetic fields
   - Try a different tag

#### Tag Detected But Write Fails

**Symptom:** "Tag detected" message but then "Failed to write page X"

**Causes:**
1. **Write-protected tag**
   - Some tags have write-protection bits set
   - Cannot be undone on NTAG tags
   - Use a fresh blank tag

2. **Insufficient tag memory**
   - Long URLs may not fit on NTAG213 (144 bytes)
   - Use NTAG215 (504 bytes) or NTAG216 (888 bytes)
   - Or use shorter URL (IP instead of hostname)

3. **Tag communication error**
   - Improve power supply stability
   - Keep tag stationary during write
   - Reduce electrical noise (move away from motors, power supplies)

### Network/URL Issues

#### "URL shows 'printer.local' but doesn't work"

**Symptom:** Tag is written successfully but phone can't reach printer

**Causes:**
1. **mDNS not working on network**
   - Some networks block mDNS (.local domains)
   - Corporate/guest WiFi often blocks it
   - Phone and printer on different subnets

**Solutions:**
```ini
# Use explicit IP address in config
[klippy_nfc]
url: http://192.168.1.100:7125

# Or use a static hostname (if you have local DNS)
url: http://ender3.home:7125
```

#### Phone Opens Wrong URL

**Symptom:** Tag works but opens incorrect address

**Cause:** Tag contains old/wrong URL

**Solution:**
```gcode
# Verify current URL
NFC_STATUS

# Update URL
NFC_SET_URL URL=http://correct-address:7125

# Write new tag (tags can't be rewritten - use fresh tag)
NFC_WRITE_TAG
```

**Note:** NTAG tags **cannot be fully erased** after writing. Always use a fresh blank tag for corrections.

### iPhone-Specific Issues

#### iPhone Not Detecting Tags

**Requirements:**
- iPhone 7 or later (has NFC hardware)
- iOS 14 or later (for background NFC reading)
- Screen must be on (locked or unlocked OK)

**Troubleshooting:**
1. **Update iOS** to latest version
2. **Enable NFC** (should be on by default)
3. **Try different tag position** - iPhone's NFC antenna location varies by model:
   - iPhone 7-8: Top back
   - iPhone X and later: Top front (camera area)
4. **Remove thick case** - may block NFC
5. **Test with another tag** - confirm tag works on Android first

#### iPhone Shows Notification But Nothing Happens

**Cause:** Need to tap the notification

**Solution:** When notification appears, **tap it** to open URL in Safari

### Android-Specific Issues

#### Android Not Detecting Tags

1. **Enable NFC** in Settings:
   - Settings → Connected Devices → Connection Preferences → NFC
   - Toggle NFC to ON

2. **Screen must be on and unlocked** (most Android devices)

3. **Try NFC Tools app** (free) to verify tag is readable

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

## Frequently Asked Questions (FAQ)

### General Questions

**Q: Can I rewrite a tag if I made a mistake?**

A: No. NTAG tags are write-once for data sectors. Once written, the NDEF data cannot be fully erased. Always use a fresh blank tag if you need to change the URL.

**Q: How many tags can I write?**

A: Unlimited. The PN532 can write as many tags as you have blank tags available.

**Q: Do tags need batteries?**

A: No. NFC tags are passive devices powered by the phone's NFC field when read. They last indefinitely.

**Q: Can tags be read by multiple phones?**

A: Yes. Tags can be read by any NFC-enabled phone unlimited times.

**Q: Will this work with my phone?**

A: If your phone has NFC and is iPhone 7+ (iOS 14+) or Android 4.0+, yes.

**Q: How close does my phone need to be?**

A: Within ~1-2 inches (2-5 cm). NFC is very short range by design.

### Setup Questions

**Q: Do I need to keep the PN532 connected after writing tags?**

A: No. You can disconnect the PN532 after writing all your tags. It's only needed for writing, not for using the tags. However, leaving it connected allows you to write new tags anytime via G-code.

**Q: Can I use I2C or UART instead of SPI?**

A: Currently only SPI is supported. I2C/UART support could be added in the future if there's demand.

**Q: Why do I need external power for PN532?**

A: The PN532 draws 100-150mA peak current, exceeding the Pi's 3.3V regulator capacity (50mA). Using Pi's 3.3V causes voltage drops and communication failures. You can most likely use the Pi's 5V pin as long as you are using a decent power supply for the Pi.

**Q: Can I use this with OctoPrint instead of Klipper?**

A: This plugin is Klipper-specific. An OctoPrint version would need to be written separately.

### Tag Questions

**Q: What's the difference between NTAG213, NTAG215, and NTAG216?**

A: Memory size:
- NTAG213: 144 bytes user memory (~25-30 character URL)
- NTAG215: 504 bytes user memory (~90 character URL)
- NTAG216: 888 bytes user memory (~160 character URL)

NTAG215 is recommended for most URLs.

**Q: Can I use MIFARE Classic tags?**

A: No. This plugin only supports NTAG and MIFARE Ultralight (Type 2 tags). MIFARE Classic uses a different protocol.

**Q: Will tags stop working after some time?**

A: No. NFC tags have no wear-out mechanism and will last decades under normal conditions.

**Q: How do I know if a tag is blank?**

A: Use a phone app like "NFC Tools" (iOS/Android) to read the tag. Blank tags show empty user memory.

### Printing Questions

**Q: Does writing a tag pause my print?**

A: The write command blocks G-code execution for 1-2 seconds. Don't write tags during critical print operations. Write tags when idle.

**Q: Can I trigger tag writing from G-code macros?**

A: Yes, you can include `NFC_WRITE_TAG` in macros, but be aware it blocks execution briefly.

### Troubleshooting Questions

**Q: Why does my phone say "No supported app for this NFC tag"?**

A: This usually means the tag write failed or the tag is corrupted. Try writing a fresh tag and verify with `NFC_STATUS` that write was successful.

**Q: The tag works on Android but not iPhone - why?**

A: Ensure iPhone is running iOS 14+ and the screen is on. Try holding the phone in different positions - iPhones have the NFC antenna in different locations depending on model.

**Q: Can I make the URL shorter to fit on smaller tags?**

A: Yes. Use an IP address instead of hostname (`192.168.1.5` instead of `my-long-printer-hostname.local`), or use a custom port 80 to omit the port number (`http://printer.local` instead of `http://printer.local:7125`).

**Q: My PN532 red LED is on but nothing works - what's wrong?**

A: Red LED indicates power only. Check:
- SPI mode switches (SW1=OFF, SW2=ON)
- Wiring connections
- SPI enabled on Pi
- Check Klipper logs for specific errors

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


### Operation Characteristics

**Performance:**
- Tag detection: < 1 second
- Tag write: 1-2 seconds (depends on URL length)
- Blocking operation: G-code execution pauses during write
- Power consumption: ~100mA @ 3.3V during active operation

**Reliability:**
- Write verification: Each page write returns success/fail status
- No retry mechanism: If write fails, operation aborts
- Tag state: Partially written tags may be corrupted - discard and use fresh tag

**Compatibility:**
- Klipper: 0.10.0+ (any recent version)
- Python: 3.7+ (Klipper's Python environment)
- pn532pi: 1.6+ (latest recommended)
- PN532 Firmware: All versions (standard firmware)

## Limitations

- ✅ **What works:**
  - Standard NTAG and MIFARE Ultralight tags (Type 2)
  - URLs up to ~800 characters (depending on tag memory)
  - Universal phone compatibility (iPhone 7+, Android 4.0+)
  - Unlimited tag writes (one tag at a time)

- ❌ **What doesn't work:**
  - Rewriting existing tags (tags are write-once for data)
  - MIFARE Classic or DESFire tags (different protocols)
  - Encrypted/secured tags
  - Reading data back from tags
  - Simultaneous multiple tag writing
  - Background tag writing (blocks during operation)

- ⚠️ **Known issues:**
  - Requires 5V from Pi OR 3.3V external power for PN532 (Pi's 3.3V insufficient)
  - Write operation blocks G-code for 1-2 seconds
  - No visual feedback during write (check logs or console)
  - Cannot detect write failures on locked tags until write attempt

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
