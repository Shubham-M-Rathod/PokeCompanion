# PokeCompanion NetBridge: Technical Specification & Architecture

## 1. Core Idea & Operational Model

PokeCompanion NetBridge is a zero-patch, sidecar multiplayer companion tool for Generation 3 GBA Pokémon games (*FireRed US v1.0* as primary target, *Emerald US* via auto-detection).

Instead of synchronizing overworld cycles or patching ROM files, the game runs completely unmodified inside **mGBA**. The companion application runs as an external Python process that interacts directly with GBA memory via mGBA’s native GDB Remote Protocol over a local TCP socket (`localhost:2345`). A lightweight cloud WebSocket relay handles player discovery, stat inspection, asynchronous item exchange, and remote party battle injection.

---

## 2. Technical Architecture

```text
[ Vanilla GBA ROM ] (FireRed/Emerald in mGBA)
       ▲
       │  GDB Remote Protocol (TCP localhost:2345)
       ▼
[ Python Client Companion ] (PySide6 / PyQt6 UI)
  ├── Memory Engine: GDB client reading/writing RAM; XOR crypt & 16-bit checksum
  ├── State Manager: Local party, badges, and bag caches
  └── Net Engine: WebSocket client exchanging JSON payloads
       ▲
       │  WebSockets (JSON over TLS/TCP)
       ▼
[ Central Relay Server ] (Python FastAPI / asyncio)
  ├── Session/Lobby Manager: Tracks connected users, badges, and team rosters
  ├── Battle Broker: Dispatches challenge requests and relays 600-byte party data
  └── Cloud Bank Service: Atomic escrow ledger for shared items (SQLite/JSON)

```

### Communication & Protocol Design

1. **mGBA GDB Protocol**:
* Uses raw TCP to send GDB commands: `$m<addr>,<len>#checksum` (read) and `$M<addr>,<len>:<hex>#checksum` (write).
* Requires zero Lua scripts, zero injected DLLs, and no ROM modifications.


2. **Client-Server WebSocket Protocol**:
* `SYNC_STATE`: Client sends local player ID, badge bitflags, and decrypted party summary.
* `CHALLENGE_REQ` / `CHALLENGE_ACCEPT`: Relays active 6-mon party data between two clients.
* `CLOUD_ITEM_DEPOSIT` / `CLOUD_ITEM_WITHDRAW`: Atomic request/ack loop for shared inventory transfers.



---

## 3. Memory Layout & Cryptographic Rules (Gen 3 GBA)

### Memory Address Map

* **ROM Game Code Check (`0x080000AC`)**: 4-byte ASCII string (`BPRE` for FireRed US, `BPEE` for Emerald US).
* **Player Party (`600 bytes`)**: `0x02024284` (FireRed) / `0x020244EC` (Emerald). Contains 6 slots of 100 bytes each.
* **Opponent/Enemy Party (`600 bytes`)**: `0x0202402C` (FireRed) / `0x02024744` (Emerald). Used to inject opposing teams for battles.
* **SaveBlock1 Pointer**: `0x03005008` (FireRed) / `0x03005D8C` (Emerald).
* **Badge Flags**: `SaveBlock1 + 0x1450` (1 byte, 8 badge bits).
* **Bag Pocket**: `SaveBlock1 + 0x0310` (FireRed) / `SaveBlock1 + 0x0560` (Emerald). Stored as an array of `[u16 item_id, u16 quantity]`.



### Gen 3 Party Data Structure & Checksum Protocol

Each 100-byte Pokémon slot contains:

* Bytes `0x00–0x1F`: Unencrypted metadata (Personality ID / PID, Trainer ID / OTID, Nickname, Language, Flags).
* Bytes `0x20–0x4F`: **48-byte Encrypted Substructs** split into four 12-byte blocks:
* **Growth (G)**: Species, Item, Experience, Move PP bonuses, Friendship.
* **Attacks (A)**: Moves 1–4, PP 1–4.
* **EVs & Condition (E)**: EVs (HP, Atk, Def, Spd, SpAtk, SpDef) and Contest stats.
* **Miscellaneous (M)**: Pokerus, Met location, Origins, IVs, Ribbons.


* Bytes `0x50–0x63`: Battle status (Level, HP, Max HP, Atk, Def, Spd, SpAtk, SpDef).

**Decryption & Checksum Rules**:

1. **Block Order**: Determined by `(PID % 24)`, which defines the order of the four 12-byte blocks ($G, A, E, M$).
2. **XOR Key**: `EncryptionKey = PID ^ OTID`. The 48 bytes are split into 12 32-bit words, each XORed with `EncryptionKey`.
3. **Checksum Recalculation**: Sum of all 24 16-bit words across the decrypted 48 bytes, truncated to 16 bits. Must be written to bytes `0x1C–0x1D` before writing back to RAM; otherwise, the game flags the slot as a "Bad Egg".

---

## 4. Requirements Specification

### Functional Requirements (FR)

* **FR-1: Auto-Detect Game Version**: Read ROM code at `0x080000AC` on launch; map addresses for `BPRE` (FireRed) or `BPEE` (Emerald).
* **FR-2: Read & Mirror Live Stats**: Extract player name, 8 Gym Badges, and Pokédex seen/caught numbers via GDB commands; publish state to the relay server.
* **FR-3: Parse & Inspect Party Data**: Decrypt 6 party slots on interval (100 ms – 500 ms) using PID/OTID XOR logic and render party details (Species, Level, Moves, IVs/EVs) in the desktop UI.
* **FR-4: Shared Cloud Bag**:
* *Deposit*: Zero out or decrement item quantity in RAM, recalculate checksum/save structures, and send increment event to server ledger.
* *Withdraw*: Server validates item availability, decrements server ledger, and client injects item ID + quantity into an empty bag slot in RAM.


* **FR-5: Battle Request & Team Injection**:
* Player A challenges Player B via UI; Player B accepts.
* Player A’s 600-byte party data is transmitted to Player B via WebSocket.
* Player B's client writes the 600 bytes directly into the Opponent Party address (`0x0202402C` on FireRed) and triggers/engages an in-game trainer battle to fight Player A's actual lineup.



### Non-Functional Requirements (NFR)

* **NFR-1: Pristine ROM Execution**: 100% vanilla ROM binary (`.gba`). No patches (`.ips`/`.bps`), no ROM header modifications, no assembly hooks.
* **NFR-2: No Emulator Plugin Dependencies**: Uses native GDB server functionality. No embedded Lua, C++ DLL injection, or external emulator extensions.
* **NFR-3: Memory Integrity**: All memory writes to party structures must recalculate the 16-bit additive checksum to prevent game lockups or Bad Egg corruption.
* **NFR-4: Transaction Safety**: Shared Bag operations must follow an atomic checkout pattern: if local RAM injection fails, the server must roll back the ledger to avoid item duplication or loss.
* **NFR-5: Performance**: Local memory polling cycle must execute in under 20 ms. Remote challenge events must propagate in under 200 ms over WebSockets.

---