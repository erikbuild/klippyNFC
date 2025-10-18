# KlippyNFC - NFC Tag Writer for Klipper

A Klipper plugin that uses a PN532 NFC module to write NFC tags with your Klipper web interface URL (usually Mainsail). Write tags once, then tap your phone to them anytime to instantly access your printer's web interface.

## Hardware Requirements

- PN532 NFC breakout board
- Raspberry Pi 4 (or compatible) with SPI enabled
- External 3.3V or 5V power supply for PN532 (Pi's 3.3V regulator insufficient)
- Blank NFC tags (Type 2: NTAG213/215/216, MIFARE Ultralight)

## Installation

### 1. Enable SPI on Raspberry Pi

```bash
sudo raspi-config
# Navigate to: Interface Options -> SPI -> Enable
sudo reboot
```

### 2. Install Python Dependencies

```bash
~/klippy-env/bin/pip install pn532pi
```

### 3. Install Plugin

Copy `klippy_nfc.py` to your Klipper extras directory:

```bash
cp klippy_nfc.py ~/klipper/klippy/extras/
```

### 4. Wire PN532 to Raspberry Pi

**PN532 SPI Mode Wiring:**

| PN532 Pin | RPi Pin | Description |
|-----------|---------|-------------|
| VCC       | External 3.3V/5V | Power (DO NOT use Pi's 3.3V) |
| GND       | GND (Pin 6) | Ground |
| SCK       | GPIO 11 (Pin 23) | SPI Clock |
| MISO      | GPIO 9 (Pin 21) | SPI MISO |
| MOSI      | GPIO 10 (Pin 19) | SPI MOSI |
| SS        | GPIO 8 (Pin 24) | SPI Chip Select (default) |

**Important:** Set PN532 to SPI mode using the onboard switches (typically: SW1=OFF, SW2=ON).

### 5. Configure Klipper

Add to your `printer.cfg`:

```ini
[klippy_nfc]
# SPI configuration
spi_bus: 0              # Default: 0 (SPI0)
spi_ce: 0               # Default: 0 (CE0=GPIO8/Pin24), use 1 for CE1=GPIO7/Pin26

# Network configuration
port: 7125              # Default: 7125 (Moonraker default port)
# url: http://custom.local:7125  # Optional: Override auto-detected URL

# NFC tag UID (hex string, 3 bytes)
uid: 010203             # Default: 010203
```

### 6. Restart Klipper

```bash
sudo systemctl restart klipper
```

## Usage

### Writing Tags

1. Place a blank NFC tag on the PN532 reader
2. Run the write command via G-code console or Mainsail/Fluidd interface:
```gcode
NFC_WRITE_TAG
```
3. Wait for confirmation message
4. Remove tag - it's now programmed!

### G-Code Commands

**NFC_WRITE_TAG**
Write the current URL to an NFC tag:
```gcode
NFC_WRITE_TAG
```
Or specify a custom URL:
```gcode
NFC_WRITE_TAG URL=http://192.168.1.100:7125
```

**NFC_STATUS**
Display tag writer status:
```gcode
NFC_STATUS
```
Output:
```
Current URL: http://printer.local:7125
Last write: Successfully wrote 48 bytes (12 pages)
Write time: 2025-01-15 14:23:45
```

**NFC_SET_URL**
Change the URL for future tag writes:
```gcode
NFC_SET_URL URL=http://192.168.1.100:7125
```

### Using Written Tags

1. Write a tag using the commands above
2. Place the tag anywhere convenient (printer enclosure, workbench, etc.)
3. Tap your phone to the tag anytime
4. Your phone opens the Klipper web interface automatically

## Troubleshooting

### Phone Compatibility

Physical NFC tags written by this plugin work with:
- ✅ iPhone 7 and later (all models with NFC)
- ✅ Android phones with NFC enabled
- ✅ Most modern smartphones

Tags are standard NDEF format and universally compatible.

### Common Issues

**"Failed to initialize PN532"**
- Check SPI wiring connections
- Verify SPI is enabled: `ls /dev/spidev0.0`
- Ensure PN532 has adequate power supply
- Check PN532 mode switches (should be set to SPI)

**"pn532pi library not found"**
```bash
~/klippy-env/bin/pip install pn532pi
```

**"No NFC tag detected"**
- Ensure tag is Type 2 compatible (NTAG213/215/216 or MIFARE Ultralight)
- Place tag flat against PN532 antenna
- Tag may already be locked/protected - try a fresh blank tag

**"Failed to write page X"**
- Tag may be write-protected
- Tag memory may be full
- Try a different tag with more memory (NTAG216 has 888 bytes)

**Random resets or communication failures**
- PN532 likely underpowered
- Connect external 3.3V or 5V power supply
- Do NOT power from Pi's 3.3V pin

**URL shows "printer.local" but doesn't work**
- Set explicit URL in config:
```ini
[klippy_nfc]
url: http://192.168.1.100:7125  # Use your Pi's IP address
```

### Viewing Logs

Check Klipper logs for NFC-related messages:
```bash
tail -f /tmp/klippy.log | grep -i nfc
```

## Technical Details

### NFC Tag Writing

- **Tag Type:** NFC Forum Type 2 Tag (NTAG/MIFARE Ultralight)
- **Protocol:** ISO/IEC 14443-3 Type A
- **NDEF Record:** URI Record with URL prefix compression
- **Write Method:** Page-by-page writing starting at page 4

### URL Discovery

The plugin automatically discovers the web interface URL:
1. Gets system hostname via `socket.gethostname()`
2. Falls back to IP address if hostname is "localhost"
3. Uses configured port (default: 7125 for Moonraker)
4. Can be overridden with `url` config parameter

### Operation

Tag writing is synchronous and blocks during the write operation (typically 1-2 seconds). The PN532 is initialized once at startup and ready to write tags on demand via G-code commands.

## Limitations

- Requires blank Type 2 NFC tags (NTAG or MIFARE Ultralight)
- Tags must be purchased separately
- Requires external power for PN532
- Write operation blocks G-code execution for 1-2 seconds

## Future Enhancements

- Bulk tag writing for multiple printers
- Material/filament tracking with NFC tags
- Access control via NFC authentication
- QR code generation alongside NFC tags

## License

MIT License - see LICENSE file

## Contributing

Contributions welcome! Please test thoroughly with your hardware before submitting PRs.

## Acknowledgments

- Built on [pn532pi](https://github.com/gassajor000/pn532pi) by gassajor000
- Inspired by Seeed Studio's PN532 Arduino library
- NFC Forum for NDEF specifications
