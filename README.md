# KlippyNFC - NFC Tag to Web Interface for Klipper

A Klipper plugin that uses a PN532 NFC module to emulate an NFC tag presenting your Klipper web interface URL (usually Mainsail). Tap your phone to the NFC module and instantly access your printer's web interface.

## Hardware Requirements

- PN532 NFC breakout board
- Raspberry Pi 4 (or compatible) with SPI enabled
- External 3.3V or 5V power supply for PN532 (Pi's 3.3V regulator insufficient)

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

### G-Code Commands

**NFC_STATUS**
Display current NFC emulation status:
```gcode
NFC_STATUS
```
Output:
```
NFC Emulation: running
Current URL: http://printer.local:7125
Error count: 0
```

**NFC_SET_URL**
Change the emulated URL dynamically:
```gcode
NFC_SET_URL URL=http://192.168.1.100:7125
```

**NFC_RESTART**
Restart NFC emulation (useful after configuration changes):
```gcode
NFC_RESTART
```

### Using with Your Phone

1. Ensure NFC is enabled on your phone
2. Tap your phone to the PN532 module
3. Your phone should prompt you to open the Klipper web interface URL
4. Tap to open in your browser

## Troubleshooting

### iPhone Compatibility

**Known Issue:** iPhone NFC reading of PN532 emulated tags is limited and unreliable:
- Maximum 47 bytes can be transmitted
- Detection may fail entirely
- Works better on newer iPhones (XR and later)

**Workaround:** If iPhone compatibility is critical, consider using the PN532 in reader/writer mode to program a physical NFC sticker instead.

### Android Compatibility

Android devices generally have better compatibility with PN532 card emulation.

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

### NFC Tag Emulation

- **Tag Type:** NFC Forum Type 4 Tag
- **Protocol:** ISO/IEC 14443-4 (ISO-DEP)
- **NDEF Record:** URI Record with URL prefix compression
- **Mode:** Passive target emulation

### URL Discovery

The plugin automatically discovers the web interface URL:
1. Gets system hostname via `socket.gethostname()`
2. Falls back to IP address if hostname is "localhost"
3. Uses configured port (default: 7125 for Moonraker)
4. Can be overridden with `url` config parameter

### Thread Safety

NFC emulation runs in a daemon background thread, preventing blocking of Klipper's main event loop.

## Limitations

- iPhone compatibility limited (47-byte max, unreliable)
- Type 4 tag protocol simplified (may not work with all readers)
- Requires external power for PN532

## Future Enhancements

- Support for physical NFC tag writing mode
- Material tracking with NFC tags
- Access control via NFC authentication
- Multi-URL profiles (e.g., Mainsail, Fluidd, Moonraker)

## License

MIT License - see LICENSE file

## Contributing

Contributions welcome! Please test thoroughly with your hardware before submitting PRs.

## Acknowledgments

- Built on [pn532pi](https://github.com/gassajor000/pn532pi) by gassajor000
- Inspired by Seeed Studio's PN532 Arduino library
- NFC Forum for NDEF specifications
