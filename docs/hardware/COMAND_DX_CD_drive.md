# Mercedes COMAND APS DX (COMAND 2.0/2.5) — CD navigation drive: hardware analysis

Reverse-engineering notes for the internal CD drive of the DX-generation COMAND units
(Blaupunkt TravelPilot DX-based, maps on CD, "program loads from the navigation CD").

Unit: top box of the 3-part COMAND 2.0 (upper box = CD drive + GPS receiver + gyroscope;
sources: [COMAND 2.0 overview (VK)](https://vk.com/topic-91074655_31744012),
[COMAND model history](https://encyclopedia.pub/entry/28584)).

## Board identification

- PCB silkscreen part number: `A 024 545 35 65` (Mercedes A0245453565), board code `0767A07-LB`
- Handwritten/printed QC stickers: `2A783`, `3A783`
- Community-annotated photo and a traced PCB layer scan (from fill.sa, watermark on image)
  are in [`photos/`](photos/):
  - `1e8d83es-1920.jpg` — annotated board overview (connector designators)
  - `AUz1smYJ9S0a0gzw2T87V0j2c7M-1920.jpg` — traced solder-side layer scan (community RE)
  - `ywcStDRGshhLt-h0cz-Dr3LHlEo-1920.jpg` — assembled drive with flex cables
  - `photo_*.jpg` — original inspection photos

## Connectors (designators from the annotated community photo)

| Designator | Pins | Function |
|---|---|---|
| X5700 | 160 | Edge connector to COMAND mainboard (gold fingers) — power + data |
| X4000 | 10 | GPS module interface (GPS receiver sits in the same box) |
| X5000 | 16 | Optical pickup flex (RAE0142Z traverse) |
| X5003 | 11 | Spindle motor |
| X5002 | 2 | Loading (tray/slot) motor |
| X3810 / X3811 | — | Board-to-board white connectors |

## Chip inventory

**Official identifications** come from the Blaupunkt spare-parts list for MB Comand 2.0 E
(7 612 001 402 / 7 612 001 407, Ersatzteilliste 8 622 401 855, 2/99) — its "Prozessorplatte
8 638 300 360" section matches this board exactly (PCB silkscreen 8638300360). Designators
(Dxxxx/Vxxxx/MExxxx) and order numbers below are from that document.

| Designator | Marking on PCB | Official part (Blaupunkt order no.) | Role | Confidence |
|---|---|---|---|---|
| — (BGA, top) | NEC `ERIC-2 0117KU203` | not listed (custom ASIC, no spare) | Host processor: runs the program loaded from the navigation CD, talks to COMAND mainboard over X5700 | function inferred from firmware analysis |
| — (BGA, top) | NEC `D17120L13 0131M2` | not listed | companion LSI next to ERIC-2; likely CD-ROM host/channel glue or security ASIC | low |
| D 5050 | NEC `D63724BGM` | **µPD63724GM** (8 925 904 123) | CD signal processor LSI (digital servo + EFM/ECC channel) | **official** |
| D 5052 | NEC `78A035Y0B13` | **µPD784035** (8 925 904 537) | 78K4-family servo/mechanism control MCU (spindle, sled, loading, focus/track) | **official** |
| D 2270 | OKI `M6842 1S2P04-2` | **MSM9842GS** (8 925 904 218) | OKI audio IC (announcement/audio output path) | **official** |
| D 5000 | (near BA5970) | **uPC2574B** (8 925 904 261) | NEC dual audio op-amp | **official** |
| D 5001 | `BA5970FP` | **BA5970FP** (8 925 904 240) | Rohm actuator/sled motor driver | **official** |
| D 5002 | `BA6853FS` | **BA6853FS** (8 925 904 309) | Rohm 2-channel motor driver (loading/spindle) | **official** |
| D 5051 | `M12W 81643242C-15FN-X` | **µPD424260** (8 925 904 124) | NEC 256K×16 DRAM (4 Mbit), 15 ns — main work RAM of the CD channel/host | **official** |
| D 5053 | SOIC-8 `?C01` near pickup | **ST24C01** (8 609 503 000) | I²C 64×8 EEPROM — pickup calibration / configuration data, **dump candidate** | **official** |
| D 5054 | — | LM50CIM3X (8 925 901 859) | temperature sensor IC | **official** |
| D 5700/02/04/06 | 4× TSOP near edge conn. | **µPD4218165** ×4 (8 925 904 211) | NEC SRAM (1M×16) — RAM bank for ERIC-2/navigation program | **official** |
| D 5708 | — | µPD696633 (8 925 904 161) | NEC interface IC | **official** |
| D 5709 | — | µPD65848 (8 925 904 154) | NEC interface IC | **official** |
| D 5710/5711 | — | MAX706TESA / MAX811LEUS | reset/supervisor | **official** |
| D 5712 | TI `ALVC164245` | 74ALVC1642(45) (8 925 904 213) | 16-bit bus transceiver, 3.3↔5 V level shift to CD domain | **official** |
| D 5800/5801 | 2× TSOP-48 flash | **AM29DL800T** ×2 (8 925 904 553/4) | AMD 8 Mbit flash — firmware banks | **official** |
| D 5830 | `AM29LV160DT-90EI` | **AM29LV160B** (8 925 904 216) | AMD 16 Mbit flash — firmware | **official** |
| — | `LV20084` | Sanyo LV20084 (8.4 V regulator) | analog/RF supply | high |
| — | SOIC near X5000 (photo_…-53/54) | not listed (on CD-Laufwerk sub-PCB) | RF preamp / pickup coil driver of the optical channel | low |
| — | 4.096 MHz crystals ×2 | — | system clocks | certain |

Module-level order numbers from the same document: NAV module D1 = 8 618 842 555;
**CD drive assembly = 8 638 812 039** (mech type TN-CCD 1001 / BP 1, exploded view in the
document); GPS module = 8 638 348 887; gyro = 8 618 842 457; processor board = 8 638 300 360;
NAV main board = 8 638 300 546.

Signal chain (inferred): pickup (RAE0142Z) → RF preamp (small SOIC near X5000) →
D63724BGM (CD DSP: EFM/ECC) ↔ 78K4 servo MCU (mechanism) → ERIC-2 (host, loads
navigation program from CD into RAM, exchanges data with the COMAND mainboard over X5700).

## Why this matters for custom-disc research

- The firmware that validates navigation discs lives in the two 29LV160 flashes and in
  the per-disc program (`NAVECE_M.EXE`). Dumping the flashes is **E8** of the research plan.
- Disc-accept/reject decisions happen in ERIC-2 software — observing *why* a disc is
  rejected requires either flash static analysis (in progress) or bus observation (below).

## Debug / observation guide (no schematic available)

1. **X5700 (160-pin edge connector) — logic analyzer.** This is the drive↔mainboard link.
   Procedure: identify GND (continuity to shield/caps), then VCC rails with a scope,
   then find the clock, then capture traffic for three scenarios: known-good nav CD
   (2003 Teleatlas), good audio CD, and a rejected custom disc. Diff the captures —
   rejection reason (TOC type, file check, security sector read) should be visible.
   A 32–100 channel LA (e.g. DSLogic / KingstVIS + sigrok) is sufficient if the bus
   is demuxed 8/16-bit with strobes.
2. **Firmware dumps (offline, cheapest win).** The board carries two **AM29DL800T**
   (D5800/D5801) and one **AM29LV160** (D5830) — all TSOP and readable with a TL866II/
   XGecu + TSOP-48 adapter, or in-circuit with clips if the MCU tristates the bus at
   reset. Gives ground truth for the disc-validation code. (Note: flash contents may
   differ per unit/region — dumps pair naturally with the E8 firmware-diff task.)
3. **ST24C01 EEPROM (D5053, I²C).** Officially listed calibration/configuration EEPROM —
   clip on with any I²C dongle (Bus Pirate, CH341A, Arduino) and dump. Compare between
   drives from different map regions (2001/2003/2010 discs).
4. **78K4 servo MCU UART.** NEC 78K4 MCUs have an on-chip UART commonly brought out on
   two port pins and frequently used for factory debug. Requires the µPD784035-series
   datasheet pinout (not yet located) — candidates are the unpopulated via clusters
   near the MCU (visible in photo_…-39 as grouped vias).
5. **Test points.** The board has generous via clusters and tented pads around every
   BGA/QFP — good probing points once the community layer scan is aligned with the
   component photo.

## CD-R, CD-RW and laser

- Optical block: **Panasonic RAE0142Z** traverse (780 nm, one-beam, glass lens).
  Commercial listings explicitly state CD-DA / CD-ROM / **CD-RW** suitability
  ([IT-Tronics](https://www.it-tronics.de/lasereinheit-rae0142z-ic-laser-pickup-einsatz-fuer-cd-player-von-vielen-herstellern-fuer-cd-da-cd-rom-und-cd-rw-geeignet/),
  [WebSpareParts](https://webspareparts.com/products/rae0142z-laser-pickup-for-cd-players-optical-pickup-unit-cd-optical-block-replacement),
  [Amazon](https://www.amazon.ca/Original-RAE0142-RAE0142Z-RAE0150Z-Mechanism/dp/B0C1SHBM6V)).
  So **the hardware can read CD-RW**; if a CD-RW is rejected it is a firmware/AGC
  strategy issue, not the laser. Worth a direct test (CloneCD, min speed, .ccp profile
  as used for CD-R).
- Replacement: RAE0142Z is sold new (~$30) as a complete traverse with mechanism —
  swap the whole assembly, transplant the flat flex, keep the small EEPROM/calibration
  data if it sits on the pickup PCB.
- Reading degradation on CD-R burns is usually cured by lens cleaning and, if needed,
  careful laser-power trim (preset on the pickup PCB) — community reports that DX
  drives get picky with age and recover after a known-good navi disc "restores" them.

## Drive emulation (avoid burning CD-Rs)

- The drive does **not** expose IDE/ATAPI; X5700 is a proprietary 160-pin mezzanine
  bus between the drive board and the COMAND mainboard. No pinout is published.
- Feasible roadmap (matches the custom-disc goal): sniff X5700 with a logic analyzer
  (see above), identify command/address/data strobes, then emulate with an FPGA or
  fast MCU (RP2040/STM32H7) + level shifters serving ISO images from SD — the same
  approach as open-source ODE projects for game consoles. This is a project of its
  own; document captures in this repo if attempted.
- Commercial CD-changer emulators (Dension, xCarLink) target the optical D2B/MOST
  changer bus, **not** this internal drive — they do not apply here.

## Sources

- Connector designators + layer scan: fill.sa community thread (images watermarked
  `Fill.sa`), mirrored in `photos/`.
- RAE0142Z specs: Panasonic SL-S450 service manual (Traverse deck RAE0142Z),
  [ManualsLib](https://www.manualslib.com/manual/4114967/Panasonic-Sl-S450.html).
- COMAND 2.0 architecture (3 boxes, top box contents):
  [VK topic](https://vk.com/topic-91074655_31744012),
  [COMAND history (MDPI encyclopedia)](https://encyclopedia.pub/entry/28584).
- DX map generation: [COMAND model history](https://encyclopedia.pub/entry/28584).
- Official part identifications, module order numbers, CD drive assembly number and
  exploded view: Blaupunkt Ersatzteilliste 8 622 401 855 "MB Comand 2.0 E
  7 612 001 402/407" (2/99), section NAV-Modul / Prozessorplatte 8 638 300 360.
  (Document kept out of the repo for copyright; facts summarized above.)

## Addendum: DX-generation schematics (2026-11-16)

Found and archived full schematics of the sibling platform Blaupunkt TravelPilot DX:

- **TravelPilot DX-R70 SCH** (76 sheets, drawing 8 638 214 861) — complete service
  schematics: main board (Hauptplatte D04V00) incl. **HAUPTPROZESSOR** sheet with a
  documented **DEBUG-SCHNITTSTELLE**: test points laid out as a 20-pin Micromatch
  (D0–D7, A0–A2, RD, WRL, RSTOUT, CS_UART, UART_REQ) — Blaupunkt's standard byte-wide
  monitor/UART debug footprint. Same sheet carries the **CDC-IF** block (MM74HC595 +
  74HC14 + M74HC160, signals CDC_DATA_OUT/CDC_DATA_IN/CDC_CLK) — the external CD-changer
  serial bus, distinct from the internal nav drive link.
- **TravelPilot DX-V SCH** (31 sheets, 8 622 403 404, 06/02) — later DX revision.
- **TravelPilot DX-R5/R52 SM** (24 pp.).
- No public schematic of the COMAND processor board 8 638 300 360 (ERIC-2 side) exists
  as of this writing; the DX-R70/DX-V schematics are the closest references.

For the COMAND drive board this implies: look for a 20-point Micromatch-pattern test
point cluster near ERIC-2 for the monitor/UART debug interface, and treat the traced
solder-side scan in `photos/AUz1smYJ9S0a0gzw2T87V0j2c7M-1920.jpg` as the de-facto
schematic for X5700 pin recovery.


### DX-V Prozessorplatte 0787 A07 — full CD-chain reference (update)

Sheet-by-sheet read of DX-V SCH (pp. 17–22 = Prozessorplatte 0787 A07, "D2 MODUL")
shows the **same component designators as the COMAND processor board 8 638 300 360**,
i.e. it is the direct reference design for the COMAND nav processor board:

| Designator | Part | Function |
|---|---|---|
| D5700 | NEC uPD97298S1-801-B | Navigation processor (ERIC-2 family). Blocks: mem/IO buses, I2C, **CAN**, **UART1+UART3+SPI**, ADC i/f, DMA, "CDROM Interrupt", debug modules + **Emulator I/F** pins A2/A3/A8/A9/AB7–AB14 |
| D5050 | NEC uPD63724GM | CD DSP (RF processor/decoder), DRAM-buffered, 40-pin header X5032 to the drive mechanism (CDR_AD0–15 + servo/RF) |
| D5052 | NEC uPD784035YGC-806 | 78K0 drive/servo microcontroller, MICRO-SERVO-BUS/MICRO-DEC-BUS to D5700, 16.9344 MHz CD_MCK crystal |
| D5053 | ST24C01 | I2C EEPROM (identical part on COMAND) |
| D5051 | uPD424260 | CD buffer DRAM |
| D2270 | OKI MSM5842GS-2K (=MSM9842) | GPS baseband on AD-BUS (identical part on COMAND) |
| D5703 | TI TLV1544ID | 4-ch 10-bit ADC: drive telemetry (VS_SENSOR) + gyro (CH0X/CH0Y) |

CD data/audio path to the nav CPU: I2S (**VD_BCK/VD_LRCK/VD_SD** + **CD_MCK**),
analog **NF_ANA/NF_GND** (68-ohm series), control via **UART3** + interrupt.

**Practical debug points for COMAND (mirroring DX-V):**

1. **6-pin header X5031** by D5052: **SPY_DT/SPY_CK** — the standard NEC 78K0 SPY
   debug port of the drive servo MCU (plus test signals CD_RFCK/ERO/ERCK). Log drive
   firmware behaviour with a cheap logic analyzer.
2. **Emulator I/F** of uPD97298 near ERIC-2 — NEC emulator footprint; look for an
   unpopulated 2×7/2×8 header pattern.
3. **40-pin header X5032** by D5050 — the digital drive bus; probe with a 16+ channel
   analyzer to sniff the actual nav-disc sector protocol.
4. DX-R70 p.36 additionally documents Blaupunkt's 20-point Micromatch DEBUG
   interface (D0–D7, A0–A2, RD, WRL, RSTOUT, CS_UART, UART_REQ) — check for the same
   test-point cluster on COMAND.

Implication for custom-disc research: the drive link is UART-command + I2S-data, not
ATAPI; a drive emulator can be built by tapping X5032 (mechanism side) or X5031
(servo MCU spy) rather than the COMAND-proprietary X5700 inter-board link.
