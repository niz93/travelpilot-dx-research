# References and provenance

## Primary evidence

The format findings in this repository were derived from eleven local TeleAtlas DX disc sets and static analysis of their `NAVECE_M.EXE` NEC V810 executable. Five identical copies of that executable were checked: 1,579,561 bytes, SHA-256 `6fa3cfd7331d28a2f417f0b8b566dd625157d0d8d5f43452c3892195d1a443f1`.

Source discs, extracted data, and firmware are deliberately not distributed. Machine-readable validation outputs are in `results/`; rendered examples are in `examples/`.

The presence of `gdf_syntax.GDF_3_0.1.1` and related compilation metadata establishes GDF as input to the Bosch production pipeline. It does not establish that the compiled TPMAP2 or TPNAV2 records are identical to ISO GDF records.

## External references

1. OpenStreetMap Help, “Blaupunkt TravelPilot DX CD structure”  
   https://help.openstreetmap.org/questions/84568/blaupunkt-travelpilot-dx-cd-structure/

2. OpenStreetMap Community, “Blaupunkt TravelPilot DX CD structure”  
   https://community.openstreetmap.org/t/blaupunkt-travelpilot-dx-cd-structure/1544

3. OpenStreetMap Wiki, “GDF”  
   https://wiki.openstreetmap.org/wiki/GDF

4. Wikipedia, “Geographic Data Files”  
   https://en.wikipedia.org/wiki/Geographic_Data_Files

5. Safe Software, FME Form, “Geographic Data Files (GDF) Reader”  
   https://docs.safe.com/fme/html/FME-Form-Documentation/FME-ReadersWriters/gdf/gdf.htm

6. ISO 14825:2011, Geographic Data Files (GDF) — GDF5.0  
   https://www.iso.org/standard/54610.html

7. ISO 14825:2011 sample document  
   https://cdn.standards.iteh.ai/samples/54610/99707075e4e34ac9b7c00a09b5fca25c/ISO-14825-2011.pdf

8. Neill Corlett, published `unecm` source code (EDC/ECC reference implementation)  
   https://beardedmaker.com/wiki/index.php?title=Code:_unecm

9. MBWorld, “COMAND 2.5 Reverse engineering project”  
   https://mbworld.org/forums/audio-electronics/840899-comand-2-5-reverse-engineering-project.html

10. Comand Online, Teleatlas DX disc compatibility listing  
    https://www.commandonline.co.uk/teleatlas-italy-dx.html?printable=Y

11. Audiocom, Blaupunkt DX Germany + Major Roads of Europe 2013–2014 compatibility listing  
    https://www.audiocom.cz/navigacni-software/blaupunkt/navigacni-cd-rom-dx-mapa-nemecko-2013-2014-hlavni-trasy-evropy-mre-2013-2014--3366cz

12. Auto Świat, “Fabryczna nawigacja – prowadzi w stronę kłopotów”  
    https://www.auto-swiat.pl/porady/fabryczna-nawigacja-prowadzi-w-strone-klopotow/875cpre

13. DRIVE2 (Russian), “Анализируем навигаторы на основе Blaupunkt-TravelPilot-DX” — early community file-signature analysis (`TPNAV2_COMPRESSED` markers, `info.txt` and `MAP00001.MAP` header breakdown)  
    https://www.drive2.ru/b/625641908487587604/

14. DRIVE2 (Russian), earlier companion post by the same author introducing the format-research effort and pointing to the OSM Community thread  
    https://www.drive2.ru/b/459571122472515752/

The external compatibility listings are cross-references, not hardware validation. Their published model-year ranges and naming conventions vary.

## Third-party software

- Python: https://www.python.org/
- pycdlib: https://github.com/clalancette/pycdlib
- Matplotlib: https://matplotlib.org/

The Windows bootstrap downloads Python only from `www.python.org` over HTTPS and checks its Authenticode signature before execution. Python, pycdlib, and Matplotlib retain their respective licenses; they are not vendored in this repository.
