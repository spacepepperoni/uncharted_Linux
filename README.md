# Uncharted: The Nathan Drake Collection for Linux/Steam Deck

👾Join the Discord: https://discord.gg/X2YhSJg6R2

**Uncharted 1, 2 and 3 from the PS4 collection running natively on Linux, forked by spacepepperoni from [SuperMedo](https://github.com/Supermedo).**

**This launcher allows you to play Uncharted 1-3 by direct launch as well as desktop/steam shortcuts. This release also contains a Steam Deck mode that optimizes the games to run on Steam Deck.**
<img width="1316" height="809" alt="image" src="https://github.com/user-attachments/assets/0e9cf5c1-2094-465f-b1b5-98d5575e88fe" />

## Distributions tested
✅ Confirmed Working: SteamOS 3.7, Fedora 44, Debian 13 CachyOS, Arch, openSUSE Tumbleweed, Ubuntu 24.04, Mint 22, Pop!OS 24.04

❌ Not Supported: Ubuntu 22.04 and older, Linux Mint 21 and older, Debian 12 and older 

## Download
1. Download **[Uncharted-x86_64.AppImage](https://github.com/spacepepperoni/uncharted_Linux/releases/latest/download/Uncharted-x86_64.AppImage)**.
2. Right-click it, open **Properties → Permissions** and tick **Is executable** (or
   **Allow executing file as program**).

## Updates

This client ships with a built in updater that can be toggled on/off, and updates from two sources: the main repo & this fork. 

- In the launcher itself, you'll see available updates in the bottom left of the launcher.
<img width="400" height="98" alt="image" src="https://github.com/user-attachments/assets/911e9ded-29b0-465b-8c18-5f589e987063" />

- If launching one of the games through Steam or Game Mode (Steam Deck), you will be prompted with an update screen if one is available.
<img width="400" height="200" alt="image" src="https://github.com/user-attachments/assets/b8c1b51d-fee3-42b8-a200-edb5d8c8712e" />


## Steam Deck

- Download the [.AppImage](https://github.com/spacepepperoni/uncharted_Linux/releases/latest/download/Uncharted-x86_64.AppImage) and add the games to Steam to play in Game Mode.
- Adding the games to your Steam Library grabs the cover art from SteamGridDB
- In the Settings tab, a Steam Deck mode is auto-selected if you are on SteamOS. With this enabled, expect an average of 25-30fps with occasional dips during demanding segments.
- Steam Deck mode automatically enables Steam Controller buttons
  <img width="1280" height="800" alt="image" src="https://github.com/user-attachments/assets/b63d118c-b9ed-46ac-b3d7-fc739cf927b6" />
- It is recommended to set your FPS cap to 30fps and set Manual GPU Clock to 1300mhz.

## Files needed 

You must have an unencrypted extracted dump of the Uncharted: The Nathan Drake Collection (CUSA02320) v1.00.

Point the launcher to this folder in the Game tab. By default, a new Saves folder will appear within your Game folder.

Once your game folder has been specified: Play, Add to Steam (recommended for Steam Deck) or create a Desktop shortcut.

> **No game files are included.** You need your own decrypted dump of the collection
> (CUSA02343, CUSA02320, ...: the folder with eboot.bin, big2-ps4_Shipping.elf,
> big3-ps4_Shipping.elf, sce_sys, u1data, u2data and u3data).
> This project is not affiliated with Sony Interactive Entertainment or Naughty Dog.

## System Requirements

- 64-bit x86 Linux with glibc 2.41 or newer: SteamOS 3.7+, Debian 13, Ubuntu 25.04, Fedora 42,
  Arch, or anything newer.
- A graphics card with Vulkan 1.3 with 6 GB of video memory or more.
  4 GB cards (GTX 1650, RX 570) run out of video memory and crash after a while; on those, keep
  Anti-aliasing and Frame generation off.
- About 8 GB of free RAM


## Reporting a bug
- Open the launcher, go to **Advanced** and click **Copy log for GitHub** (Steam Deck: in Desktop Mode). It copies your system details and the last game log, without your home folder or user name.
- Open a new issue in the [Issues tab](https://github.com/spacepepperoni/uncharted_Linux/issues/new?template=bug_report.yml), choose **Bug report**, and paste the log into the **Log** field.
- Say which game and where in it the problem happened.

## Credits

Built on [bbport](https://github.com/deadinside28/bloodborne_pc), the native Linux port of
Bloodborne by deadinside28, and on the [shadPS4](https://github.com/shadps4-emu/shadPS4)
renderer. Video decoding (Videodec2) and the DLSS bridge come from
[IFreemz/shadPS4-Bloodborne-DLSS-FSR](https://github.com/IFreemz/shadPS4-Bloodborne-DLSS-FSR).
Thanks to Mindro for the shadPS4 Uncharted build that showed which problems to look for.
Performance work on Uncharted 2's draw recording and read-backs is [che2281337](https://github.com/che2281337)'s, and several freeze fixes are from [drakolordx7's community build](https://github.com/drakolordx7/uncharted_pc).
The render resolution patch (scripts/render_res.py, cutscene movie scaling in gpu/shim/bbport_movie.cpp, the Uncharted 2 aim focus fix) is ported from [BilalReloaded's Uncharted PC port](https://github.com/bc160201983/Uncharted-The-Nathan-Drake-Collection-PC-port) (GPL-2.0-or-later).

Also used: [FSR-Vulkan](https://github.com/FireBurn/FSR-Vulkan) and the AMD FidelityFX SDK (FSR),
FSR 4 assets from [FireBurn/Q2RTX](https://github.com/FireBurn/Q2RTX), the
[NVIDIA DLSS SDK](https://github.com/NVIDIA/DLSS) (`nvngx_dlss.dll` under NVIDIA's license),
[LibAtrac9](https://github.com/Thealexbarney/LibAtrac9), [SDL3](https://github.com/libsdl-org/SDL),
[FFmpeg](https://ffmpeg.org), [Dear ImGui](https://github.com/ocornut/imgui),
[sirit](https://github.com/shadps4-emu/sirit), [magic_enum](https://github.com/Neargye/magic_enum),
[xbyak](https://github.com/herumi/xbyak),
[Vulkan Memory Allocator](https://github.com/GPUOpen-LibrariesAndSDKs/VulkanMemoryAllocator),
[MSYS2](https://www.msys2.org) / [LLVM](https://llvm.org), [PyInstaller](https://pyinstaller.org),
[Pillow](https://python-pillow.org) and the Cinzel font (SIL Open Font License).

NVIDIA, GeForce RTX and DLSS are trademarks of NVIDIA Corporation.

## License

GNU GPL v2 or later ([LICENSE](LICENSE)). Third-party components keep their own licenses
(see `licenses/` in the download).
