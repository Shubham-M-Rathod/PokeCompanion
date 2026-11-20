PokeCompanion NetBridge is a zero-patch, sidecar multiplayer companion tool for Generation 3 GBA Pokémon games (*FireRed US v1.0* as primary target, *Emerald US* via auto-detection).

Instead of synchronizing overworld cycles or patching ROM files, the game runs completely unmodified inside **mGBA**. The companion application runs as an external Python process that interacts directly with GBA memory via mGBA’s native GDB Remote Protocol over a local TCP socket (`localhost:2345`). A lightweight cloud WebSocket relay handles player discovery, stat inspection, asynchronous item exchange, and remote party battle injection.

<hr/>

https://github.com/user-attachments/assets/783dccd4-fe96-46be-9331-059f10f560ef
